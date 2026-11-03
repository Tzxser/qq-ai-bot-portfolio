import asyncio
import json
from unittest.mock import AsyncMock
import aiohttp
from aiohttp import web
from aiohttp.test_utils import TestServer, TestClient
from bot.gateway.onebot import OneBotGateway
from bot.gateway.events import GroupIncrease, parse_event


async def test_reverse_websocket_auth_action_receipt_and_reconnect(settings, event):
    gateway = OneBotGateway(settings)
    app = web.Application()
    app.router.add_get("/ws", gateway.websocket)
    async with TestServer(app) as server:
        async with aiohttp.ClientSession() as client:
            denied = await client.get(server.make_url("/ws"))
            assert denied.status == 401
            headers = {"Authorization": "Bearer " + settings.onebot_token, "X-Self-ID": "10001"}
            async with client.ws_connect(server.make_url("/ws"), headers=headers) as ws:
                await ws.send_json(event)
                msg = await asyncio.wait_for(gateway.queue.get(), 2)
                assert msg.text == "你好"
                gateway.queue.task_done()
                send = asyncio.create_task(gateway.send(msg, "[CQ:at,qq=all]"))
                action = await ws.receive_json(timeout=2)
                assert action["action"] == "send_private_msg"
                assert action["params"]["message"][0]["type"] == "text"
                await ws.send_json({"status": "ok", "retcode": 0,
                                    "data": {"message_id": 999}, "echo": action["echo"]})
                assert await send == "999"
            # Wait for the server to observe the close, bounded by 1 second.
            for _ in range(100):
                if gateway.ws is None: break
                await asyncio.sleep(.01)
            async with client.ws_connect(server.make_url("/ws"), headers=headers):
                assert gateway.connections == 2


async def test_action_timeout_cleans_pending(settings):
    gateway = OneBotGateway(settings)
    gateway.ws = AsyncMock()
    gateway.ws.closed = False
    try:
        await gateway.action("get_status", {}, timeout=.01)
    except asyncio.TimeoutError:
        pass
    else:
        assert False, "Expected timeout"
    assert not gateway.pending


async def test_structured_sender_keeps_model_text_as_text(settings, event):
    from types import SimpleNamespace
    gateway = OneBotGateway(settings)
    gateway.action = AsyncMock(return_value={"message_id": "991"})
    gateway.self_id = "10001"
    reply = await gateway.send_segments(SimpleNamespace(self_id="10001", group_id=None, user_id="20002"), [
            {"type": "text", "data": {"text": "看起来像 [CQ:at,qq=all] 的普通内容"}},
            {"type": "at", "data": {"qq": "all"}},
        ])
    assert reply == "991"
    params = gateway.action.call_args.args[1]
    assert params["message"][0]["type"] == "text"
    assert params["message"][0]["data"]["text"].startswith("看起来像 [CQ:at")
    assert params["message"][1]["type"] == "at"


async def test_group_queue_is_bounded(settings, event):
    settings.group_queue_size = 1
    gateway = OneBotGateway(settings)
    app = web.Application()
    app.router.add_get("/ws", gateway.websocket)
    group_event = dict(event, message_type="group", group_id=30003,
                       message=[{"type": "at", "data": {"qq": "10001"}},
                                {"type": "text", "data": {"text": "问题"}}])
    async with TestServer(app) as server:
        headers = {"Authorization": "Bearer " + settings.onebot_token, "X-Self-ID": "10001"}
        async with aiohttp.ClientSession() as client:
            async with client.ws_connect(server.make_url("/ws"), headers=headers) as ws:
                await ws.send_json(group_event)
                await ws.send_json(dict(group_event, message_id=124))
                queued = await asyncio.wait_for(gateway.queue.get(), 2)
                assert queued.group_id == "30003"
                assert gateway.queue.qsize() == 0
                gateway.release(queued)
                gateway.queue.task_done()


async def test_live_message_is_persisted_before_queue(settings, event):
    store = AsyncMock()
    store.claim.return_value = True
    gateway = OneBotGateway(settings)
    gateway.attach_store(store)
    app = web.Application()
    app.router.add_get("/ws", gateway.websocket)
    async with TestServer(app) as server:
        headers = {"Authorization": "Bearer " + settings.onebot_token, "X-Self-ID": "10001"}
        async with aiohttp.ClientSession() as client:
            async with client.ws_connect(server.make_url("/ws"), headers=headers) as ws:
                await ws.send_json(event)
                message = await asyncio.wait_for(gateway.queue.get(), 2)
                assert message.persistence_key
                store.persist_inbox.assert_awaited_once()
                gateway.queue.task_done()


async def test_group_increase_notice_does_not_disconnect_gateway(settings):
    gateway = OneBotGateway(settings)
    app = web.Application()
    app.router.add_get("/ws", gateway.websocket)
    notice = {
        "post_type": "notice",
        "notice_type": "group_increase",
        "sub_type": "approve",
        "self_id": 10001,
        "group_id": 30003,
        "user_id": 20002,
        "time": 1700000000,
    }
    async with TestServer(app) as server:
        headers = {"Authorization": "Bearer " + settings.onebot_token, "X-Self-ID": "10001"}
        async with aiohttp.ClientSession() as client:
            async with client.ws_connect(server.make_url("/ws"), headers=headers) as ws:
                await ws.send_json(notice)
                queued = await asyncio.wait_for(gateway.queue.get(), 2)
                assert isinstance(queued, GroupIncrease)
                assert gateway.ws is not None and not gateway.ws.closed
                gateway.release(queued)
                gateway.queue.task_done()
