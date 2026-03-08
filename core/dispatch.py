"""Message dispatcher — routes messages from channels to agents.

Routing rules are loaded from config/platform.yaml dispatch.routes section.
"""

from __future__ import annotations

import logging
from typing import Any, Callable

from core.config import get_config

logger = logging.getLogger(__name__)


class Dispatcher:
    """Routes incoming channel messages to the appropriate agent handler."""

    def __init__(self) -> None:
        self._routes: dict[str, str] = {}
        self._agent_handlers: dict[str, Callable] = {}
        self._load_routes()

    def _load_routes(self) -> None:
        """Load routing rules from platform config."""
        config = get_config()
        routes = config.get("dispatch", {}).get("routes", [])
        for route in routes:
            channel = route.get("channel", "")
            agent = route.get("agent", "")
            if channel and agent:
                self._routes[channel] = agent
                logger.debug("Route: %s -> %s", channel, agent)

    def register_agent_handler(self, agent_id: str, handler: Callable) -> None:
        """Register a handler function for an agent.

        Args:
            agent_id: The agent identifier.
            handler: Async callable that processes messages for this agent.
        """
        self._agent_handlers[agent_id] = handler

    async def dispatch(self, channel_id: str, message: Any) -> Any:
        """Route a message from a channel to the appropriate agent.

        Args:
            channel_id: The originating channel identifier.
            message: The message to route.

        Returns:
            The result from the agent handler, or None if no route found.
        """
        agent_id = self._routes.get(channel_id)
        if not agent_id:
            logger.warning("No route found for channel: %s", channel_id)
            return None

        handler = self._agent_handlers.get(agent_id)
        if not handler:
            logger.warning("No handler registered for agent: %s (channel: %s)", agent_id, channel_id)
            return None

        logger.info("Dispatching message from channel '%s' to agent '%s'", channel_id, agent_id)
        return await handler(message)

    def get_route(self, channel_id: str) -> str | None:
        """Get the agent ID for a given channel.

        Args:
            channel_id: The channel identifier.

        Returns:
            Agent ID or None if no route configured.
        """
        return self._routes.get(channel_id)
