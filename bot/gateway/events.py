import re
from dataclasses import asdict, dataclass, field


@dataclass(frozen=True)
class Message:
    event_id: str
    self_id: str
    user_id: str
    group_id: str | None
    text: str
    mentioned: bool
    timestamp: int
    message_type: str = "private"
    sub_type: str = ""
    at_ids: tuple[str, ...] = field(default_factory=tuple)
    reply_to: str | None = None
    at_all: bool = False
    anonymous: bool = False
    sender_role: str | None = None
    message_id: str = ""
    persistence_key: str = ""

    @property
    def conversation_id(self):
        scope = f"group:{self.group_id}:user:{self.user_id}" if self.group_id else f"private:{self.user_id}"
        return f"{self.self_id}:{scope}"

    @property
    def is_group(self):
        return self.group_id is not None


def message_to_dict(message: Message) -> dict:
    """Serialize only the bounded, routing-relevant message fields."""
    data = asdict(message)
    data["at_ids"] = list(message.at_ids)
    return data


def message_from_dict(data: dict) -> Message | None:
    """Rebuild a validated Message from protected persistence data."""
    if not isinstance(data, dict):
        return None
    try:
        values = dict(data)
        values["at_ids"] = tuple(str(item) for item in values.get("at_ids", ()))
        return Message(**values)
    except (TypeError, ValueError):
        return None


@dataclass(frozen=True)
class GroupIncrease:
    event_id: str
    self_id: str
    group_id: str
    user_id: str
    sub_type: str
    timestamp: int


def _decode_cq(value):
    for source, target in (("&#91;", "["), ("&#93;", "]"), ("&#44;", ","), ("&amp;", "&")):
        value = value.replace(source, target)
    return value


def _parse_string_payload(payload, self_id):
    at_ids = []
    at_all = False

    def replace(segment):
        nonlocal at_all
        body = segment.group(1)
        items = body.split(",")
        kind = items[0] if items else ""
        parts = {}
        for item in items[1:]:
            if "=" in item:
                key, value = item.split("=", 1)
                parts[key] = _decode_cq(value)
        if kind == "at":
            qq = str(parts.get("qq", ""))
            if qq == "all":
                at_all = True
            elif qq.isdecimal():
                at_ids.append(qq)
        return ""

    plain = re.sub(r"\[CQ:([^\]]*)\]", replace, payload)
    return _decode_cq(plain), tuple(at_ids), at_all


def parse_event(event):
    if not isinstance(event, dict) or event.get("post_type") != "message":
        return None
    kind = event.get("message_type")
    if kind not in ("private", "group") or event.get("sub_type") == "group" and kind == "private":
        return None
    try:
        self_id, user_id = str(int(event["self_id"])), str(int(event["user_id"]))
        message_id = str(int(event["message_id"]))
        group_id = str(int(event["group_id"])) if kind == "group" else None
        timestamp = int(event["time"])
    except (KeyError, TypeError, ValueError):
        return None
    if user_id == self_id or int(user_id) <= 0 or int(self_id) <= 0:
        return None
    payload, text, at_ids, mentioned, at_all, reply_to = event.get("message"), [], [], False, False, None
    anonymous = isinstance(event.get("anonymous"), dict) or event.get("anonymous") is True
    if kind == "group" and (event.get("sub_type") == "anonymous" or anonymous):
        anonymous = True
    sender = event.get("sender")
    sender_role = sender.get("role") if isinstance(sender, dict) and isinstance(sender.get("role"), str) else None
    if isinstance(payload, str):
        plain, at_ids, at_all = _parse_string_payload(payload, self_id)
        mentioned = self_id in at_ids and not at_all
        text.append(plain)
    elif isinstance(payload, list):
        for segment in payload:
            if not isinstance(segment, dict) or not isinstance(segment.get("data"), dict):
                continue
            data = segment["data"]
            if segment.get("type") == "text" and isinstance(data.get("text"), str):
                text.append(data["text"])
            elif segment.get("type") == "at":
                qq = str(data.get("qq", ""))
                if qq == "all":
                    at_all = True
                elif qq.isdecimal():
                    at_ids.append(qq)
            elif segment.get("type") == "reply":
                value = data.get("id")
                if isinstance(value, (int, str)) and str(value).lstrip("-").isdigit():
                    reply_to = str(value)
    else:
        return None
    content = "".join(text).strip()
    mentioned = self_id in at_ids and not at_all
    if not content and kind == "private" and not reply_to:
        return None
    return Message(f"{self_id}:{kind}:{group_id or user_id}:{message_id}", self_id, user_id,
                   group_id, content, mentioned, timestamp, kind, str(event.get("sub_type", "")),
                   tuple(at_ids), reply_to, at_all, anonymous, sender_role, message_id)


def parse_notice(event):
    """Parse only the group-increase notice used by the local welcome path."""
    if not isinstance(event, dict) or event.get("post_type") != "notice":
        return None
    if event.get("notice_type") != "group_increase":
        return None
    try:
        self_id = str(int(event["self_id"]))
        group_id = str(int(event["group_id"]))
        user_id = str(int(event["user_id"]))
        timestamp = int(event["time"])
    except (KeyError, TypeError, ValueError):
        return None
    if min(int(self_id), int(group_id), int(user_id)) <= 0 or user_id == self_id:
        return None
    subtype = str(event.get("sub_type", ""))
    if subtype not in ("approve", "invite"):
        return None
    return GroupIncrease(f"{self_id}:notice:{group_id}:{user_id}:{timestamp}:{subtype}",
                         self_id, group_id, user_id, subtype, timestamp)
