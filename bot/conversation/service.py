import logging
import time
from collections import Counter

from bot.gateway.events import GroupIncrease, Message, message_from_dict
from bot.group.router import GroupRouter
from bot.group.quota import QuotaService
from bot.group.welcome import WelcomeService
from bot.llm.base import ProviderError
from bot.memory.session import SessionPolicy
from bot.personality import SYSTEM_PROMPT
from bot.presentation.plain import format_answer, split_for_qq
from bot.security.policy import allowed, pseudonym

logger = logging.getLogger(__name__)


class ConversationService:
    def __init__(self, settings, store, limiter, provider, sender):
        self.settings, self.store, self.limiter = settings, store, limiter
        self.provider, self.sender = provider, sender
        self.metrics = Counter()
        self.router = GroupRouter(settings)
        self.quota = QuotaService(settings, limiter)
        self.welcome = WelcomeService(settings, store, limiter, sender, self.metrics)
        self.group_sessions = SessionPolicy(
            getattr(settings, "group_recent_turns", 3),
            getattr(settings, "group_history_chars", 6400),
            getattr(settings, "group_idle_ttl", 1800),
            getattr(settings, "group_absolute_ttl", 7200),
        )

    def _safe_id(self, value):
        return pseudonym(str(value), self.settings.app_secret)[:12]

    def _state(self, state, message, reason=""):
        kind = "group" if getattr(message, "group_id", None) else "private"
        logger.info("event_state=%s kind=%s event=%s group=%s user=%s reason=%s",
                    state, kind, self._safe_id(getattr(message, "event_id", "")),
                    self._safe_id(getattr(message, "group_id", "private")),
                    self._safe_id(getattr(message, "user_id", "")), reason)

    async def handle(self, event):
        if isinstance(event, GroupIncrease):
            await self.welcome.handle(event)
            return
        if not isinstance(event, Message):
            return
        if event.group_id:
            await self._handle_group(event)
        else:
            await self._handle_private(event)

    async def recover_pending(self):
        """Resume local, already-persisted work without history replay."""
        if not getattr(self.settings, "recovery_local_enabled", True):
            return 0
        loader = getattr(self.store, "recoverable_tasks", None)
        if loader is None:
            return 0
        recovered = 0
        owner = f"bot-recovery-{id(self)}"
        for record in await loader(limit=getattr(self.settings, "max_pending", 32)):
            message = message_from_dict(record.get("message_json"))
            if message is None or record.get("source", "live") == "history_recovery":
                continue
            event_key = str(record.get("event_key", ""))
            conversation = str(record.get("conversation_key", ""))
            if not event_key or not conversation:
                continue
            leaser = getattr(self.store, "acquire_recovery_lease", None)
            if leaser is not None and not await leaser(event_key, owner, 180):
                continue
            message = message.__class__(**{**message.__dict__, "persistence_key": event_key})
            try:
                if record.get("state") == "ready_to_send" and record.get("answer_parts"):
                    if await self._send_recovered_answer(message, record):
                        recovered += 1
                    continue
                claimed = (event_key, conversation,
                           pseudonym(message.self_id + ":" + message.user_id, self.settings.app_secret))
                if message.group_id:
                    await self._handle_group(message, claimed=claimed, recovery=True)
                else:
                    await self._handle_private(message, claimed=claimed)
                recovered += 1
            finally:
                releaser = getattr(self.store, "release_recovery_lease", None)
                if releaser is not None:
                    await releaser(event_key, owner)
        return recovered

    async def _send_recovered_answer(self, message, record):
        if message.group_id and not self.router.authorized(message):
            await self.store.mark(record["event_key"], "recovery_not_authorized")
            return False
        parts = record.get("answer_parts") or []
        if not isinstance(parts, list) or not parts:
            return False
        reply_ids = []
        try:
            for index, part in enumerate(parts[:getattr(self.settings, "max_answer_parts", 2)]):
                job_id = f"{record['event_key']}:{index}"
                marker = getattr(self.store, "mark_outbox_sending", None)
                if marker is not None:
                    await marker(job_id, f"recovery-{time.time_ns()}")
                if message.group_id:
                    segments = self._reply_segments(message, str(part), include_reply=(index == 0))
                    reply_id = await self._send_segments(message, segments, str(part))
                else:
                    reply_id = await self.sender.send(message, str(part))
                reply_ids.append(reply_id)
                confirmer = getattr(self.store, "mark_outbox_sent", None)
                if confirmer is not None:
                    await confirmer(job_id, reply_id)
                await self._record_outbound(reply_id, message, record["event_key"])
            answer = "\n\n".join(str(part) for part in parts)
            await self.store.complete(record["event_key"], record["conversation_key"],
                                      message.text, answer, reply_ids[-1],
                                      getattr(self.settings, "group_recent_turns", 3)
                                      if message.group_id else getattr(self.settings, "context_turns", 8))
            self.metrics["recovered_sent"] += 1
            return True
        except Exception:
            await self.store.mark(record["event_key"], "delivery_uncertain")
            self.metrics["recovered_delivery_uncertain"] += 1
            return False

    async def _known_reply(self, message):
        if not message.reply_to:
            return False
        method = getattr(self.store, "is_known_bot_reply", None)
        if method is None:
            return False
        try:
            return bool(await method(message.reply_to, message.group_id))
        except Exception:
            # A quote validation failure must not become an LLM trigger.
            return False

    async def _claim(self, message, conversation=None):
        event = pseudonym(message.event_id, self.settings.app_secret)
        conversation = conversation or pseudonym(message.conversation_id, self.settings.app_secret)
        persisted = getattr(message, "persistence_key", "")
        if persisted:
            return persisted, conversation, pseudonym(message.self_id + ":" + message.user_id,
                                                       self.settings.app_secret)
        if not await self.store.claim(event, conversation):
            self.metrics["duplicate"] += 1
            self._state("ignored", message, "duplicate_event")
            return None, None, None
        return event, conversation, pseudonym(message.self_id + ":" + message.user_id,
                                               self.settings.app_secret)

    async def _record_outbound(self, reply_id, message, event_key):
        recorder = getattr(self.store, "record_outbound", None)
        if recorder is not None:
            await recorder(reply_id, message.self_id, group_id=message.group_id,
                           user_id=message.user_id, event_key=event_key)

    async def _record_usage(self, event_key, message, user_key, started, status,
                            usage=None, attempts=None):
        recorder = getattr(self.store, "record_usage", None)
        if recorder is None:
            return
        usage = usage if isinstance(usage, dict) else getattr(self.provider, "last_usage", {})
        if not isinstance(usage, dict):
            usage = {}
        attempts = getattr(self.provider, "last_attempts", 1) if attempts is None else attempts
        try:
            attempts = int(attempts or 0)
        except (TypeError, ValueError):
            attempts = 0
        try:
            await recorder(event_key, message.group_id, user_key, attempts, usage,
                           int(max(0, (time.monotonic() - started) * 1000)), status)
        except Exception:
            # Usage accounting must never turn a completed provider call into
            # a lost reply. The paid path already fails closed before calling
            # the provider when Redis/quota storage is unavailable.
            logger.warning("usage_record_failed event=%s", str(event_key)[:12])

    async def _send_segments(self, message, segments, fallback_text):
        sender = getattr(self.sender, "send_segments", None)
        if sender is not None:
            return await sender(message, segments)
        return await self.sender.send(message, fallback_text)

    async def _send_answer_parts(self, message, parts, group=False):
        """Send at most two already-rendered parts through the existing gateway."""
        reply_ids = []
        for index, part in enumerate(parts):
            if group:
                segments = self._reply_segments(message, part, include_reply=(index == 0))
                reply_ids.append(await self._send_segments(message, segments, part))
            else:
                reply_ids.append(await self.sender.send(message, part))
        return reply_ids

    def _reply_segments(self, message, text, at=None, include_reply=True):
        segments = []
        if include_reply and getattr(message, "message_id", None):
            segments.append({"type": "reply", "data": {"id": message.message_id}})
        if at:
            segments.append({"type": "at", "data": {"qq": str(at)}})
        segments.append({"type": "text", "data": {"text": text}})
        return segments

    async def _finish_local(self, message, event_key, conversation, text, reason):
        self._state("queued", message, reason)
        try:
            reply_id = await self._send_segments(message, self._reply_segments(message, text), text)
            await self._record_outbound(reply_id, message, event_key)
            await self.store.mark(event_key, "sent", reply_id)
        except Exception:
            self.metrics["delivery_uncertain"] += 1
            await self.store.mark(event_key, "delivery_uncertain")
            self._state("failed", message, "delivery_uncertain")
            return
        self.metrics["sent"] += 1
        self._state("sent", message, reason)

    async def _lead_member(self, message, target):
        probe = getattr(self.sender, "member_in_group", None)
        if probe is None:
            return False
        try:
            return bool(await probe(message.group_id, target))
        except Exception:
            return False

    async def _handoff(self, message, route, event_key, conversation):
        target = str(getattr(self.settings, "association_lead_target_qq", "") or "")
        if not target or not await self._lead_member(message, target):
            await self.store.mark(event_key, "handoff_unavailable")
            self.metrics["handoff_unavailable"] += 1
            text = route.text if route.kind == "handoff_prompt" else "我暂时无法确认协会负责人在本群或当前是否可提醒，请稍后再试或直接联系群内管理。"
            await self._finish_local(message, event_key, conversation, text, "handoff_unavailable")
            return
        try:
            user_key = f"handoff:user:{message.group_id}:{message.user_id}"
            group_key = f"handoff:group:{message.group_id}"
            if hasattr(self.limiter, "allow_key"):
                question = pseudonym((route.text or message.text).strip()[:600], self.settings.app_secret)
                if not await self.limiter.allow_key(f"handoff:question:{message.group_id}:{message.user_id}:{question}", 86400):
                    await self.store.mark(event_key, "handoff_rate_limited")
                    self.metrics["handoff_rate_limited"] += 1
                    return
                if not await self.limiter.allow_key(user_key, getattr(self.settings, "handoff_requester_cooldown", 1800)):
                    await self.store.mark(event_key, "handoff_rate_limited")
                    self.metrics["handoff_rate_limited"] += 1
                    return
                if not await self.limiter.allow_key(group_key, getattr(self.settings, "handoff_group_cooldown", 600)):
                    await self.store.mark(event_key, "handoff_rate_limited")
                    self.metrics["handoff_rate_limited"] += 1
                    return
            if hasattr(self.limiter, "allow_count"):
                if not await self.limiter.allow_count("handoff:target", getattr(self.settings, "handoff_global_per_hour", 3), 3600):
                    await self.store.mark(event_key, "handoff_rate_limited")
                    self.metrics["handoff_rate_limited"] += 1
                    return
            if route.kind == "handoff_prompt":
                text = route.text
                segments = self._reply_segments(message, text)
            else:
                text = "有同学希望请协会负责人本人答复上面的问题，方便时请查看；我先不代替负责人作答。"
                segments = self._reply_segments(message, text, at=target)
            self._state("queued", message, "handoff")
            reply_id = await self._send_segments(message, segments, text)
            await self._record_outbound(reply_id, message, event_key)
            await self.store.mark(event_key, "sent", reply_id)
            self.metrics["handoff_sent"] += 1
            self.metrics["sent"] += 1
            self._state("sent", message, "handoff")
        except Exception:
            self.metrics["delivery_uncertain"] += 1
            await self.store.mark(event_key, "delivery_uncertain")
            self._state("failed", message, "handoff_delivery_uncertain")

    async def _handle_group(self, message, claimed=None, recovery=False):
        if not self.router.authorized(message):
            self.metrics["ignored"] += 1
            self._state("ignored", message, "group_not_authorized")
            return
        route = self.router.route(message, await self._known_reply(message), recovery=recovery)
        if route.kind == "ignored":
            self.metrics["ignored"] += 1
            self._state("ignored", message, route.reason)
            return
        if claimed is None:
            event_key, conversation, _ = await self._claim(message)
        else:
            event_key, conversation, _ = claimed
        if event_key is None:
            return
        if route.kind in ("handoff", "handoff_prompt"):
            await self._handoff(message, route, event_key, conversation)
            return
        if route.kind == "local":
            await self._finish_local(message, event_key, conversation, route.text, route.reason)
            return
        if route.kind == "clear_session":
            self.group_sessions.clear(conversation)
            clearer = getattr(self.store, "clear_conversation", None)
            if clearer is not None:
                await clearer(conversation)
            await self._finish_local(message, event_key, conversation, route.text, route.reason)
            return
        if not self.settings.api_key:
            self.metrics["waiting_api_key"] += 1
            await self.store.mark(event_key, "waiting_api_key")
            self._state("ignored", message, "missing_api_key")
            return
        user = pseudonym(message.self_id + ":" + message.user_id + ":" + (message.group_id or ""),
                         self.settings.app_secret)
        try:
            if hasattr(self.limiter, "allow_key"):
                user_allowed = await self.limiter.allow_key(
                    f"group:user:{message.group_id}:{message.user_id}",
                    getattr(self.settings, "group_user_cooldown", 6),
                )
            else:
                user_allowed = await self.limiter.allow(user)
            if not user_allowed:
                self.metrics["rate_limited"] += 1
                await self.store.mark(event_key, "rate_limited")
                self._state("ignored", message, "user_rate_limit")
                return
        except Exception:
            self.metrics["rate_limited"] += 1
            await self.store.mark(event_key, "rate_limiter_unavailable")
            self._state("ignored", message, "rate_limiter_unavailable")
            return
        estimate_input = min(getattr(self.settings, "group_input_token_cap", 6000),
                             max(1, len(message.text) // 4 + 400))
        reserved, reason = await self.quota.reserve(user, message.group_id, estimate_input,
                                                    getattr(self.settings, "group_max_output", 800))
        if not reserved:
            self.metrics["quota_rejected"] += 1
            await self.store.mark(event_key, "quota_rejected")
            self._state("ignored", message, reason)
            return
        await self.quota.acquire()
        try:
            await self._generate_and_send(message, event_key, conversation, user, group=True)
        finally:
            self.quota.release()

    async def _handle_private(self, message, claimed=None):
        if not allowed(message, self.settings):
            self.metrics["ignored"] += 1
            self._state("ignored", message, "policy")
            return
        if not self.settings.api_key:
            self.metrics["waiting_api_key"] += 1
            self._state("ignored", message, "missing_api_key")
            return
        if claimed is None:
            event_key, conversation, user = await self._claim(message)
        else:
            event_key, conversation, user = claimed
        if event_key is None:
            return
        try:
            if not await self.limiter.allow(user):
                self.metrics["rate_limited"] += 1
                await self.store.mark(event_key, "rate_limited")
                self._state("ignored", message, "user_rate_limit")
                return
        except Exception:
            self.metrics["rate_limited"] += 1
            await self.store.mark(event_key, "rate_limiter_unavailable")
            return
        await self._generate_and_send(message, event_key, conversation, user, group=False)

    async def _generate_and_send(self, message, event_key, conversation, user, group=False):
        s = self.settings
        if group:
            session_active = self.group_sessions.active(conversation)
            history = (await self.store.history(conversation, getattr(s, "group_recent_turns", 3))) if session_active else []
            history = self.group_sessions.trim(history)
        else:
            history = await self.store.history(conversation, s.context_turns)
        while history and sum(len(m["content"]) for m in history) > s.context_chars:
            history = history[2:]
        messages = [{"role": "system", "content": SYSTEM_PROMPT}, *history,
                    {"role": "user", "content": message.text}]
        self.metrics["accepted"] += 1
        self._state("generating", message, "model")
        started = time.monotonic()
        result = None
        try:
            attempts = getattr(s, "group_llm_attempts", 2) if group else None
            max_tokens = getattr(s, "group_max_output", 800) if group else None
            provider_result_method = getattr(type(self.provider), "complete_result", None)
            if provider_result_method is not None:
                result = await self.provider.complete_result(messages, attempts=attempts,
                                                              max_tokens=max_tokens)
                answer = result.text
                result_usage = getattr(result, "usage", {})
                result_attempts = getattr(result, "attempts", None)
                truncated = bool(getattr(result, "truncated", False))
            else:
                answer = await self.provider.complete(messages, attempts=attempts,
                                                       max_tokens=max_tokens)
                result_usage = None
                result_attempts = None
                truncated = False
            self.metrics["llm_success"] += 1
            await self._record_usage(event_key, message, user, started,
                                     "truncated" if truncated else "success",
                                     result_usage, result_attempts)
        except ProviderError as exc:
            self.metrics["llm_error"] += 1
            logger.warning("provider_error event=%s code=%s", event_key[:12], str(exc))
            await self._record_usage(event_key, message, user, started, str(exc))
            await self.store.mark(event_key, "provider_error")
            try:
                fallback = "暂时无法连接 AI 服务，请稍后再试。"
                segments = self._reply_segments(message, fallback) if group else None
                reply_id = await self._send_segments(message, segments, fallback) if segments else await self.sender.send(message, fallback)
                await self._record_outbound(reply_id, message, event_key)
            except Exception:
                self.metrics["delivery_uncertain"] += 1
            return
        answer = format_answer(answer)
        if truncated:
            answer += "\n\n（模型达到输出上限，内容可能不完整；请回复“继续”）"
        split = split_for_qq(answer, getattr(s, "qq_part_limit", 4000),
                             getattr(s, "max_answer_parts", 2))
        parts = split.parts or ("暂时没有可发送的完整答案。",)
        if split.truncated and "未发送" not in parts[-1]:
            parts = (*parts[:-1], parts[-1] + "\n\n（答案过长，后续部分未发送；请缩小问题范围后继续）")
        answer = "\n\n".join(parts)
        saver = getattr(self.store, "save_answer", None)
        if saver is not None:
            try:
                await saver(event_key, message, answer, parts, result,
                            ttl_seconds=getattr(s, "recovery_pending_ttl", 7200))
            except Exception:
                await self.store.mark(event_key, "answer_persist_failed")
                self._state("failed", message, "answer_persist_failed")
                return
        await self.store.mark(event_key, "sending")
        try:
            reply_ids = await self._send_answer_parts(message, parts, group=group)
            reply_id = reply_ids[-1]
        except Exception:
            self.metrics["delivery_uncertain"] += 1
            await self.store.mark(event_key, "delivery_uncertain")
            self._state("failed", message, "delivery_uncertain")
            return
        for reply_id in reply_ids:
            await self._record_outbound(reply_id, message, event_key)
        keep = getattr(s, "group_recent_turns", 3) if group else s.context_turns
        await self.store.complete(event_key, conversation, message.text, answer, reply_id, keep)
        self.metrics["sent"] += 1
        self._state("sent", message, "model")

    async def close(self):
        await self.welcome.close()
