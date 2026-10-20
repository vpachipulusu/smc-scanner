"""A small in-process sliding-window rate limiter for the expensive API endpoints.

State lives in this process only, like the scan lock and the run guard: run a single worker,
or each worker would allow the full limit on its own. The limit is global per endpoint, not per
client, because the only caller is the Next.js server.
"""

import math
import threading
import time
from collections import deque
from collections.abc import Callable


class RateLimiter:
    """At most ``limit`` accepted hits in any ``window_seconds``; thread-safe."""

    def __init__(
        self,
        limit: int,
        window_seconds: float,
        *,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        if limit < 1:
            raise ValueError("limit must be at least 1")
        if not (math.isfinite(window_seconds) and window_seconds > 0):
            raise ValueError("window_seconds must be a positive, finite number")
        self._limit = limit
        self._window = window_seconds
        self._clock = clock
        self._lock = threading.Lock()
        self._hits: deque[float] = deque()

    def take(self) -> int | None:
        """Count one hit and return None, or return the seconds to wait (at least 1) when full.

        Refused hits are not counted, so hammering a full limiter does not extend the wait.
        """
        with self._lock:
            now = self._clock()
            while self._hits and now - self._hits[0] >= self._window:
                self._hits.popleft()
            if len(self._hits) >= self._limit:
                return max(1, math.ceil(self._window - (now - self._hits[0])))
            self._hits.append(now)
            return None

    def reset(self) -> None:
        with self._lock:
            self._hits.clear()
