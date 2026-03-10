"""Persistent store for GitHub Issues awaiting Owner confirmation."""

from __future__ import annotations

import json
import time
from pathlib import Path

from core.logging import get_logger

logger = get_logger(__name__)

# Issue status constants
STATUS_PENDING = "pending_confirmation"
STATUS_APPROVED = "approved"
STATUS_REJECTED = "rejected"
STATUS_TIMEOUT = "timeout"
STATUS_EXECUTING = "executing"
STATUS_COMPLETED = "completed"
STATUS_FAILED = "failed"

# Default confirmation timeout: 24 hours
CONFIRMATION_TIMEOUT_SECONDS = 24 * 60 * 60


class PendingIssueStore:
    """Persists pending issue state to a JSON file.

    Stores issues awaiting Owner confirmation with their analysis results.
    """

    def __init__(self, store_path: str | None = None) -> None:
        self._path = Path(store_path or "data/agents/dev_bot/workspace/pending_issues.json")

    def _ensure_dir(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)

    def load(self) -> dict[str, dict]:
        """Load all pending issues from disk."""
        if not self._path.exists():
            return {}
        try:
            return json.loads(self._path.read_text())
        except (json.JSONDecodeError, OSError):
            logger.warning("Failed to load pending issues from %s", self._path)
            return {}

    def save(self, data: dict[str, dict]) -> None:
        """Save all pending issues to disk."""
        self._ensure_dir()
        self._path.write_text(json.dumps(data, indent=2, default=str))

    def add(self, issue_key: str, issue_data: dict) -> None:
        """Add or update a pending issue."""
        data = self.load()
        data[issue_key] = issue_data
        self.save(data)

    def get(self, issue_key: str) -> dict | None:
        """Get a pending issue by key."""
        return self.load().get(issue_key)

    def remove(self, issue_key: str) -> None:
        """Remove a pending issue."""
        data = self.load()
        data.pop(issue_key, None)
        self.save(data)

    def update_status(self, issue_key: str, status: str) -> None:
        """Update the status of a pending issue."""
        data = self.load()
        if issue_key in data:
            data[issue_key]["status"] = status
            self.save(data)

    def get_timed_out(self, timeout_seconds: int = CONFIRMATION_TIMEOUT_SECONDS) -> list[str]:
        """Get keys of issues that have exceeded the confirmation timeout."""
        data = self.load()
        now = time.time()
        timed_out = []
        for key, info in data.items():
            if info.get("status") == STATUS_PENDING:
                created = info.get("created_at", 0)
                if now - created > timeout_seconds:
                    timed_out.append(key)
        return timed_out
