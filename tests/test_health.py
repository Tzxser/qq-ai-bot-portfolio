from unittest.mock import AsyncMock
from types import SimpleNamespace
from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer
from bot.app import RUNTIME, health


async def test_health_and_readiness_are_separate():
    app = web.Application()
    store, redis = AsyncMock(), AsyncMock()
    store.healthy.return_value = redis.ping.return_value = True
    app[RUNTIME] = {"store": store, "redis": redis,
        "settings": SimpleNamespace(api_key=""), "service": SimpleNamespace(metrics={}),
        "gateway": SimpleNamespace(ready=False, connections=0, queue=SimpleNamespace(qsize=lambda: 0))}
    app.router.add_get("/healthz", health)
    app.router.add_get("/readyz", health)
    async with TestClient(TestServer(app)) as client:
        response = await client.get("/healthz")
        assert response.status == 200
        assert not (await response.json())["llm_key_configured"]
        assert (await client.get("/readyz")).status == 503
        app[RUNTIME]["settings"].api_key = "test"
        app[RUNTIME]["gateway"].ready = True
        assert (await client.get("/readyz")).status == 200
        store.healthy.side_effect = ConnectionError()
        assert (await client.get("/healthz")).status == 503
