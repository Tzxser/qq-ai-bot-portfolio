import asyncio
from datetime import datetime
try:
    from zoneinfo import ZoneInfo
except ImportError:  # pragma: no cover - Python always provides zoneinfo
    ZoneInfo = None


class QuotaService:
    """Redis-backed group admission with process-local concurrency control."""

    def __init__(self, settings, limiter):
        self.settings, self.limiter = settings, limiter
        self.semaphore = asyncio.Semaphore(getattr(settings, "global_llm_concurrency", 2))

    async def reserve(self, user_key, group_id, input_tokens, output_tokens):
        method = getattr(self.limiter, "allow_count", None)
        if method is None:
            return True, "legacy_limiter"
        try:
            now = datetime.now(ZoneInfo("Asia/Shanghai")).strftime("%Y%m%d")
        except Exception:
            # Minimal images may omit tzdata; the host/container is configured
            # to Asia/Shanghai in production, so local time remains the safe
            # fallback for the daily key.
            now = datetime.now().strftime("%Y%m%d")
        attempts = max(1, int(getattr(self.settings, "group_llm_attempts", 1)))
        limits = (
            (f"group:user:min:{user_key}", getattr(self.settings, "group_user_per_minute", 4), 60, attempts),
            (f"group:user:hour:{user_key}", getattr(self.settings, "group_user_per_hour", 30), 3600, attempts),
            (f"group:min:{group_id}", getattr(self.settings, "group_per_minute", 10), 60, attempts),
            (f"group:day:req:{now}", getattr(self.settings, "group_daily_requests", 300), 86400, attempts),
            (f"group:day:input:{now}", getattr(self.settings, "group_daily_input_tokens", 1000000), 86400, 1),
            (f"group:day:output:{now}", getattr(self.settings, "group_daily_generated_tokens", 200000), 86400, 1),
        )
        # A reservation is conservative: if a later counter is unavailable or
        # exhausted, already reserved capacity remains held until its TTL.
        for index, (key, limit, ttl, request_amount) in enumerate(limits):
            amount = max(1, int(input_tokens)) if index == 4 else max(1, int(output_tokens)) if index == 5 else request_amount
            try:
                if not await method(key, limit, ttl, amount):
                    return False, "daily_or_frequency_limit"
            except Exception:
                return False, "quota_store_unavailable"
        return True, "reserved"

    async def acquire(self):
        await self.semaphore.acquire()

    def release(self):
        self.semaphore.release()
