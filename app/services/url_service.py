from datetime import datetime, timedelta, timezone
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.base62 import encode
from app.core.redis_client import get_redis
from app.core.config import get_settings
from app.models.models import URL

settings = get_settings()


class URLNotFoundError(Exception):
    pass


class URLExpiredError(Exception):
    pass


class URLService:
    def __init__(self, db: AsyncSession):
        self.db = db
        self.redis = get_redis()

    async def create_short_url(
        self,
        long_url: str,
        custom_alias: str | None = None,
        expiry_days: int | None = None,
        created_by: str | None = None,
    ) -> URL:
        expires_at = None
        if expiry_days is not None:
            expires_at = datetime.now(timezone.utc) + timedelta(days=expiry_days)
        elif settings.DEFAULT_EXPIRY_DAYS:
            expires_at = datetime.now(timezone.utc) + timedelta(days=settings.DEFAULT_EXPIRY_DAYS)

        if custom_alias:
            # Custom aliases bypass the id->base62 scheme entirely.
            existing = await self.db.scalar(select(URL).where(URL.short_code == custom_alias))
            if existing:
                raise ValueError(f"Alias '{custom_alias}' is already taken")
            url_row = URL(
                short_code=custom_alias,
                long_url=long_url,
                expires_at=expires_at,
                created_by=created_by,
            )
            self.db.add(url_row)
            await self.db.commit()
            await self.db.refresh(url_row)
        else:
            # Insert first to get the auto-incremented id, then derive
            # the short_code from it and update in the same transaction.
            url_row = URL(
                short_code="",  # placeholder, NOT NULL constraint satisfied below
                long_url=long_url,
                expires_at=expires_at,
                created_by=created_by,
            )
            self.db.add(url_row)
            await self.db.flush()  # assigns url_row.id without committing
            url_row.short_code = encode(url_row.id)
            await self.db.commit()
            await self.db.refresh(url_row)

        await self._cache_url(url_row)
        return url_row

    async def resolve(self, short_code: str) -> str:
        """
        Cache-aside lookup: Redis first, Postgres on miss.
        Raises URLNotFoundError or URLExpiredError so the API layer
        can return the right status code.
        """
        cached = await self.redis.get(f"url:{short_code}")
        if cached is not None:
            if cached == "__EXPIRED__":
                raise URLExpiredError(short_code)
            return cached

        url_row = await self.db.scalar(
            select(URL).where(URL.short_code == short_code, URL.is_active == True)  # noqa: E712
        )
        if url_row is None:
            raise URLNotFoundError(short_code)

        if url_row.expires_at and url_row.expires_at < datetime.now(timezone.utc):
            # Mark expired in cache so we don't keep hitting Postgres for it
            await self.redis.set(f"url:{short_code}", "__EXPIRED__", ex=settings.CACHE_TTL_SECONDS)
            raise URLExpiredError(short_code)

        await self._cache_url(url_row)
        return url_row.long_url

    async def _cache_url(self, url_row: URL) -> None:
        ttl = settings.CACHE_TTL_SECONDS
        if url_row.expires_at:
            seconds_to_expiry = int((url_row.expires_at - datetime.now(timezone.utc)).total_seconds())
            ttl = max(1, min(ttl, seconds_to_expiry))
        await self.redis.set(f"url:{url_row.short_code}", url_row.long_url, ex=ttl)

    async def deactivate(self, short_code: str) -> bool:
        result = await self.db.execute(
            update(URL).where(URL.short_code == short_code).values(is_active=False)
        )
        await self.db.commit()
        await self.redis.delete(f"url:{short_code}")
        return result.rowcount > 0

    async def get_metadata(self, short_code: str) -> URL | None:
        return await self.db.scalar(select(URL).where(URL.short_code == short_code))
