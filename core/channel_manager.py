"""Channel manager — lifecycle management for channel adapters.

Handles registration, startup, and shutdown of all channels.
Individual channel failures don't affect others.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from channels.base import BaseChannel

logger = logging.getLogger(__name__)


class ChannelManager:
    """Manages the lifecycle of all registered channel adapters."""

    def __init__(self) -> None:
        self._channels: dict[str, BaseChannel] = {}

    def register(self, channel: BaseChannel) -> None:
        """Register a channel adapter.

        Args:
            channel: The channel to register. Must have a unique id.
        """
        if channel.id in self._channels:
            logger.warning("Channel '%s' already registered, overwriting", channel.id)
        self._channels[channel.id] = channel
        logger.info("Registered channel: %s", channel.id)

    async def start_all(self) -> None:
        """Start all registered channels.

        Individual channel startup failures are logged but don't
        prevent other channels from starting.
        """
        for channel_id, channel in self._channels.items():
            try:
                await channel.start()
                logger.info("Channel '%s' started", channel_id)
            except Exception:
                logger.warning("Failed to start channel '%s'", channel_id, exc_info=True)

    async def stop_all(self) -> None:
        """Stop all registered channels gracefully."""
        for channel_id, channel in self._channels.items():
            try:
                await channel.stop()
                logger.info("Channel '%s' stopped", channel_id)
            except Exception:
                logger.warning("Failed to stop channel '%s'", channel_id, exc_info=True)

    def get_channel(self, channel_id: str) -> BaseChannel | None:
        """Get a channel by its ID."""
        return self._channels.get(channel_id)

    def list_channels(self) -> list[str]:
        """List all registered channel IDs."""
        return list(self._channels.keys())
