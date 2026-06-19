from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import RedirectResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.config import get_settings
from app.services.url_service import URLService, URLNotFoundError, URLExpiredError
from app.services.analytics_service import AnalyticsService
from app.api.schemas import (
    ShortenRequest,
    ShortenResponse,
    URLMetadataResponse,
    StatsResponse,
)

router = APIRouter()
settings = get_settings()


@router.post("/api/v1/shorten", response_model=ShortenResponse, status_code=201)
async def shorten_url(payload: ShortenRequest, db: AsyncSession = Depends(get_db)):
    service = URLService(db)
    try:
        url_row = await service.create_short_url(
            long_url=str(payload.long_url),
            custom_alias=payload.custom_alias,
            expiry_days=payload.expiry_days,
        )
    except ValueError as e:
        raise HTTPException(status_code=409, detail=str(e))

    return ShortenResponse(
        short_code=url_row.short_code,
        short_url=f"{settings.BASE_URL}/{url_row.short_code}",
        long_url=url_row.long_url,
        expires_at=url_row.expires_at,
        created_at=url_row.created_at,
    )


@router.get("/api/v1/urls/{short_code}", response_model=URLMetadataResponse)
async def get_url_metadata(short_code: str, db: AsyncSession = Depends(get_db)):
    service = URLService(db)
    url_row = await service.get_metadata(short_code)
    if not url_row:
        raise HTTPException(status_code=404, detail="Short URL not found")

    analytics = AnalyticsService()
    click_count = await analytics.get_quick_count(short_code)

    return URLMetadataResponse(
        short_code=url_row.short_code,
        long_url=url_row.long_url,
        created_at=url_row.created_at,
        expires_at=url_row.expires_at,
        is_active=url_row.is_active,
        click_count=click_count,
    )


@router.get("/api/v1/urls/{short_code}/stats", response_model=StatsResponse)
async def get_url_stats(short_code: str, db: AsyncSession = Depends(get_db)):
    service = URLService(db)
    url_row = await service.get_metadata(short_code)
    if not url_row:
        raise HTTPException(status_code=404, detail="Short URL not found")

    analytics = AnalyticsService(db)
    stats = await analytics.get_stats(short_code)
    return StatsResponse(**stats)


@router.delete("/api/v1/urls/{short_code}", status_code=204)
async def deactivate_url(short_code: str, db: AsyncSession = Depends(get_db)):
    service = URLService(db)
    deleted = await service.deactivate(short_code)
    if not deleted:
        raise HTTPException(status_code=404, detail="Short URL not found")


# IMPORTANT: this catch-all must stay registered LAST. FastAPI matches
# routes in registration order, and "/{short_code}" matches any single
# path segment -- including literal segments like "api" -- so anything
# more specific (the /api/v1/... routes above) has to come first or
# this route will shadow them.
@router.get("/{short_code}")
async def redirect_to_long_url(
    short_code: str, request: Request, db: AsyncSession = Depends(get_db)
):
    service = URLService(db)
    try:
        long_url = await service.resolve(short_code)
    except URLNotFoundError:
        raise HTTPException(status_code=404, detail="Short URL not found")
    except URLExpiredError:
        raise HTTPException(status_code=410, detail="This short URL has expired")

    # Fire-and-forget analytics write; doesn't block the redirect response.
    analytics = AnalyticsService()
    client_ip = request.headers.get("x-forwarded-for", "").split(",")[0].strip() or (
        request.client.host if request.client else None
    )
    await analytics.record_click(
        short_code=short_code,
        ip=client_ip,
        user_agent=request.headers.get("user-agent"),
        referrer=request.headers.get("referer"),
    )

    return RedirectResponse(url=long_url, status_code=302)
