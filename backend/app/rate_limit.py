from collections import defaultdict, deque
from threading import Lock
from time import monotonic


class FixedWindowRateLimiter:
    def __init__(self, max_keys: int = 10_000) -> None:
        self._events: dict[str, deque[float]] = defaultdict(deque)
        self._lock = Lock()
        self._max_keys = max_keys

    def allow(self, key: str, limit: int, window_seconds: int = 60, now: float | None = None) -> bool:
        current = monotonic() if now is None else now
        cutoff = current - window_seconds
        with self._lock:
            if key not in self._events and len(self._events) >= self._max_keys:
                stale_keys = [name for name, values in self._events.items() if not values or values[-1] <= cutoff]
                for stale_key in stale_keys:
                    del self._events[stale_key]
                if len(self._events) >= self._max_keys:
                    oldest_key = min(self._events, key=lambda name: self._events[name][-1])
                    del self._events[oldest_key]
            events = self._events[key]
            while events and events[0] <= cutoff:
                events.popleft()
            if len(events) >= limit:
                return False
            events.append(current)
            return True

    def reset(self) -> None:
        with self._lock:
            self._events.clear()


rate_limiter = FixedWindowRateLimiter()
