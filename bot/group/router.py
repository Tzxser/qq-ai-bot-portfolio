import re
import time
from dataclasses import dataclass

from .directory import DepartmentDirectory


@dataclass(frozen=True)
class Route:
    kind: str
    reason: str = ""
    text: str = ""


class GroupRouter:
    """Pure local decision layer; it never calls an LLM."""

    def __init__(self, settings):
        self.settings = settings
        self.directory = DepartmentDirectory(settings)

    def authorized(self, message):
        if not getattr(message, "group_id", None):
            return False
        if getattr(message, "anonymous", False):
            return False
        enabled = getattr(self.settings, "group_features_enabled",
                          getattr(self.settings, "group_enabled", False))
        allowed = getattr(self.settings, "allowed_group_ids", None)
        if not enabled:
            return False
        if allowed is not None:
            return message.group_id in allowed
        # Compatibility is only for old test fixtures; production Settings
        # always exposes an explicit tuple and therefore fails closed.
        return True

    @staticmethod
    def _substantive(text):
        text = re.sub(r"\s+", "", text or "")
        return len(text) >= 2 and not re.fullmatch(r"[?？！!。.,，、~～]+", text)

    def _handoff_command(self, text):
        text = (text or "").strip()
        if re.search(r"(?:不要|别|不必|无需|不用|不需要|别再|不要再)", text):
            return None
        prefix = "/转负责人"
        if text.startswith(prefix):
            return text[len(prefix):].strip()
        if re.search(r"(?:请|希望|麻烦).{0,8}协会负责人(?:本人)?(?:回答|回复|答复|处理)", text):
            return text
        return None

    @staticmethod
    def _lead_request_is_explicit(text):
        normalized = re.sub(r"\s+", "", text or "")
        if not normalized:
            return False
        if re.search(r"(?:不要|别|不必|无需|不用|不需要|别再|不要再|不(?:要)?回复|不(?:要)?答复|不(?:要)?处理|不在群|没必要|勿)", normalized):
            return False
        if normalized in {"负责人是谁", "协会负责人是谁", "负责人是什么", "协会负责人是什么",
                          "负责人有哪些职责", "协会负责人有哪些职责", "负责人职责", "协会负责人职责"}:
            return False
        if re.search(r"(?:请|麻烦|希望|能否|可以请|帮忙|转给|让).{0,10}(?:协会负责人|负责人)", normalized):
            return True
        if re.search(r"(?:协会负责人|负责人).{0,10}(?:本人|亲自).{0,6}(?:回答|回复|答复|处理|看看|确认)", normalized):
            return True
        # A real top-level mention with a substantive question is itself an
        # explicit request, except for role-information and greetings.
        if normalized in {"你好", "您好", "嗨", "谢谢", "感谢", "负责人", "协会负责人"}:
            return False
        return len(normalized) >= 3 and not re.fullmatch(r"[?？！!。.,，、~～]+", normalized)

    def _local_answer(self, text):
        normalized = re.sub(r"\s+", "", text or "").lower()
        if normalized in {"你好", "嗨", "hello", "hi", "谢谢", "感谢", "收到"}:
            return "你好，有算法、代码或学习路线问题，可以 @我具体描述。"
        if any(token in normalized for token in ("怎么开始", "零基础", "入门", "学算法")):
            return "可以从熟悉一门语言、基础语法和简单题开始；遇到具体题目时，带上题意、约束和尝试过程，我再帮你拆解。"
        if any(token in normalized for token in ("竞赛部", "赛事部", "事务部", "团支书", "会长", "协会负责人", "部门")):
            return self.directory.navigation()
        if normalized.startswith("/我的记忆"):
            return "当前默认不启用长期个人记忆；本群只保留短期会话以便连续追问。"
        if normalized.startswith("/忘记我"):
            return "已按本地规则清理当前短期会话；长期个人记忆默认未开启。"
        return None

    def route(self, message, known_reply=False, recovery=False):
        if not self.authorized(message):
            return Route("ignored", "group_not_authorized")
        if not recovery and abs(time.time() - message.timestamp) > 300:
            return Route("ignored", "stale_event")
        if len(message.text) > getattr(self.settings, "max_input", 4000):
            return Route("ignored", "input_too_long")
        if getattr(message, "at_all", False):
            return Route("ignored", "at_all")
        ignored_bots = set(getattr(self.settings, "ignore_bot_ids", ()) or ())
        if message.user_id in ignored_bots:
            return Route("ignored", "ignored_bot")

        target = str(getattr(self.settings, "association_lead_target_qq", "") or "")
        lead_enabled = bool(getattr(self.settings, "association_lead_enabled", False)
                            and target and message.user_id != target)
        lead_mentioned = lead_enabled and target in tuple(getattr(message, "at_ids", ()) or ())
        command_text = self._handoff_command(message.text)
        command_present = command_text is not None
        if recovery and (lead_mentioned or command_present or (message.text or "").lstrip().startswith("/")):
            return Route("ignored", "recovery_action_suppressed")
        if lead_mentioned and not self._substantive(message.text):
            return Route("handoff_prompt", "handoff_missing_question",
                         "请补充希望协会负责人本人答复的问题。")
        if lead_mentioned and self._lead_request_is_explicit(message.text):
            question = command_text or message.text
            if not self._substantive(question):
                return Route("handoff_prompt", "handoff_missing_question",
                             "请补充希望协会负责人本人答复的问题。")
            return Route("handoff", "explicit_lead_request", question)
        if lead_mentioned and re.search(r"(?:不要|别|不必|无需|不用|别再|不要再)", re.sub(r"\s+", "", message.text or "")):
            # Do not let a negative request add a reminder; the normal bot
            # route may still answer if the bot itself was mentioned.
            pass
        # Commands and high-precision prose require @bot or a known bot reply.
        if lead_enabled and command_present and (message.mentioned or known_reply):
            question = command_text or ""
            if not self._substantive(question):
                return Route("handoff_prompt", "handoff_missing_question",
                             "请补充希望协会负责人本人答复的问题。")
            return Route("handoff", "explicit_lead_request", question)

        # A reply is valid only when the persistence layer has recorded the
        # bot message ID. Quoted/forwarded text alone never enables this path.
        if message.reply_to and not known_reply:
            return Route("ignored", "unknown_bot_reply")
        command = re.sub(r"\s+", "", message.text or "")
        if (message.mentioned or message.reply_to) and command.startswith("/新话题"):
            return Route("clear_session", "new_topic", "已清理当前话题，可以开始新的问题。")
        if (message.mentioned or message.reply_to) and command.startswith("/忘记我"):
            return Route("clear_session", "forget_memory", "已按本地规则清理当前短期会话；长期个人记忆默认未开启。")
        local = self._local_answer(message.text)
        if local is not None and (message.mentioned or message.reply_to):
            return Route("local", "deterministic_faq", local)
        if message.mentioned and not message.text:
            return Route("local", "bare_mention",
                         "你好，请把想了解的算法、代码或社团事项写在 @我 后面。")
        if message.mentioned or message.reply_to:
            return Route("model", "mention_or_known_reply")
        return Route("ignored", "no_bot_trigger")
