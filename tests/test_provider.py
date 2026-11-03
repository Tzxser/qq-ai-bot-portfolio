import asyncio
import json
from unittest.mock import AsyncMock
import pytest
from bot.llm.base import ProviderError
from bot.llm.deepseek import DeepSeekProvider


class Content:
    def __init__(self, body): self.body = body
    async def iter_chunked(self, size):
        yield self.body


class Response:
    def __init__(self, status=200, body=None):
        self.status = status
        self.content = Content(body if body is not None else json.dumps(
            {"choices": [{"message": {"content": "回答"}}]}).encode())
    async def __aenter__(self): return self
    async def __aexit__(self, *args): pass


class Session:
    def __init__(self, replies): self.replies, self.calls = iter(replies), []
    def post(self, url, **kwargs):
        self.calls.append((url, kwargs))
        response = next(self.replies)
        if isinstance(response, Exception): raise response
        return response


async def test_model_and_key_in_request_only(settings):
    session = Session([Response()])
    provider = DeepSeekProvider(settings, session)
    assert await provider.complete([{"role": "user", "content": "你好"}]) == "回答"
    url, params = session.calls[0]
    assert params["json"]["model"] == "test-model"
    assert settings.api_key not in url
    assert params["allow_redirects"] is False


async def test_usage_is_exposed_without_raw_response(settings):
    body = json.dumps({
        "choices": [{"message": {"content": "回答"}}],
        "usage": {"prompt_tokens": 10, "completion_tokens": 4, "total_tokens": 14,
                   "prompt_cache_hit_tokens": 3, "prompt_cache_miss_tokens": 7,
                   "completion_tokens_details": {"reasoning_tokens": 0}},
    }).encode()
    provider = DeepSeekProvider(settings, Session([Response(body=body)]))
    assert await provider.complete([], attempts=1, max_tokens=80) == "回答"
    assert provider.last_usage["prompt_cache_hit_tokens"] == 3
    assert provider.last_attempts == 1


async def test_provider_result_keeps_finish_reason_and_usage(settings):
    body = json.dumps({
        "choices": [{"message": {"content": "半截"}, "finish_reason": "length"}],
        "usage": {"prompt_tokens": 3, "completion_tokens": 80},
    }).encode()
    provider = DeepSeekProvider(settings, Session([Response(body=body)]))
    result = await provider.complete_result([], attempts=1, max_tokens=80)
    assert result.text == "半截"
    assert result.finish_reason == "length"
    assert result.truncated is True
    assert result.attempts == 1


async def test_exponential_backoff(settings):
    sleep = AsyncMock()
    session = Session([Response(429), Response(503), Response()])
    assert await DeepSeekProvider(settings, session, sleep).complete([]) == "回答"
    delays = [call.args[0] for call in sleep.call_args_list]
    assert 1 <= delays[0] <= 1.4 and 2 <= delays[1] <= 2.4


async def test_group_attempt_override_controls_retry_count(settings):
    settings.llm_attempts = 1
    sleep = AsyncMock()
    session = Session([Response(429), Response()])
    assert await DeepSeekProvider(settings, session, sleep).complete([], attempts=2) == "回答"
    assert len(session.calls) == 2


@pytest.mark.parametrize("status", [400, 401, 403, 404, 302])
async def test_no_retry_for_permanent_errors(settings, status):
    session = Session([Response(status, b"secret body")])
    with pytest.raises(ProviderError, match="upstream_rejected"):
        await DeepSeekProvider(settings, session).complete([])
    assert len(session.calls) == 1


async def test_timeouts_bounded(settings):
    session = Session([asyncio.TimeoutError()] * 3)
    with pytest.raises(ProviderError, match="network_timeout"):
        await DeepSeekProvider(settings, session, AsyncMock()).complete([])
    assert len(session.calls) == 3


@pytest.mark.parametrize("body", [b"bad-json", b'{}', b'{"choices":[]}', b'x' * 262145],
                         ids=["invalid-json", "missing-choices", "empty-choices", "oversize"])
async def test_invalid_response(settings, body):
    with pytest.raises(ProviderError):
        await DeepSeekProvider(settings, Session([Response(body=body)])).complete([])


async def test_missing_key_no_request(settings):
    settings.api_key = ""
    session = Session([])
    with pytest.raises(ProviderError, match="missing_api_key"):
        await DeepSeekProvider(settings, session).complete([])
    assert not session.calls
