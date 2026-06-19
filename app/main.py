from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from contextlib import asynccontextmanager
import os

from app.core.config import get_settings
from app.core.middleware import RateLimitMiddleware
from app.core.database import engine
from app.models.models import Base
from app.api.routes import router

settings = get_settings()
STATIC_DIR = os.path.join(os.path.dirname(__file__), "static")


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Auto-create tables on startup for local/dev convenience.
    # In production, use Alembic migrations instead (see /alembic).
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield


app = FastAPI(
    title="URL Shortener at Scale",
    description="TinyURL-style shortener with analytics, rate limiting, and expiry",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(RateLimitMiddleware)


@app.get("/health")
async def health_check():
    return {"status": "ok"}


@app.get("/")
async def serve_frontend():
    return FileResponse(os.path.join(STATIC_DIR, "index.html"))


# Mounted under /static so it never collides with the /{short_code}
# catch-all in routes.py -- a real short code would have to literally
# be "static" to clash, which create_short_url never generates.
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

app.include_router(router)
