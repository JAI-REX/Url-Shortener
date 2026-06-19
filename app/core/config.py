"""
Centralized configuration. All env-driven so the same image runs in
dev/staging/prod with different .env files / k8s secrets.
"""
from pydantic_settings import BaseSettings
from functools import lru_cache


class Settings(BaseSettings):
    # --- App ---
    APP_NAME: str = "url-shortener"
    BASE_URL: str = "http://localhost:8000"
    ENV: str = "development"

    # --- Postgres ---
    # Either set these discrete fields (used by local docker-compose),
    # or set DATABASE_URL_OVERRIDE directly (used by managed platforms
    # like Railway/Render that hand you one connection string).
    POSTGRES_USER: str = "shortener"
    POSTGRES_PASSWORD: str = "shortener_pass"
    POSTGRES_DB: str = "shortener_db"
    POSTGRES_HOST: str = "postgres"
    POSTGRES_PORT: int = 5432
    DATABASE_URL_OVERRIDE: str | None = None

    # --- Redis ---
    REDIS_HOST: str = "redis"
    REDIS_PORT: int = 6379
    REDIS_DB: int = 0
    REDIS_URL_OVERRIDE: str | None = None

    # --- Rate limiting ---
    RATE_LIMIT_REQUESTS: int = 100       # requests
    RATE_LIMIT_WINDOW_SECONDS: int = 60  # per window

    # --- URL behavior ---
    DEFAULT_EXPIRY_DAYS: int = 365
    SHORT_CODE_MIN_LENGTH: int = 6
    CACHE_TTL_SECONDS: int = 3600

    @property
    def DATABASE_URL(self) -> str:
        if self.DATABASE_URL_OVERRIDE:
            # Railway/Render/Heroku-style URLs come as postgres:// or
            # postgresql://; asyncpg needs the postgresql+asyncpg:// scheme.
            url = self.DATABASE_URL_OVERRIDE
            if url.startswith("postgres://"):
                url = url.replace("postgres://", "postgresql+asyncpg://", 1)
            elif url.startswith("postgresql://") and "+asyncpg" not in url:
                url = url.replace("postgresql://", "postgresql+asyncpg://", 1)
            return url
        return (
            f"postgresql+asyncpg://{self.POSTGRES_USER}:{self.POSTGRES_PASSWORD}"
            f"@{self.POSTGRES_HOST}:{self.POSTGRES_PORT}/{self.POSTGRES_DB}"
        )

    @property
    def REDIS_URL(self) -> str:
        if self.REDIS_URL_OVERRIDE:
            return self.REDIS_URL_OVERRIDE
        return f"redis://{self.REDIS_HOST}:{self.REDIS_PORT}/{self.REDIS_DB}"

    class Config:
        env_file = ".env"


@lru_cache
def get_settings() -> Settings:
    return Settings()
