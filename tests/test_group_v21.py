import asyncio
import time
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from bot.conversation.service import ConversationService
from bot.gateway.events import parse_event, parse_notice
from bot.group.router import GroupRouter
from bot.group.directory import DepartmentDirectory
from bot.memory.session import SessionPolicy


def group_event(message, **extra):
    value = {
        "post_type": "message", "message_type": "group", "sub_type": "normal",
        "self_id": 10001, "user_id": 20002, "group_id": 30003,
        "message_id": 123, "time": int(time.time()), "message": message,
    }
    value.update(extra)
    return value


def group_settings(settings):
    settings.group_features_enabled = True
    settings.group_enabled = True
    settings.allowed_group_ids = ("30003",)
    settings.ignore_bot_ids = ()
    settings.group_welcome_enabled = True
    settings.association_lead_enabled = True
    settings.association_lead_target_qq = "90009"
    settings.group_send_interval = 0
    settings.handoff_requester_cooldown = 1800
    settings.handoff_group_cooldown = 600
    settings.handoff_global_per_hour = 3
    settings.welcome_window = 0.01
    settings.welcome_stale_seconds = 180
    return settings


def test_parser_distinguishes_top_level_at_reply_and_nested_content():
    event = group_event([
        {"type": "reply", "data": {"id": 777}},
        {"type": "at", "data": {"qq": "10001"}},
        {"type": "at", "data": {"qq": "20003"}},
        {"type": "forward", "data": {"content": [{"type": "at", "data": {"qq": "10001"}}]}},
        {"type": "text", "data": {"text": "题目怎么做"}},
    ])
    message = parse_event(event)
    assert message.mentioned is True
    assert message.at_ids == ("10001", "20003")
    assert message.reply_to == "777"
    assert message.message_id == "123"

    event["message"] = [{"type": "at", "data": {"qq": "all"}},
                         {"type": "text", "data": {"text": "大家好"}}]
    message = parse_event(event)
    assert message.at_all is True
    assert message.mentioned is False


def test_notice_uses_user_id_and_rejects_self():
    notice = parse_notice({"post_type": "notice", "notice_type": "group_increase",
                           "sub_type": "invite", "self_id": 10001,
                           "group_id": 30003, "user_id": 20002,
                           "operator_id": 88888, "time": int(time.time())})
    assert notice.user_id == "20002"
    assert parse_notice({**notice.__dict__, "post_type": "message"}) is None
    assert parse_notice({"post_type": "notice", "notice_type": "group_increase",
                         "sub_type": "approve", "self_id": 10001,
                         "group_id": 30003, "user_id": 10001,
                         "time": int(time.time())}) is None


def test_router_fails_closed_and_handoff_has_priority(settings):
    settings = group_settings(settings)
    router = GroupRouter(settings)
    unauthorized = parse_event(group_event(
        [{"type": "at", "data": {"qq": "10001"}}, {"type": "text", "data": {"text": "你好"}}],
        group_id=99999))
    assert router.route(unauthorized).reason == "group_not_authorized"

    handoff = parse_event(group_event([
        {"type": "at", "data": {"qq": "90009"}},
        {"type": "at", "data": {"qq": "10001"}},
        {"type": "text", "data": {"text": "请负责人看一下报名问题"}},
    ]))
    route = router.route(handoff)
    assert route.kind == "handoff"
    assert router.route(parse_event(group_event(
        [{"type": "text", "data": {"text": "@负责人"}}]))).kind == "ignored"

    informational = parse_event(group_event([
        {"type": "at", "data": {"qq": "90009"}},
        {"type": "text", "data": {"text": "负责人是谁"}},
    ]))
    assert router.route(informational).kind == "ignored"
    negative = parse_event(group_event([
        {"type": "at", "data": {"qq": "90009"}},
        {"type": "text", "data": {"text": "不要提醒负责人"}},
    ]))
    assert router.route(negative).kind == "ignored"
    bare_lead = parse_event(group_event([
        {"type": "at", "data": {"qq": "90009"}},
    ]))
    assert router.route(bare_lead).kind == "handoff_prompt"
    empty_command = parse_event(group_event([
        {"type": "at", "data": {"qq": "10001"}},
        {"type": "text", "data": {"text": "/转负责人"}},
    ]))
    assert router.route(empty_command).kind == "handoff_prompt"
    command_without_bot = parse_event(group_event([
        {"type": "text", "data": {"text": "/转负责人 报名问题"}},
    ]))
    assert router.route(command_without_bot).kind == "ignored"


