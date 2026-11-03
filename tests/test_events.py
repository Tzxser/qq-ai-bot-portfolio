import pytest
from bot.gateway.events import parse_event
from bot.security.policy import allowed, authorized


def test_private_event(event, settings):
    msg = parse_event(event)
    assert msg.text == "你好"
    assert allowed(msg, settings)
    assert "20002" in msg.conversation_id


@pytest.mark.parametrize("change", [{"post_type": "message_sent"}, {"post_type": "request"},
    {"user_id": 10001}, {"message": []}, {"self_id": None}, {"message_type": "other"}])
def test_ignored_events(event, change):
    event.update(change)
    assert parse_event(event) is None


def test_group_requires_enabled_and_explicit_mention(event, settings):
    event.update(message_type="group", group_id=30003)
    event["message"].insert(0, {"type": "at", "data": {"qq": "10001"}})
    msg = parse_event(event)
    assert not allowed(msg, settings)
    settings.group_enabled = True
    assert allowed(msg, settings)
    event["message"][0]["data"]["qq"] = "all"
    assert not allowed(parse_event(event), settings)


def test_cq_string_and_media(event):
    event["message"] = "[CQ:at,qq=10001]你好&#91;测试&#93;[CQ:image,file=private]"
    msg = parse_event(event)
    assert msg.mentioned and msg.text == "你好[测试]"


def test_old_or_huge_message_ignored(event, settings):
    event["time"] -= 3600
    assert not allowed(parse_event(event), settings)
    event["time"] += 3600
    event["message"] = "x" * 5000
    assert not allowed(parse_event(event), settings)


def test_auth_does_not_allow_bare_token():
    assert authorized("Bearer fixture", "fixture")
    assert not authorized("fixture", "fixture")
    assert not authorized(None, "fixture")
    assert not authorized("Bearer 非ASCII输入", "fixture")
