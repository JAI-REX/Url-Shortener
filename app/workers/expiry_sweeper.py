"""
Run as a periodic job (cron / k8s CronJob / simple sleep loop):
    python -m app.workers.expiry_sweeper

This is a housekeeping pass, NOT the primary expiry enforcement —
url_service.resolve() already checks expires_at on every lookup, so
an expired link returns 410 immediately regardless of whether this
job has run yet. This job's only purpose is to:
  1. Flip is_active=False on expired rows for clean leaderboard/admin
     queries (filtering on is_active is cheaper than a date compare).
  2. Evict any Redis cache entries left over before TTL caught up.
"""
import asyncio
import logging
from datetime import datetime, timezone

from sqlalchemy import select, update

from app.core.database import AsyncSessionLocal
from app.core.redis_client import get_redis
from app.models.models import URL

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("expiry_sweeper")

SWEEP_INTERVAL_SECONDS = 300
BATCH_LIMIT = 500


async def sweep_once():
    redis = get_redis()
    now = datetime.now(timezone.utc)

    async with AsyncSessionLocal() as session:
        expired_rows = (
            await session.execute(
                select(URL.short_code)
                .where(URL.expires_at < now, URL.is_active == True)  # noqa: E712
                .limit(BATCH_LIMIT)
            )
        ).scalars().all()

        if not expired_rows:
            return 0

        await session.execute(
            update(URL).where(URL.short_code.in_(expired_rows)).values(is_active=False)
        )
        await session.commit()

    if expired_rows:
        pipe = redis.pipeline()
        for code in expired_rows:
            pipe.delete(f"url:{code}")
        await pipe.execute()

    return len(expired_rows)


async def main():
    logger.info("Expiry sweeper started, interval=%ds", SWEEP_INTERVAL_SECONDS)
    while True:
        try:
            n = await sweep_once()
            if n:
                logger.info("Deactivated %d expired URLs", n)
        except Exception:
            logger.exception("Sweep error")
        await asyncio.sleep(SWEEP_INTERVAL_SECONDS)


if __name__ == "__main__":
    asyncio.run(main())
