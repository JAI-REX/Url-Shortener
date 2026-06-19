"""
Analytics write path is decoupled from the redirect response:

  redirect request -> XADD to Redis stream (sub-millisecond) -> return 302
                              |
                              v
                  background worker batches & writes to Postgres

This keeps the user-facing redirect latency independent of Postgres
write throughput, which matters a lot once click volume is high.
"""
import hashlib
import json
from datetime import datetime, timezone

from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession
from user_agents import parse as parse_ua

from app.core.redis_client import get_redis
from app.models.models import ClickEvent

STREAM_KEY = "clicks:stream"


def hash_ip(ip: str) -> str:
    # Store a hash, not the raw IP, to limit PII exposure while still
    # allowing rough unique-visitor counting.
    return hashlib.sha256(ip.encode()).hexdigest()[:16]


class AnalyticsService:
    def __init__(self, db: AsyncSession | None = None):
        self.db = db
        self.redis = get_redis()

    async def record_click(
        self,
        short_code: str,
        ip: str | None,
        user_agent: str | None,
        referrer: str | None,
    ) -> None:
        event = {
            "short_code": short_code,
            "clicked_at": datetime.now(timezone.utc).isoformat(),
            "ip_hash": hash_ip(ip) if ip else "",
            "user_agent": user_agent or "",
            "referrer": referrer or "",
        }
        # XADD is O(1) and durable in Redis; the worker reads via consumer group
        await self.redis.xadd(STREAM_KEY, {"data": json.dumps(event)})
        # Also bump a simple per-code counter for instant stats without
        # waiting on the Postgres drain.
        await self.redis.incr(f"clicks:count:{short_code}")

    async def get_quick_count(self, short_code: str) -> int:
        val = await self.redis.get(f"clicks:count:{short_code}")
        return int(val) if val else 0

    async def get_stats(self, short_code: str, days: int = 30) -> dict:
        """Authoritative stats from Postgres (includes drained + historical data)."""
        total = await self.db.scalar(
            select(func.count(ClickEvent.id)).where(ClickEvent.short_code == short_code)
        )
        unique_visitors = await self.db.scalar(
            select(func.count(func.distinct(ClickEvent.ip_hash))).where(
                ClickEvent.short_code == short_code
            )
        )
        top_referrers = await self.db.execute(
            select(ClickEvent.referrer, func.count(ClickEvent.id).label("cnt"))
            .where(ClickEvent.short_code == short_code, ClickEvent.referrer.isnot(None))
            .group_by(ClickEvent.referrer)
            .order_by(func.count(ClickEvent.id).desc())
            .limit(5)
        )
        return {
            "short_code": short_code,
            "total_clicks": total or 0,
            "unique_visitors": unique_visitors or 0,
            "top_referrers": [{"referrer": r, "count": c} for r, c in top_referrers],
        }

    @staticmethod
    def parse_device(user_agent: str | None) -> dict:
        if not user_agent:
            return {"device": "unknown", "browser": "unknown", "os": "unknown"}
        ua = parse_ua(user_agent)
        return {
            "device": "mobile" if ua.is_mobile else "tablet" if ua.is_tablet else "desktop",
            "browser": ua.browser.family,
            "os": ua.os.family,
        }
