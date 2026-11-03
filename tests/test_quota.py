from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from bot.group.quota import QuotaService


@pytest.mark.asyncio
async def test_quota_reserves_retry_attempts_and_token_budgets():
    settings = SimpleNamespace(
        group_llm_attempts=2,
        group_user_per_minute=4,
        group_user_per_hour=30,
        group_per_minute=10,
        group_daily_requests=300,
        group_daily_input_tokens=1000000,
        group_daily_generated_tokens=200000,
        global_llm_concurrency=2,
    )
    limiter = SimpleNamespace(allow_count=AsyncMock(return_value=True))
    quota = QuotaService(settings, limiter)
    assert await quota.reserve("user", "group", 123, 800) == (True, "reserved")
    calls = limiter.allow_count.await_args_list
    assert [call.args[3] for call in calls[:4]] == [2, 2, 2, 2]
    assert calls[4].args[3] == 123
    assert calls[5].args[3] == 800
