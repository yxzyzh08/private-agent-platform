"""Rate limiter — sliding window per-user rate limiting.

Enforces a maximum number of messages per minute per user.
"""

from __future__ import annotations

import time

from core.constants import RATE_LIMIT_PER_MINUTE
from core.errors import RateLimitError


class RateLimiter:
    """Sliding window rate limiter with per-user tracking.

    Each user has an independent window. Timestamps older than
    the window are automatically pruned on each check.
    """

    def __init__(self, limit: int | None = None, window_seconds: int = 60) -> None:
        """Initialize the rate limiter.

        Args:
            limit: Max requests per window. Defaults to RATE_LIMIT_PER_MINUTE from config.
            window_seconds: Window duration in seconds (default: 60).
        """
        self._limit = limit
        self._window = window_seconds
        self._requests: dict[str, list[float]] = {}

    @property
    def limit(self) -> int:
        """Get the current rate limit (lazy resolution from config)."""
        if self._limit is not None:
            return self._limit
        return RATE_LIMIT_PER_MINUTE()

    def check(self, user_id: str) -> None:
        """Check if the user is within the rate limit.

        Args:
            user_id: The user identifier.

        Raises:
            RateLimitError: If the user has exceeded the rate limit.
        """
        now = time.monotonic()
        cutoff = now - self._window

        # Get or create user's request list
        if user_id not in self._requests:
            self._requests[user_id] = []

        # Prune expired timestamps
        self._requests[user_id] = [ts for ts in self._requests[user_id] if ts > cutoff]

        # Check limit
        if len(self._requests[user_id]) >= self.limit:
            raise RateLimitError(
                f"Rate limit exceeded for user '{user_id}': "
                f"{self.limit} requests per {self._window}s"
            )

        # Record this request
        self._requests[user_id].append(now)

    def reset(self, user_id: str | None = None) -> None:
        """Reset rate limit tracking.

        Args:
            user_id: Reset for specific user. If None, resets all users.
        """
        if user_id:
            self._requests.pop(user_id, None)
        else:
            self._requests.clear()
