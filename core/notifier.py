"""Notification service — ntfy HTTP API integration.

Sends push notifications to the Owner via ntfy.sh (self-hosted or public).
"""

from __future__ import annotations

import os

import httpx

from core.logging import get_logger

logger = get_logger(__name__)

DEFAULT_NTFY_URL = "https://ntfy.sh"


class Notifier:
    """Push notification sender via ntfy HTTP API.

    Configuration:
        NTFY_URL: Base URL of ntfy server (default: https://ntfy.sh)
        NTFY_TOPIC: Topic to publish to (required)
    """

    def __init__(
        self,
        topic: str | None = None,
        base_url: str | None = None,
    ) -> None:
        self._topic = topic or os.environ.get("NTFY_TOPIC", "")
        self._base_url = (base_url or os.environ.get("NTFY_URL", DEFAULT_NTFY_URL)).rstrip("/")

    @property
    def configured(self) -> bool:
        """Whether the notifier has a topic configured."""
        return bool(self._topic)

    async def send(
        self,
        message: str,
        title: str = "",
        priority: str = "default",
        tags: list[str] | None = None,
        click_url: str = "",
    ) -> bool:
        """Send a notification via ntfy.

        Args:
            message: Notification body text.
            title: Optional notification title.
            priority: Priority level (min/low/default/high/urgent).
            tags: Optional list of emoji tags (e.g., ["warning", "robot"]).
            click_url: URL to open when notification is clicked.

        Returns:
            True if sent successfully, False otherwise.
        """
        if not self._topic:
            logger.warning("Notifier: NTFY_TOPIC not configured, skipping notification")
            return False

        url = f"{self._base_url}/{self._topic}"
        headers: dict[str, str] = {}

        if title:
            headers["Title"] = title
        if priority != "default":
            headers["Priority"] = priority
        if tags:
            headers["Tags"] = ",".join(tags)
        if click_url:
            headers["Click"] = click_url

        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.post(url, content=message, headers=headers)
                resp.raise_for_status()
            logger.info("ntfy notification sent: topic=%s, title=%s", self._topic, title)
            return True
        except httpx.HTTPError:
            logger.error("Failed to send ntfy notification", exc_info=True)
            return False
