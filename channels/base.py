"""Base channel interface.

All channel adapters must inherit from BaseChannel and implement
start(), stop(), and send().
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Callable

logger = logging.getLogger(__name__)


@dataclass
class Message:
    """Platform-internal message structure."""

    text: str
    channel_id: str = ""
    user_id: str = ""
    message_id: str = ""
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    metadata: dict = field(default_factory=dict)


class BaseChannel(ABC):
    """Abstract base class for all channel adapters.

    Subclasses must implement start(), stop(), and send().
    """

    id: str = ""
    on_message: Callable | None = None
    dm_policy: str = "pairing"
    allowed_users: list[str] = []

    @abstractmethod
    async def start(self) -> None:
        """Start listening for incoming messages."""

    @abstractmethod
    async def stop(self) -> None:
        """Gracefully stop the channel."""

    @abstractmethod
    async def send(self, recipient: str, message: Message) -> None:
        """Send a message to a recipient.

        Args:
            recipient: Target user/channel identifier.
            message: The message to send.
        """

    async def verify_user(self, user_id: str) -> bool:
        """Verify if a user is allowed to interact.

        Default implementation checks against allowed_users whitelist.
        If allowed_users is empty, all users are allowed (open policy).

        Args:
            user_id: The user identifier to verify.

        Returns:
            True if the user is allowed.
        """
        if not self.allowed_users:
            return True
        allowed = user_id in self.allowed_users
        if not allowed:
            logger.warning("User %s denied access to channel %s", user_id, self.id)
        return allowed
