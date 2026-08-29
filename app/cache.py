from __future__ import annotations

import threading
import time
from dataclasses import dataclass


@dataclass
class CacheEntry:
    target_url: str
    expires_at: str | None
    disabled: bool
    cached_until: float


class LinkCache:
    """Small read-through cache; intentionally bounded to one application process."""

    def __init__(self, ttl_seconds: int, maximum_entries: int = 10_000):
        self.ttl_seconds = ttl_seconds
        self.maximum_entries = maximum_entries
        self._entries: dict[str, CacheEntry] = {}
        self._lock = threading.Lock()

    def get(self, code: str) -> CacheEntry | None:
        with self._lock:
            entry = self._entries.get(code)
            if entry and entry.cached_until > time.monotonic():
                return entry
            self._entries.pop(code, None)
            return None

    def put(self, code: str, target_url: str, expires_at: str | None, disabled: bool) -> None:
        with self._lock:
            if len(self._entries) >= self.maximum_entries:
                oldest = min(self._entries, key=lambda item: self._entries[item].cached_until)
                self._entries.pop(oldest, None)
            self._entries[code] = CacheEntry(target_url, expires_at, disabled, time.monotonic() + self.ttl_seconds)

    def invalidate(self, code: str) -> None:
        with self._lock:
            self._entries.pop(code, None)
