# URL Shortener at Scale

TinyURL-style URL shortener built with FastAPI, PostgreSQL, Redis, and Docker.

## Features
- **Short code generation**: Base62-encoded Postgres auto-increment IDs (no collision retries)
- **Cache-aside redirects**: Redis-first lookups, Postgres fallback
- **Analytics**: async click tracking via Redis Streams, drained to Postgres by a background worker
- **Rate limiting**: atomic Redis Lua-script-based per-IP limiter with `X-RateLimit-*` headers
- **Expiry**: enforced on every read (410 Gone) + periodic sweeper job for cleanup
- **Custom aliases**, soft-delete (deactivate), and basic per-link stats

## Quick Start

```bash
cp .env.example .env
docker compose up --build
```

This starts: `postgres`, `redis`, `api` (port 8000), `analytics_worker`, `expiry_sweeper`.

API docs: http://localhost:8000/docs

## API Usage

**Shorten a URL**
```bash
curl -X POST http://localhost:8000/api/v1/shorten \
  -H "Content-Type: application/json" \
  -d '{"long_url": "https://example.com/some/very/long/path", "expiry_days": 30}'
```
```json
{
  "short_code": "RWRAMe",
  "short_url": "http://localhost:8000/RWRAMe",
  "long_url": "https://example.com/some/very/long/path",
  "expires_at": "2026-07-19T...",
  "created_at": "2026-06-19T..."
}
```

**Custom alias**
```bash
curl -X POST http://localhost:8000/api/v1/shorten \
  -H "Content-Type: application/json" \
  -d '{"long_url": "https://example.com", "custom_alias": "mylink"}'
```

**Redirect** — just visit `http://localhost:8000/RWRAMe` in a browser, or:
```bash
curl -iL http://localhost:8000/RWRAMe
```

**Get metadata + quick click count**
```bash
curl http://localhost:8000/api/v1/urls/RWRAMe
```

**Get detailed stats (from Postgres, after worker drains the stream)**
```bash
curl http://localhost:8000/api/v1/urls/RWRAMe/stats
```

**Deactivate a link**
```bash
curl -X DELETE http://localhost:8000/api/v1/urls/RWRAMe
```

## Scaling Notes

- **Horizontal API scaling**: `docker compose up --scale api=4` — stateless, so this is safe.
  Put a load balancer (nginx/ALB) in front in production.
- **Redis as the bottleneck-breaker**: redirect reads almost never touch Postgres once
  warm, since hot links stay cached with TTL aligned to their expiry.
- **Analytics decoupling**: the redirect response doesn't wait on a Postgres write —
  it only waits on a Redis `XADD`, which is fast and durable (AOF-backed in this compose
  setup). Multiple `analytics_worker` replicas can run concurrently via the consumer
  group without double-counting.
- **Click event table growth**: in production, partition `click_events` by month
  (e.g. Postgres native partitioning) and roll up old partitions into aggregate
  tables for long-term stats.
- **Rate limiter**: fixed-window via Lua script — O(1), atomic, no race conditions
  between `INCR` and `EXPIRE`. Swap to a sorted-set sliding window if you need
  stricter fairness at window boundaries.

## Local Dev Without Docker

```bash
pip install -r requirements.txt
# point POSTGRES_HOST/REDIS_HOST in .env at localhost if running those separately
uvicorn app.main:app --reload
```

## Project Structure
```
app/
  api/        # routes + pydantic schemas
  core/       # config, db engine, redis client, base62, rate-limit middleware
  models/     # SQLAlchemy ORM models
  services/   # business logic: url_service, analytics_service, rate_limiter
  workers/    # analytics_worker (stream -> Postgres), expiry_sweeper
```
