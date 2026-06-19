import redis.asyncio as redis
from app.core.config import get_settings

settings = get_settings()

# A single connection pool shared across the app; redis-py handles
# concurrency internally so we don't need per-request connections.
redis_pool = redis.ConnectionPool.from_url(
    settings.REDIS_URL, decode_responses=True, max_connections=50
)


def get_redis() -> redis.Redis:
    return redis.Redis(connection_pool=redis_pool)
