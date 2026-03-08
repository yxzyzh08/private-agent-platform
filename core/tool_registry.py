"""Tool registry — register tools and enforce per-agent access control.

Tools are registered globally. Access is controlled by agent-level
allowed_tools configuration.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from core.errors import PermissionDeniedError

if TYPE_CHECKING:
    from tools.base import BaseTool

logger = logging.getLogger(__name__)


class ToolRegistry:
    """Global tool registry with per-agent permission enforcement."""

    def __init__(self) -> None:
        self._tools: dict[str, BaseTool] = {}
        self._agent_permissions: dict[str, list[str]] = {}

    def register(self, tool: BaseTool) -> None:
        """Register a tool instance.

        Args:
            tool: The tool to register. Must have a unique name.
        """
        if tool.name in self._tools:
            logger.warning("Tool '%s' already registered, overwriting", tool.name)
        self._tools[tool.name] = tool
        logger.info("Registered tool: %s", tool.name)

    def set_agent_permissions(self, agent_id: str, allowed_tools: list[str]) -> None:
        """Set the allowed tools for an agent.

        Args:
            agent_id: The agent identifier.
            allowed_tools: List of tool names the agent can use.
        """
        self._agent_permissions[agent_id] = allowed_tools

    def get_tool(self, name: str, agent_id: str) -> BaseTool:
        """Get a tool by name, enforcing agent permissions.

        Args:
            name: Tool name.
            agent_id: Agent requesting the tool.

        Returns:
            The tool instance.

        Raises:
            PermissionDeniedError: If the agent is not allowed to use this tool.
            KeyError: If the tool is not registered.
        """
        if name not in self._tools:
            raise KeyError(f"Tool not found: {name}")

        allowed = self._agent_permissions.get(agent_id, [])
        if name not in allowed:
            raise PermissionDeniedError(f"Agent '{agent_id}' is not authorized to use tool '{name}'")

        return self._tools[name]

    def list_tools(self, agent_id: str) -> list[BaseTool]:
        """List all tools available to an agent.

        Args:
            agent_id: The agent identifier.

        Returns:
            List of tools the agent is allowed to use.
        """
        allowed = self._agent_permissions.get(agent_id, [])
        return [self._tools[name] for name in allowed if name in self._tools]

    def list_all_tools(self) -> list[BaseTool]:
        """List all registered tools regardless of permissions."""
        return list(self._tools.values())
