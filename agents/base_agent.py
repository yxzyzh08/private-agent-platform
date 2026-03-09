"""Base agent interface.

All agents must inherit from BaseAgent and implement process_message().
Agent configuration is loaded from config/agents/<name>.yaml.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any

import yaml

from channels.base import Message
from core.agent_runtime import AgentResponse, AgentRuntime
from core.logging import get_logger

logger = get_logger(__name__)


class BaseAgent(ABC):
    """Abstract base class for all platform agents.

    Provides config loading, AgentRuntime integration, and event handling.
    Subclasses implement ``process_message`` with domain-specific logic.
    """

    def __init__(
        self,
        agent_id: str,
        config_path: str | None = None,
        tool_registry: Any = None,
    ) -> None:
        self.agent_id = agent_id
        self.tool_registry = tool_registry
        self.config: dict = {}

        if config_path:
            self.config = self._load_config(config_path)

        self._runtime: AgentRuntime | None = None

    def _load_config(self, config_path: str) -> dict:
        """Load agent config from YAML file."""
        path = Path(config_path)
        if not path.exists():
            logger.warning("Agent config not found: %s", config_path)
            return {}
        with open(path) as f:
            return yaml.safe_load(f) or {}

    @property
    def name(self) -> str:
        return self.config.get("name", self.agent_id)

    @property
    def allowed_tools(self) -> list[str]:
        return self.config.get("tools", {}).get("allowed", [])

    @property
    def system_prompt(self) -> str:
        return self.config.get("persona", "")

    def get_runtime(self) -> AgentRuntime:
        """Get or create the AgentRuntime for this agent."""
        if self._runtime is None:
            model = self.config.get("model")
            self._runtime = AgentRuntime(
                agent_id=self.agent_id,
                model=model,
                system_prompt=self.system_prompt,
                tool_registry=self.tool_registry,
            )
        return self._runtime

    @abstractmethod
    async def process_message(self, message: Message) -> AgentResponse:
        """Process an incoming message and return a response.

        Args:
            message: The incoming channel message.

        Returns:
            AgentResponse with the processing result.
        """

    async def on_event(self, event: Any) -> None:
        """Handle a platform event (override in subclasses that subscribe).

        Args:
            event: A PlatformEvent from the event bus.
        """
