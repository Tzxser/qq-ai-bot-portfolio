from unittest.mock import AsyncMock
import pytest
from bot.conversation.service import ConversationService
from bot.gateway.events import parse_event
from bot.gateway.events import message_to_dict
from bot.llm.base import ProviderError


def service(settings):
    store = AsyncMock()
    store.claim.return_value = True
    store.history.return_value = []
    limiter, provider, sender = AsyncMock(), AsyncMock(), AsyncMock()
    limiter.allow.return_value = True
    provider.complete.return_value = "回答"
    sender.send.return_value = "4321"
    return ConversationService(settings, store, limiter, provider, sender)


async def test_private_roundtrip_and_context(settings, event):
    s = service(settings)
    s.store.history.return_value = [{"role": "user", "content": "我叫小白"},
                                    {"role": "assistant", "content": "你好，小白"}]
    await s.handle(parse_event(event))
    assert s.metrics["sent"] == 1
    assert s.provider.complete.call_args.args[0][1]["content"] == "我叫小白"
    s.store.complete.assert_awaited_once()


async def test_duplicate_never_calls_model_or_sends(settings, event):
    s = service(settings)
    s.store.claim.return_value = False
    await s.handle(parse_event(event))
    s.provider.complete.assert_not_called()
    s.sender.send.assert_not_called()


async def test_rate_limit_prevents_call(settings, event):
    s = service(settings)
    s.limiter.allow.return_value = False
    await s.handle(parse_event(event))
    s.provider.complete.assert_not_called()


async def test_ambiguous_send_not_retried(settings, event):
    s = service(settings)
    s.sender.send.side_effect = TimeoutError()
    await s.handle(parse_event(event))
    s.sender.send.assert_awaited_once()
    s.store.complete.assert_not_called()
    assert s.metrics["delivery_uncertain"] == 1


async def test_provider_error_safe_response(settings, event):
    s = service(settings)
    s.provider.complete.side_effect = ProviderError("network_timeout")
    await s.handle(parse_event(event))
    assert s.sender.send.call_args.args[1] == "暂时无法连接 AI 服务，请稍后再试。"
    s.store.complete.assert_not_called()


async def test_recovery_reuses_persisted_answer_without_model(settings, event):
    s = service(settings)
    message = parse_event(event)
    s.store.recoverable_tasks.return_value = [{
        "event_key": "persisted-event", "conversation_key": "persisted-conversation",
        "state": "ready_to_send", "source": "live", "message_json": message_to_dict(message),
        "answer_parts": ["已经生成的答案"],
    }]
    s.sender.send.return_value = "999"
    assert await s.recover_pending() == 1
    s.provider.complete.assert_not_called()
    assert s.sender.send.await_count == 1
    assert s.sender.send.call_args.args[0].event_id == message.event_id
    assert s.sender.send.call_args.args[1] == "已经生成的答案"
    s.store.complete.assert_awaited_once()


async def test_missing_external_key_pauses_messages(settings, event):
    settings.api_key = ""
    s = service(settings)
    await s.handle(parse_event(event))
    s.store.claim.assert_not_called()
    s.sender.send.assert_not_called()


async def test_group_ignored_by_default(settings, event):
    event.update(message_type="group", group_id=30003)
    s = service(settings)
    await s.handle(parse_event(event))
    s.provider.complete.assert_not_called()
