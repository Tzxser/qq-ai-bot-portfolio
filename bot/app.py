import asyncio
import logging
from contextlib import suppress

import aiohttp
from aiohttp import web
from redis.asyncio import Redis

from bot.config import Settings
from bot.conversation.service import ConversationService
from bot.gateway.onebot import OneBotGateway
from bot.llm.factory import create_provider
from bot.persistence.postgres import PostgresStore
from bot.security.logging import configure
from bot.security.policy import RateLimiter

logger = logging.getLogger(__name__)
RUNTIME = web.AppKey("runtime", dict)


async def health(request):
    runtime = request.app[RUNTIME]
    async def check():
        return await runtime["store"].healthy() and await runtime["redis"].ping()
    try:
        healthy = await asyncio.wait_for(check(), 5)
    except Exception:
        healthy = False
    gateway = runtime["gateway"]
    body = {"healthy": bool(healthy), "llm_key_configured": bool(runtime["settings"].api_key),
            "onebot_connected": gateway.ready, "connections": gateway.connections,
            "queue_size": gateway.queue.qsize(), "metrics": dict(runtime["service"].metrics)}
    if request.path == "/readyz":
        healthy = healthy and body["llm_key_configured"] and body["onebot_connected"]
    return web.json_response(body, status=200 if healthy else 503)


async def worker(gateway, service):
    while True:
        message = await gateway.queue.get()
        try:
            await asyncio.wait_for(service.handle(message), 180)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            # No stack trace or message payloads from external libraries.
            logger.error("message_failed type=%s", type(exc).__name__)
            service.metrics["worker_error"] += 1
        finally:
            gateway.release(message)
            gateway.queue.task_done()


async def maintenance(store, days):
    while True:
        try:
            await store.prune(days)
        except Exception:
            logger.warning("retention_cleanup_failed")
        await asyncio.sleep(3600)


async def recover_after_connect(gateway, service):
    """Wait for a verified OneBot link before replaying local outbox work."""
    for _ in range(18):
        if gateway.ready:
            try:
                count = await service.recover_pending()
                if count:
                    logger.info("recovery_local_completed count=%s", count)
            except Exception:
                logger.warning("recovery_local_failed")
            return
        await asyncio.sleep(5)
    logger.info("recovery_local_deferred reason=onebot_not_ready")


async def resources(app):
    s = app[RUNTIME]["settings"]
    store = await PostgresStore.connect(s)
    redis = Redis(host=s.redis_host, password=s.redis_password, decode_responses=True,
                  socket_timeout=5, socket_connect_timeout=5)
    await redis.ping()
    session = aiohttp.ClientSession(trust_env=False)
    gateway = app[RUNTIME]["gateway"]
    gateway.attach_store(store)
    service = ConversationService(s, store, RateLimiter(redis, s.cooldown), create_provider(s, session), gateway)
    app[RUNTIME].update(store=store, redis=redis, service=service)
    task = asyncio.create_task(worker(gateway, service))
    prune = asyncio.create_task(maintenance(store, s.retention_days))
    recovery = asyncio.create_task(recover_after_connect(gateway, service))
    logger.info("bot_started api_key_configured=%s", bool(s.api_key))
    try:
        yield
    finally:
        gateway.accepting = False
        task.cancel()
        prune.cancel()
        recovery.cancel()
        await asyncio.gather(task, prune, recovery, return_exceptions=True)
        await gateway.close()
        await service.close()
        await session.close()
        await redis.aclose()
        await store.close()
        logger.info("bot_stopped")


async def shutdown(app):
    app[RUNTIME]["gateway"].accepting = False
    # Drain before closing the receive loop so pending action receipts still arrive.
    with suppress(asyncio.TimeoutError):
        await asyncio.wait_for(app[RUNTIME]["gateway"].queue.join(), 190)
    await app[RUNTIME]["gateway"].close()


def create_app(settings=None):
    s = settings or Settings.from_env()
    configure(s)
    app = web.Application(client_max_size=65536)
    gateway = OneBotGateway(s)
    app[RUNTIME] = {"settings": s, "gateway": gateway}
    app.router.add_get("/onebot/v11/ws", gateway.websocket)
    app.router.add_get("/healthz", health)
    app.router.add_get("/readyz", health)
    app.cleanup_ctx.append(resources)
    app.on_shutdown.append(shutdown)
    return app
