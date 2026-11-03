import asyncio
import json
import logging
import time
import uuid
from dataclasses import replace
from collections import Counter

from aiohttp import web, WSMsgType

from bot.security.policy import authorized
from bot.security.policy import pseudonym
from .events import GroupIncrease, parse_event, parse_notice

logger = logging.getLogger(__name__)


class OneBotGateway:
    def __init__(self, settings):
        self.settings = settings
        self.ws = None
        self.self_id = None
        self.online = False
        self.last_event = 0.0
        self.pending = {}
        self.queue = asyncio.Queue(maxsize=settings.max_pending)
        self.send_lock = asyncio.Lock()
        self.last_send = 0.0
        self.connections = 0
        self.accepting = True
        self.group_pending = Counter()
        self.store = None

    def attach_store(self, store):
        self.store = store

    def _persistable(self, message):
        """Apply cheap trigger filters before storing any group正文."""
        # Notice events are routed to the welcome service but do not carry a
        # message body.  They must never enter the message inbox path: calling
        # ``len(message.text)`` on a GroupIncrease used to tear down the
        # reverse WebSocket as soon as a member joined a group.
        if isinstance(message, GroupIncrease):
            return False
        if not message.group_id:
            return True
        enabled = getattr(self.settings, "group_features_enabled",
                          getattr(self.settings, "group_enabled", False))
        allowed = getattr(self.settings, "allowed_group_ids", None)
        if not enabled or allowed is not None and message.group_id not in allowed:
            return False
        if getattr(message, "anonymous", False) or getattr(message, "at_all", False):
            return False
        if len(message.text) > getattr(self.settings, "max_input", 4000):
            return False
        target = str(getattr(self.settings, "association_lead_target_qq", "") or "")
        return bool(message.mentioned or message.reply_to or target and target in message.at_ids)

    @property
    def ready(self):
        return bool(self.ws is not None and not self.ws.closed and self.online
                    and time.monotonic() - self.last_event < 90)

    async def websocket(self, request):
        if not authorized(request.headers.get("Authorization"), self.settings.onebot_token):
            raise web.HTTPUnauthorized()
        sid = request.headers.get("X-Self-ID", "")
        if len(sid) > 20 or not sid.isascii() or not sid.isdecimal() or int(sid) <= 0:
            raise web.HTTPBadRequest()
        if not self.accepting or self.ws is not None and not self.ws.closed:
            raise web.HTTPConflict()
        ws = web.WebSocketResponse(heartbeat=30, max_msg_size=65536)
        await ws.prepare(request)
        self.ws, self.self_id, self.online = ws, sid, False
        self.last_event = time.monotonic()
        self.connections += 1
        logger.info("onebot_connected count=%s", self.connections)
        try:
            async for frame in ws:
                if frame.type != WSMsgType.TEXT:
                    continue
                try:
                    event = json.loads(frame.data)
                    if not isinstance(event, dict):
                        continue
                except (ValueError, TypeError):
                    continue
                self.last_event = time.monotonic()
                echo = event.get("echo")
                if isinstance(echo, str) and echo in self.pending:
                    future = self.pending[echo]
                    if not future.done():
                        future.set_result(event)
                    continue
                if str(event.get("self_id", "")) != sid:
                    continue
                if event.get("meta_event_type") == "heartbeat":
                    status = event.get("status", {})
                    self.online = isinstance(status, dict) and status.get("online") is True
                if event.get("meta_event_type") == "lifecycle":
                    self.online = True
                message = parse_event(event) if event.get("post_type") == "message" else parse_notice(event)
                if message and self.accepting:
                    self.online = True
                    logger.info("event_state=received kind=%s event=%s",
                                "notice" if event.get("post_type") == "notice" else "message",
                                pseudonym(message.event_id, self.settings.app_secret)[:12])
                    try:
                        if self.store is not None and hasattr(self.store, "claim") and self._persistable(message):
                            event_key = pseudonym(message.event_id, self.settings.app_secret)
                            conversation_key = pseudonym(message.conversation_id, self.settings.app_secret)
                            if not await self.store.claim(event_key, conversation_key):
                                logger.info("event_state=ignored kind=message reason=persisted_duplicate")
                                continue
                            try:
                                await self.store.persist_inbox(
                                    event_key, message, conversation_key,
                                    source="live", ttl_seconds=getattr(self.settings, "recovery_pending_ttl", 7200),
                                )
                            except Exception:
                                await self.store.mark(event_key, "persistence_failed")
                                logger.warning("event_state=failed reason=inbox_persist")
                                continue
                            message = replace(message, persistence_key=event_key)
                        group_id = getattr(message, "group_id", None)
                        if group_id is not None:
                            limit = getattr(self.settings, "group_queue_size", self.settings.max_pending)
                            if self.group_pending[group_id] >= limit:
                                logger.info("event_state=ignored kind=group reason=group_queue_full")
                                continue
                            self.group_pending[group_id] += 1
                        self.queue.put_nowait(message)
                    except asyncio.QueueFull:
                        if group_id is not None and self.group_pending[group_id] > 0:
                            self.group_pending[group_id] -= 1
                        logger.warning("message_queue_full")
        finally:
            self.ws, self.online = None, False
            for future in self.pending.values():
                if not future.done():
                    future.set_exception(ConnectionError("onebot_disconnected"))
            self.pending.clear()
            logger.info("onebot_disconnected")
        return ws

    def release(self, event):
        group_id = getattr(event, "group_id", None)
        if group_id is not None and self.group_pending[group_id] > 0:
            self.group_pending[group_id] -= 1

    async def action(self, action, params, timeout=15):
        ws = self.ws
        if ws is None or ws.closed:
            raise ConnectionError("onebot_not_connected")
        echo = uuid.uuid4().hex
        future = asyncio.get_running_loop().create_future()
        self.pending[echo] = future
        try:
            await ws.send_json({"action": action, "params": params, "echo": echo})
            result = await asyncio.wait_for(future, timeout)
            if result.get("status") != "ok" or result.get("retcode") != 0:
                raise RuntimeError("onebot_action_failed")
            return result.get("data") or {}
        finally:
            self.pending.pop(echo, None)

    async def send_segments(self, message, segments):
        async with self.send_lock:
            if message.self_id != self.self_id:
                raise ConnectionError("account_changed")
            interval = self.settings.send_interval
            if getattr(message, "group_id", None):
                interval = max(interval, getattr(self.settings, "group_send_interval", interval))
            await asyncio.sleep(max(0, interval - (time.monotonic() - self.last_send)))
            self.last_send = time.monotonic()
            safe = []
            for segment in segments:
                if not isinstance(segment, dict) or segment.get("type") not in ("text", "at", "reply"):
                    continue
                data = segment.get("data")
                if not isinstance(data, dict):
                    continue
                if segment["type"] == "text":
                    text = data.get("text")
                    if isinstance(text, str) and text:
                        # Keep model output a text segment; CQ-looking text is
                        # deliberately not reparsed as protocol markup.
                        safe.append({"type": "text", "data": {"text": text[:4000]}})
                elif segment["type"] == "reply":
                    value = data.get("id")
                    if isinstance(value, (int, str)) and str(value).lstrip("-").isdigit():
                        safe.append({"type": "reply", "data": {"id": int(value)}})
                else:
                    qq = str(data.get("qq", ""))
                    if qq == "all" or qq.isdecimal() and int(qq) > 0:
                        safe.append({"type": "at", "data": {"qq": qq}})
            if not safe:
                raise ValueError("empty_message_segments")
            params = {"message": safe}
            if message.group_id:
                action, params["group_id"] = "send_group_msg", int(message.group_id)
            else:
                action, params["user_id"] = "send_private_msg", int(message.user_id)
            data = await self.action(action, params)
            if "message_id" not in data:
                raise RuntimeError("missing_send_receipt")
            return str(data["message_id"])

    async def send(self, message, text):
        return await self.send_segments(message, [{"type": "text", "data": {"text": text}}])

    async def member_in_group(self, group_id, user_id):
        """Return a conservative membership result for deterministic handoff."""
        data = await self.action("get_group_member_info", {
            "group_id": int(group_id), "user_id": int(user_id), "no_cache": False,
        })
        return isinstance(data, dict) and str(data.get("user_id")) == str(user_id)

    async def close(self):
        self.accepting = False
        if self.ws is not None:
            await self.ws.close(code=1001, message=b"shutdown")