def test_directory_keeps_six_roles_and_single_lead(settings):
    settings = group_settings(settings)
    directory = DepartmentDirectory(settings)
    assert [role.display_name for role in directory.roles] == [
        "竞赛部", "赛事部", "事务部", "社团团支书", "会长", "协会负责人"
    ]
    assert len(directory.association_lead().contact_ids) == 1


@pytest.mark.parametrize("known_reply,expected", [(False, "ignored"), (True, "handoff")])
def test_handoff_quote_requires_recorded_bot_receipt(settings, known_reply, expected):
    router = GroupRouter(group_settings(settings))
    message = parse_event(group_event([
        {"type": "reply", "data": {"id": "777"}},
        {"type": "text", "data": {"text": "/转负责人 请确认报名安排"}},
    ]))
    assert router.route(message, known_reply=known_reply).kind == expected


@pytest.mark.parametrize("text", [
    "不要请协会负责人回答这个问题", "负责人不用回复报名问题",
    "负责人不在群里", "没必要请负责人处理", "勿提醒负责人",
])
def test_negative_requests_never_add_lead_mention(settings, text):
    router = GroupRouter(group_settings(settings))
    message = parse_event(group_event([
        {"type": "at", "data": {"qq": "90009"}},
        {"type": "at", "data": {"qq": "10001"}},
        {"type": "text", "data": {"text": text}},
    ]))
    assert router.route(message).kind not in ("handoff", "handoff_prompt")


def test_prefixed_negative_handoff_command_never_notifies(settings):
    router = GroupRouter(group_settings(settings))
    message = parse_event(group_event([
        {"type": "at", "data": {"qq": "10001"}},
        {"type": "text", "data": {"text": "/转负责人 不要提醒负责人"}},
    ]))
    assert router.route(message).kind not in ("handoff", "handoff_prompt")


def test_lead_own_message_cannot_remind_self_but_can_ask_bot(settings):
    router = GroupRouter(group_settings(settings))
    message = parse_event(group_event([
        {"type": "at", "data": {"qq": "90009"}},
        {"type": "text", "data": {"text": "请回答这个问题"}},
    ], user_id=90009))
    assert router.route(message).kind == "ignored"
    question = parse_event(group_event([
        {"type": "at", "data": {"qq": "10001"}},
        {"type": "text", "data": {"text": "二分查找为什么需要有序数据"}},
    ], user_id=90009))
    assert router.route(question).kind == "model"


def test_disabled_handoff_command_cannot_bypass_feature_flag(settings):
    settings = group_settings(settings)
    settings.association_lead_enabled = False
    message = parse_event(group_event([
        {"type": "at", "data": {"qq": "10001"}},
        {"type": "text", "data": {"text": "/转负责人 请确认报名安排"}},
    ]))
    assert GroupRouter(settings).route(message).kind not in ("handoff", "handoff_prompt")


@pytest.mark.asyncio
async def test_unverified_reply_never_sends_handoff_or_calls_model(settings):
    settings = group_settings(settings)
    store, limiter, provider, sender = (AsyncMock() for _ in range(4))
    store.is_known_bot_reply.return_value = False
    service = ConversationService(settings, store, limiter, provider, sender)
    message = parse_event(group_event([
        {"type": "reply", "data": {"id": "777"}},
        {"type": "text", "data": {"text": "/转负责人 请确认报名安排"}},
    ]))
    await service.handle(message)
    sender.send_segments.assert_not_awaited()
    provider.complete.assert_not_awaited()
    store.claim.assert_not_awaited()
    await service.close()


