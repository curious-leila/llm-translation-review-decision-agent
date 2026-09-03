"""Per-IP rate limiting for the public demo review API.

The demo is deployed publicly and every ``POST /api/review`` consumes
upstream model quota. This module adds a small in-memory fixed-window
limiter so a single visitor cannot exhaust the demo budget.

Notes:
- State is in-memory per process; Render runs a single instance, so the
  window is process-wide. Multi-instance deployments would need a shared
  store (e.g. Redis) instead.
- The client key prefers the first ``X-Forwarded-For`` entry because
  Render terminates TLS in front of the app.
"""

from __future__ import annotations

import time
from collections import defaultdict

from fastapi import Request


class RateLimiter:
    """Fixed-window per-key limiter with monotonic timestamps."""

    def __init__(self, limit: int = 60, window_seconds: int = 60) -> None:
        self.limit = limit
        self.window = window_seconds
        self._hits: dict[str, list[float]] = defaultdict(list)

    def client_key(self, request: Request) -> str:
        forwarded = request.headers.get("x-forwarded-for")
        if forwarded:
            return forwarded.split(",")[0].strip()
        if request.client is not None:
            return request.client.host
        return "unknown"

    def allow(self, client_key: str) -> bool:
        now = time.monotonic()
        hits = self._hits[client_key]
        cutoff = now - self.window
        while hits and hits[0] < cutoff:
            hits.pop(0)
        if len(hits) >= self.limit:
            return False
        hits.append(now)
        return True
