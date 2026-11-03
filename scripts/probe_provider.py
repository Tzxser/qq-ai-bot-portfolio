"""One real provider request; prints only status and timing, never credentials/content.

Run from the host with: bash scripts/compose.sh exec -T bot python < scripts/probe_provider.py
This probe does not send QQ messages or modify conversation history.
"""
import asyncio
import json
import time

import aiohttp

from bot.config import Settings
from bot.llm.base import ProviderError
from bot.llm.factory import create_provider
from bot.security.logging import configure


async def main():
    started = time.monotonic()
    statuses = []

    async def request_ended(session, context, params):
        statuses.append(params.response.status)

    try:
        settings = Settings.from_env()
        configure(settings)
        if not settings.api_key:
            raise ProviderError("missing_api_key")
        trace = aiohttp.TraceConfig()
        trace.on_request_end.append(request_ended)
        async with aiohttp.ClientSession(trust_env=False, trace_configs=[trace]) as session:
            provider = create_provider(settings, session)
            answer = await asyncio.wait_for(provider.complete([
                {"role": "user", "content": "Reply with exactly: QQ_BOT_PROVIDER_OK"}
            ]), timeout=170)
        result = {"provider_ok": bool(answer),
                  "expected_reply": answer.strip() == "QQ_BOT_PROVIDER_OK"}
    except ProviderError as exc:
        known = {"missing_api_key", "upstream_unavailable", "upstream_rejected",
                 "network_timeout", "invalid_response", "response_too_large"}
        result = {"provider_ok": False,
                  "reason": str(exc) if str(exc) in known else "provider_error"}
    except Exception as exc:
        result = {"provider_ok": False, "reason": type(exc).__name__}
    if statuses:
        result["http_status"] = statuses[-1]
    result["elapsed_seconds"] = round(time.monotonic() - started, 2)
    print(json.dumps(result, sort_keys=True))
    return 0 if result["provider_ok"] else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
