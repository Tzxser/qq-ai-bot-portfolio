import os
import uuid
import pytest
from redis.asyncio import Redis
from bot.config import Settings
from bot.persistence.postgres import PostgresStore
from bot.security.policy import RateLimiter
from bot.gateway.events import parse_event

pytestmark = pytest.mark.integration


async def test_real_postgres_dedup_context_isolation_and_redis():
    if os.environ.get("RUN_DB_TESTS") != "1":
        pytest.skip("requires isolated test environment with PostgreSQL and Redis")
    s = Settings.from_env()
    store = await PostgresStore.connect(s)
    redis = Redis(host=s.redis_host, password=s.redis_password, decode_responses=True)
    prefix = "test:" + uuid.uuid4().hex
    try:
        assert await store.healthy()
        assert await store.claim(prefix, prefix)
        assert not await store.claim(prefix, prefix)
        await store.complete(prefix, prefix, "hello", "world", "1", 8)
        assert len(await store.history(prefix, 8)) == 2
        assert await store.history(prefix + ":other", 8) == []
        message = parse_event({"post_type": "message", "message_type": "private",
                               "sub_type": "friend", "self_id": 10001, "user_id": 20002,
                               "message_id": 991, "time": 1700000000,
                               "message": [{"type": "text", "data": {"text": "待答"}}]})
        await store.persist_inbox(prefix, message, prefix, ttl_seconds=7200)
        await store.save_answer(prefix, message, "答案", ["答案"],
                                {"usage": {"prompt_tokens": 2}, "finish_reason": "stop"})
        pending = await store.recoverable_tasks()
        assert pending and pending[0]["answer_parts"] == ["答案"]
        assert await store.acquire_recovery_lease(prefix, "worker-1", 60)
        assert not await store.acquire_recovery_lease(prefix, "worker-2", 60)
        await store.release_recovery_lease(prefix, "worker-1")
        await store.mark_outbox_sending(prefix + ":0", "attempt-1")
        await store.mark_outbox_sent(prefix + ":0", "2")
        limiter = RateLimiter(redis, 1)
        assert await limiter.allow(prefix)
        assert not await limiter.allow(prefix)
        # Reconnect to prove persisted context rather than process memory.
        await store.close()
        store = await PostgresStore.connect(s)
        assert (await store.history(prefix, 8))[1]["content"] == "world"
    finally:
        await store.pool.execute("DELETE FROM turns WHERE event_key=$1", prefix)
        await store.pool.execute("DELETE FROM events WHERE event_key=$1", prefix)
        await redis.delete("rate:" + prefix)
        await redis.aclose()
        await store.close()
