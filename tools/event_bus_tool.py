"""Event bus tool — publish/subscribe via injected EventBus instance.

Wraps EventBus operations as a platform tool. EventBus instance is injected
via constructor (dependency injection), not imported at module level.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from tools.base import BaseTool, ToolResult

if TYPE_CHECKING:
    pass  # EventBus type will be resolved at runtime


class EventBusTool(BaseTool):
    """Publish and subscribe to platform events via EventBus."""

    name = "event_bus"
    description = "Publish or subscribe to platform events"
    input_schema = {
        "type": "object",
        "properties": {
            "operation": {
                "type": "string",
                "enum": ["publish", "subscribe"],
                "description": "The event bus operation",
            },
            "event_type": {
                "type": "string",
                "description": "Event type identifier",
            },
            "payload": {
                "type": "object",
                "description": "Event data payload (for publish)",
            },
        },
        "required": ["operation", "event_type"],
    }

    def __init__(self, event_bus: Any) -> None:
        """Initialize with an EventBus instance (dependency injection).

        Args:
            event_bus: An EventBus instance with publish() and subscribe() methods.
        """
        self._event_bus = event_bus

    async def execute(self, params: dict) -> ToolResult:
        await self.validate_input(params)

        operation = params["operation"]
        event_type = params["event_type"]

        if operation == "publish":
            return await self._publish(event_type, params.get("payload", {}))
        elif operation == "subscribe":
            return await self._subscribe(event_type)
        else:
            return ToolResult(success=False, error=f"Unknown operation: {operation}")

    async def _publish(self, event_type: str, payload: dict) -> ToolResult:
        """Publish an event to the event bus."""
        try:
            from core.event_bus import PlatformEvent

            event = PlatformEvent(
                type=event_type,
                source_agent="tool",
                payload=payload,
            )
            await self._event_bus.publish(event)
            return ToolResult(success=True, data={"event_id": event.event_id, "event_type": event_type})
        except Exception as e:
            return ToolResult(success=False, error=f"Failed to publish event: {e}")

    async def _subscribe(self, event_type: str) -> ToolResult:
        """Register a subscription (returns confirmation, handler must be set separately)."""
        return ToolResult(
            success=True,
            data={
                "event_type": event_type,
                "status": "subscription_registered",
                "note": "Handler must be registered programmatically via EventBus.subscribe()",
            },
        )
