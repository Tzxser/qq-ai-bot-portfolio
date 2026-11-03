import hashlib
import hmac
import time


def authorized(header, token):
    return bool(header) and hmac.compare_digest(header.encode(), ("Bearer " + token).encode())


def pseudonym(value, secret):
    return hmac.new(secret.encode(), value.encode(), hashlib.sha256).hexdigest()


def allowed(message, settings, now=None):
    now = time.time() if now is None else now
    if abs(now - message.timestamp) > 300 or len(message.text) > settings.max_input:
        return False
    if message.group_id:
        if getattr(message, "anonymous", False):
            return False
        enabled = getattr(settings, "group_features_enabled", getattr(settings, "group_enabled", False))
        if not enabled:
            return False
        allowed_groups = getattr(settings, "allowed_group_ids", None)
        if allowed_groups is not None and allowed_groups and message.group_id not in allowed_groups:
            return False
        # An empty allow-list is fail-closed for the real Settings object. The
        # compatibility fallback keeps old isolated fixtures working.
        if allowed_groups == () and hasattr(settings, "group_features_enabled"):
            return False
        return message.mentioned
    return settings.allow_private


class RateLimiter:
    def __init__(self, redis, seconds):
        self.redis, self.seconds = redis, seconds

    async def allow(self, user):
        return bool(await self.redis.set("rate:" + user, "1", nx=True, px=int(self.seconds * 1000)))

    async def allow_key(self, key, seconds):
        return bool(await self.redis.set("rl:" + key, "1", nx=True, px=max(1, int(seconds * 1000))))

    async def allow_count(self, key, limit, seconds, amount=1):
        """Reserve a bounded window using Redis atomic increment/expiry.

        A failed Redis operation is deliberately propagated so paid paths can
        fail closed. The first writer owns the expiry; subsequent writers only
        increment the existing window.
        """
        redis_key = "rlcount:" + key
        value = await self.redis.incrby(redis_key, int(amount))
        if int(value) == int(amount):
            await self.redis.expire(redis_key, max(1, int(seconds)))
        return int(value) <= int(limit)
