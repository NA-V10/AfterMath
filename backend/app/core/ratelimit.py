"""Failed sign-in throttling (docs/SECURITY.md §2, threat: credential guessing).

Keyed by (username, client address), so a guesser at one address cannot lock the account for
everyone else. In-process, like the rest of the single-process API (ADR-0006); a restart clears it.
"""

from __future__ import annotations

import time
from collections import deque
from collections.abc import Callable
from threading import Lock


class LoginThrottle:
    def __init__(
        self,
        max_failures: int = 5,
        window_s: float = 15 * 60,
        clock: Callable[[], float] = time.monotonic,
        max_keys: int = 10_000,
    ) -> None:
        self.max_failures = max_failures
        self.window_s = window_s
        self._clock = clock
        self._max_keys = max_keys
        self._failures: dict[tuple[str, str], deque[float]] = {}
        self._lock = Lock()

    def _recent(self, key: tuple[str, str]) -> deque[float]:
        now = self._clock()
        q = self._failures.get(key, deque())
        while q and now - q[0] > self.window_s:
            q.popleft()
        return q

    def retry_after(self, username: str, client: str) -> int | None:
        """Seconds until another attempt is allowed, or None if it is allowed now."""
        with self._lock:
            q = self._recent((username.lower(), client))
            if len(q) < self.max_failures:
                return None
            return max(1, int(self.window_s - (self._clock() - q[0])) + 1)

    def failed(self, username: str, client: str) -> None:
        with self._lock:
            key = (username.lower(), client)
            q = self._recent(key)
            q.append(self._clock())
            self._failures[key] = q
            if len(self._failures) > self._max_keys:  # bound memory: drop the oldest key
                self._failures.pop(next(iter(self._failures)))

    def succeeded(self, username: str, client: str) -> None:
        with self._lock:
            self._failures.pop((username.lower(), client), None)
