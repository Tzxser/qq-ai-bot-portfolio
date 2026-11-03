import asyncio
import json
import random

import aiohttp

from .base import ProviderError, ProviderResult


class DeepSeekProvider:
    def __init__(self, settings, session, sleep=asyncio.sleep):
        self.settings, self.session, self.sleep = settings, session, sleep
        self.last_usage = {}
        self.last_attempts = 0
        self.last_result = None

    async def complete(self, messages, *, attempts=None, max_tokens=None):
        return (await self.complete_result(messages, attempts=attempts, max_tokens=max_tokens)).text

    async def complete_result(self, messages, *, attempts=None, max_tokens=None):
        s = self.settings
        self.last_usage = {}
        self.last_attempts = 0
        self.last_result = None
        if not s.api_key:
            raise ProviderError("missing_api_key")
        max_attempts = int(attempts or s.llm_attempts)
        for attempt in range(max_attempts):
            self.last_attempts = attempt + 1
            try:
                async with self.session.post(
                    s.base_url + "/chat/completions",
                    headers={"Authorization": "Bearer " + s.api_key},
                    json={"model": s.model, "messages": messages, "stream": False,
                          "max_tokens": int(max_tokens or 1024), "thinking": {"type": "disabled"}},
                    timeout=aiohttp.ClientTimeout(total=s.llm_timeout, connect=10),
                    allow_redirects=False,
                ) as response:
                    if response.status in (408, 429) or response.status >= 500:
                        if attempt == max_attempts - 1:
                            raise ProviderError("upstream_unavailable")
                    elif response.status != 200:
                        raise ProviderError("upstream_rejected")
                    else:
                        raw = bytearray()
                        async for chunk in response.content.iter_chunked(8192):
                            raw.extend(chunk)
                            if len(raw) > 262144:
                                raise ProviderError("response_too_large")
                        try:
                            body = json.loads(raw)
                            choice = body["choices"][0]
                            content = choice["message"]["content"]
                            if not isinstance(content, str) or not content.strip():
                                raise ValueError
                            finish_reason = choice.get("finish_reason")
                            if finish_reason is not None and not isinstance(finish_reason, str):
                                finish_reason = str(finish_reason)
                            usage = body.get("usage")
                            if isinstance(usage, dict):
                                details = usage.get("completion_tokens_details")
                                reasoning = details.get("reasoning_tokens") if isinstance(details, dict) else None
                                self.last_usage = {
                                    key: int(usage[key]) for key in (
                                        "prompt_tokens", "completion_tokens", "total_tokens",
                                        "prompt_cache_hit_tokens", "prompt_cache_miss_tokens",
                                    ) if isinstance(usage.get(key), (int, float))
                                }
                                if isinstance(reasoning, (int, float)):
                                    self.last_usage["reasoning_tokens"] = int(reasoning)
                            result = ProviderResult(
                                text=content.strip(), usage=dict(self.last_usage),
                                finish_reason=finish_reason, attempts=self.last_attempts,
                            )
                            self.last_result = result
                            return result
                        except (ValueError, KeyError, IndexError, TypeError):
                            raise ProviderError("invalid_response") from None
            except (aiohttp.ClientError, asyncio.TimeoutError):
                if attempt == max_attempts - 1:
                    raise ProviderError("network_timeout") from None
            await self.sleep(min(2 ** attempt, 8) + random.uniform(0, 0.4))
        raise ProviderError("upstream_unavailable")
