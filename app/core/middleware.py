from fastapi import Request
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware
from app.services.rate_limiter import get_rate_limiter


class RateLimitMiddleware(BaseHTTPMiddleware):
    """
    Applies a per-IP rate limit to all routes except health checks.
    Adds standard X-RateLimit-* headers so well-behaved clients can
    back off before hitting 429s.
    """

    EXEMPT_PATHS = {"/health", "/docs", "/openapi.json", "/redoc", "/", "/favicon.ico"}

    async def dispatch(self, request: Request, call_next):
        if request.url.path in self.EXEMPT_PATHS or request.url.path.startswith("/static/"):
            return await call_next(request)

        client_ip = request.client.host if request.client else "unknown"
        # Respect X-Forwarded-For when behind a load balancer / reverse proxy
        forwarded = request.headers.get("x-forwarded-for")
        if forwarded:
            client_ip = forwarded.split(",")[0].strip()

        limiter = get_rate_limiter()
        allowed, current, limit = await limiter.is_allowed(client_ip)

        if not allowed:
            return JSONResponse(
                status_code=429,
                content={"detail": "Rate limit exceeded. Try again later."},
                headers={
                    "X-RateLimit-Limit": str(limit),
                    "X-RateLimit-Remaining": "0",
                    "Retry-After": "60",
                },
            )

        response = await call_next(request)
        response.headers["X-RateLimit-Limit"] = str(limit)
        response.headers["X-RateLimit-Remaining"] = str(max(0, limit - current))
        return response
