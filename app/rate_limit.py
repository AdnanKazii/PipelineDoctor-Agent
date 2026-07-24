import os
import time
from collections import defaultdict, deque

from fastapi import Request
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

HOUR = 3600
DAY = 86400


class RateLimiter(BaseHTTPMiddleware):
    """A simple in-process per-IP rate limiter for the /diagnose endpoints,
    since every call there spends real Claude tokens (unlike the rest of the
    API, which just reads DuckDB). In-memory only -- fine for a single-instance
    portfolio deployment; a multi-instance deployment would need a shared
    store (e.g. Redis) instead."""

    def __init__(self, app, per_hour: int | None = None, per_day: int | None = None):
        super().__init__(app)
        self.per_hour = per_hour or int(os.environ.get("RATE_LIMIT_PER_HOUR", 10))
        self.per_day = per_day or int(os.environ.get("RATE_LIMIT_PER_DAY", 30))
        self._hits: dict[str, deque] = defaultdict(deque)

    async def dispatch(self, request: Request, call_next):
        if request.url.path.startswith("/diagnose"):
            ip = request.client.host if request.client else "unknown"
            now = time.time()
            hits = self._hits[ip]
            while hits and now - hits[0] > DAY:
                hits.popleft()

            hour_count = sum(1 for t in hits if now - t <= HOUR)
            if hour_count >= self.per_hour or len(hits) >= self.per_day:
                return JSONResponse(
                    status_code=429,
                    content={
                        "detail": f"Rate limit exceeded ({self.per_hour}/hour, {self.per_day}/day per IP). "
                        "Try again later."
                    },
                )
            hits.append(now)

        return await call_next(request)
