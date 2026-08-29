from __future__ import annotations

import threading
import time
from collections import Counter
from collections.abc import Iterator
from contextlib import contextmanager


class ApplicationMetrics:
    def __init__(self):
        self._counts: Counter[str] = Counter()
        self._redirect_latency_total = 0.0
        self._lock = threading.Lock()

    def increment(self, name: str) -> None:
        with self._lock:
            self._counts[name] += 1

    @contextmanager
    def redirect_timer(self) -> Iterator[None]:
        started = time.monotonic()
        try:
            yield
        finally:
            with self._lock:
                self._counts["redirect_latency_observations"] += 1
                self._redirect_latency_total += time.monotonic() - started

    def render(self) -> str:
        with self._lock:
            lines = [
                "# TYPE url_shortener_links_created_total counter",
                f"url_shortener_links_created_total {self._counts['links_created']}",
                "# TYPE url_shortener_redirects_total counter",
                f"url_shortener_redirects_total {self._counts['redirects']}",
                "# TYPE url_shortener_redirect_errors_total counter",
                f"url_shortener_redirect_errors_total {self._counts['redirect_errors']}",
                "# TYPE url_shortener_rate_limited_total counter",
                f"url_shortener_rate_limited_total {self._counts['rate_limited']}",
                "# TYPE url_shortener_redirect_latency_seconds summary",
                f"url_shortener_redirect_latency_seconds_count {self._counts['redirect_latency_observations']}",
                f"url_shortener_redirect_latency_seconds_sum {self._redirect_latency_total:.6f}",
            ]
        return "\n".join(lines) + "\n"
