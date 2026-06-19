from pydantic import BaseModel, HttpUrl, Field, field_validator
from datetime import datetime


class ShortenRequest(BaseModel):
    long_url: HttpUrl
    custom_alias: str | None = Field(default=None, min_length=3, max_length=20)
    expiry_days: int | None = Field(default=None, ge=1, le=3650)

    @field_validator("custom_alias")
    @classmethod
    def alias_must_be_alphanumeric(cls, v):
        if v is not None and not v.isalnum():
            raise ValueError("custom_alias must be alphanumeric")
        return v


class ShortenResponse(BaseModel):
    short_code: str
    short_url: str
    long_url: str
    expires_at: datetime | None
    created_at: datetime


class URLMetadataResponse(BaseModel):
    short_code: str
    long_url: str
    created_at: datetime
    expires_at: datetime | None
    is_active: bool
    click_count: int


class StatsResponse(BaseModel):
    short_code: str
    total_clicks: int
    unique_visitors: int
    top_referrers: list[dict]
