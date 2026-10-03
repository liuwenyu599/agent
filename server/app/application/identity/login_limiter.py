"""Login brute-force protection for the single-process deployment.

Policy (delivery review P0-2):
- track failures independently by client IP and normalized username;
- 5 failures within 10 minutes locks that key for 15 minutes;
- successful authentication clears both keys;
- state is deliberately process-local because production currently runs one API worker.
"""
from __future__ import annotations

import threading
import time
from collections import defaultdict, deque
from dataclasses import dataclass
from typing import Deque, Dict

from app.core.exceptions import AppError


WINDOW_SECONDS = 10 * 60
MAX_FAILURES = 5
LOCK_SECONDS = 15 * 60


@dataclass
class _Bucket:
    failures: Deque[float]
    locked_until: float = 0.0


class LoginRateLimiter:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._buckets: Dict[str, _Bucket] = defaultdict(lambda: _Bucket(deque()))

    @staticmethod
    def _keys(ip: str, username: str) -> tuple[str, str]:
        ip_key = f"ip:{(ip or 'unknown').strip()}"
        user_key = f"user:{(username or '').strip().lower()}"
        return ip_key, user_key

    @staticmethod
    def _prune(bucket: _Bucket, now: float) -> None:
        cutoff = now - WINDOW_SECONDS
        while bucket.failures and bucket.failures[0] < cutoff:
            bucket.failures.popleft()
        if bucket.locked_until <= now:
            bucket.locked_until = 0.0

    def check(self, ip: str, username: str) -> None:
        """Raise 429 when either the IP or username is currently locked."""
        now = time.monotonic()
        retry_after = 0
        with self._lock:
            for key in self._keys(ip, username):
                bucket = self._buckets[key]
                self._prune(bucket, now)
                if bucket.locked_until > now:
                    retry_after = max(retry_after, int(bucket.locked_until - now) + 1)
        if retry_after:
            raise AppError(429, f"登录尝试过多，请 {retry_after} 秒后再试")

    def record_failure(self, ip: str, username: str) -> None:
        now = time.monotonic()
        with self._lock:
            for key in self._keys(ip, username):
                bucket = self._buckets[key]
                self._prune(bucket, now)
                bucket.failures.append(now)
                if len(bucket.failures) >= MAX_FAILURES:
                    bucket.locked_until = max(bucket.locked_until, now + LOCK_SECONDS)
                    bucket.failures.clear()

    def record_success(self, ip: str, username: str) -> None:
        with self._lock:
            for key in self._keys(ip, username):
                self._buckets.pop(key, None)

    def reset(self) -> None:
        """Test helper."""
        with self._lock:
            self._buckets.clear()


login_rate_limiter = LoginRateLimiter()
