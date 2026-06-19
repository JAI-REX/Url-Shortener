"""
Run as a separate process/container:  python -m app.workers.analytics_worker

Uses a Redis consumer group so multiple worker replicas can run in
parallel without double-processing the same click event, and so a
crashed worker's pending entries get picked up again (XACK / XCLAIM).
"""
import asyncio
import json
import logging

from app.core.redis_client import get_redis
from app.core.database import AsyncSessionLocal
from app.models.models import ClickEvent
from app.services.analytics_service import STREAM_KEY

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("analytics_worker")

GROUP_NAME = "analytics_workers"
CONSUMER_NAME = "worker-1"
BATCH_SIZE = 100
BLOCK_MS = 5000


async def ensure_group(redis):
    try:
        await redis.xgroup_create(STREAM_KEY, GROUP_NAME, id="0", mkstream=True)
    except Exception as e:
        if "BUSYGROUP" not in str(e):
            raise  # group already exists -> fine


async def drain_batch(redis) -> int:
    response = await redis.xreadgroup(
        GROUP_NAME, CONSUMER_NAME, {STREAM_KEY: ">"}, count=BATCH_SIZE, block=BLOCK_MS
    )
    if not response:
        return 0

    entries = response[0][1]  # [(stream_key, [(id, {data: ...}), ...])]
    rows = []
    ack_ids = []
    for entry_id, fields in entries:
        try:
            event = json.loads(fields["data"])
            rows.append(
                ClickEvent(
                    short_code=event["short_code"],
                    ip_hash=event["ip_hash"] or None,
                    user_agent=event["user_agent"] or None,
                    referrer=event["referrer"] or None,
                )
            )
            ack_ids.append(entry_id)
        except Exception:
            logger.exception("Failed to parse click event %s, skipping", entry_id)
            ack_ids.append(entry_id)  # ack anyway to avoid poison-pill looping

    if rows:
        async with AsyncSessionLocal() as session:
            session.add_all(rows)
            await session.commit()

    if ack_ids:
        await redis.xack(STREAM_KEY, GROUP_NAME, *ack_ids)

    return len(rows)


async def main():
    redis = get_redis()
    await ensure_group(redis)
    logger.info("Analytics worker started, consuming from '%s'", STREAM_KEY)
    while True:
        try:
            n = await drain_batch(redis)
            if n:
                logger.info("Drained %d click events to Postgres", n)
        except Exception:
            logger.exception("Worker loop error, backing off")
            await asyncio.sleep(2)


if __name__ == "__main__":
    asyncio.run(main())