def test_session_policy_expires_and_trims():
    policy = SessionPolicy(recent_turns=3, history_chars=10, idle_ttl=5, absolute_ttl=20)
    assert policy.active("x", now=0)
    assert not policy.active("x", now=6)
    assert policy.trim([{"role": "user", "content": "12345"},
                        {"role": "assistant", "content": "67890"},
                        {"role": "user", "content": "abc"},
                        {"role": "assistant", "content": "def"}]) == [
        {"role": "user", "content": "abc"}, {"role": "assistant", "content": "def"}
    ]


@pytest.mark.asyncio
async def test_handoff_is_local_zero_model_and_structured(settings):
    settings = group_settings(settings)
    store = AsyncMock()
    store.claim.return_value = True
    sender = AsyncMock()
    sender.member_in_group.return_value = True
    sender.send_segments.return_value = "888"
    limiter = AsyncMock()
    limiter.allow_key.return_value = True
    limiter.allow_count.return_value = True
    provider = AsyncMock()
    service = ConversationService(settings, store, limiter, provider, sender)
    event = parse_event(group_event([
        {"type": "at", "data": {"qq": "90009"}},
        {"type": "text", "data": {"text": "请协会负责人本人回答这个问题"}},
    ]))
    await service.handle(event)
    provider.complete.assert_not_called()
    sender.send_segments.assert_awaited_once()
    segments = sender.send_segments.call_args.args[1]
    assert any(seg["type"] == "at" and seg["data"]["qq"] == "90009" for seg in segments)
    await service.close()


@pytest.mark.asyncio
async def test_welcome_uses_notice_user_and_no_model(settings):
    settings = group_settings(settings)
    store = AsyncMock()
    store.claim.return_value = True
    limiter = AsyncMock()
    limiter.allow_key.return_value = True
    sender = AsyncMock()
    sender.member_in_group.return_value = True
    sender.send_segments.return_value = "889"
    service = ConversationService(settings, store, limiter, AsyncMock(), sender)
    notice = parse_notice({"post_type": "notice", "notice_type": "group_increase",
                           "sub_type": "approve", "self_id": 10001,
                           "group_id": 30003, "user_id": 20002,
                           "operator_id": 88888, "time": int(time.time())})
    await service.handle(notice)
    await asyncio.sleep(0.03)
    sender.send_segments.assert_awaited_once()
    segments = sender.send_segments.call_args.args[1]
    assert segments[0]["type"] == "at"
    assert segments[0]["data"]["qq"] == "20002"
    await service.close()


@pytest.mark.asyncio
async def test_group_model_requires_known_reply_or_top_level_mention(settings):
    settings = group_settings(settings)
    store = AsyncMock()
    store.claim.return_value = True
    store.history.return_value = []
    store.is_known_bot_reply.return_value = False
    limiter = AsyncMock()
    limiter.allow.return_value = True
    sender = AsyncMock()
    sender.send_segments.return_value = "890"
    provider = AsyncMock()
    provider.complete.return_value = "答案"
    service = ConversationService(settings, store, limiter, provider, sender)
    no_trigger = parse_event(group_event([{"type": "text", "data": {"text": "普通聊天"}}]))
    await service.handle(no_trigger)
    provider.complete.assert_not_called()
    mentioned = parse_event(group_event([
        {"type": "at", "data": {"qq": "10001"}},
        {"type": "text", "data": {"text": "复杂题怎么做"}},
    ]))
    await service.handle(mentioned)
    provider.complete.assert_awaited_once()
    assert sender.send_segments.await_count == 1
    await service.close()
