from __future__ import annotations

import threading
import time
from collections import defaultdict, deque


class SlidingWindowRateLimiter:
    """Process-local abuse guard; use a shared store when horizontally scaling."""

    def __init__(self, requests_per_minute: int):
        self.limit = requests_per_minute
        self._events: dict[str, deque[float]] = defaultdict(deque)
        self._lock = threading.Lock()

    def allow(self, key: str) -> bool:
        current = time.monotonic()
        cutoff = current - 60
        with self._lock:
            for stale_key in list(self._events):
                stale_events = self._events[stale_key]
                while stale_events and stale_events[0] <= cutoff:
                    stale_events.popleft()
                if not stale_events:
                    del self._events[stale_key]
            events = self._events[key]
            while events and events[0] <= cutoff:
                events.popleft()
            if len(events) >= self.limit:
                return False
            events.append(current)
            return True
