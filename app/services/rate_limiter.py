"""
Sliding-window-ish rate limiter using Redis INCR + EXPIRE.

We use the fixed-window-with-Lua approach: simple, O(1) per request,
and atomic (no race between INCR and EXPIRE under concurrent requests).
For stricter sliding-window guarantees you'd swap this for a sorted-set
timestamp approach, at the cost of O(log n) and more memory per key.
For a public URL shortener, fixed-window is the right trade-off.
"""
from app.core.redis_client import get_redis
from app.core.config import get_settings

settings = get_settings()

# KEYS[1] = rate limit key, ARGV[1] = limit, ARGV[2] = window seconds
_RATE_LIMIT_LUA = """
local current = redis.call('INCR', KEYS[1])
if current == 1 then
    redis.call('EXPIRE', KEYS[1], ARGV[2])
end
if current > tonumber(ARGV[1]) then
    return {0, current}
end
return {1, current}
"""


class RateLimiter:
    def __init__(self):
        self.redis = get_redis()
        self.script = self.redis.register_script(_RATE_LIMIT_LUA)

    async def is_allowed(
        self,
        identifier: str,
        limit: int | None = None,
        window: int | None = None,
    ) -> tuple[bool, int, int]:
        """
        Returns (allowed, current_count, limit).
        `identifier` is typically client IP or API key.
        """
        limit = limit or settings.RATE_LIMIT_REQUESTS
        window = window or settings.RATE_LIMIT_WINDOW_SECONDS
        key = f"ratelimit:{identifier}"

        result = await self.script(keys=[key], args=[limit, window])
        allowed, current = result[0], result[1]
        return bool(allowed), int(current), limit


_rate_limiter: RateLimiter | None = None


def get_rate_limiter() -> RateLimiter:
    global _rate_limiter
    if _rate_limiter is None:
        _rate_limiter = RateLimiter()
    return _rate_limiter
