"""In-process event broadcaster for plan execution progress (Phase 1D).

Supports multiple SSE clients subscribing to the same plan_id.
Uses asyncio.Queue fan-out pattern — each subscriber gets its own Queue.

NOT using Redis EventBus because BRPOP is competitive-consumer semantics
(one consumer gets the event, others don't). PlanEventBroker broadcasts
to ALL subscribers, which is the correct behavior for SSE.
"""

from __future__ import annotations

import asyncio
from collections import defaultdict

from core.logging import get_logger

logger = get_logger(__name__)


class PlanEventBroker:
    """In-process event broadcaster for plan execution progress."""

    def __init__(self) -> None:
        self._subscribers: dict[str, list[asyncio.Queue]] = defaultdict(list)

    def subscribe(self, plan_id: str) -> asyncio.Queue:
        """Register a new subscriber Queue for a plan.

        Called by SSE endpoint when a client connects.
        Returns an asyncio.Queue that will receive events.
        """
        queue: asyncio.Queue = asyncio.Queue()
        self._subscribers[plan_id].append(queue)
        logger.debug(
            "SSE subscriber added for plan %s (total: %d)",
            plan_id,
            len(self._subscribers[plan_id]),
        )
        return queue

    def unsubscribe(self, plan_id: str, queue: asyncio.Queue) -> None:
        """Remove a subscriber Queue.

        Called by SSE endpoint when a client disconnects.
        """
        self._subscribers[plan_id] = [
            q for q in self._subscribers[plan_id] if q is not queue
        ]
        if not self._subscribers[plan_id]:
            del self._subscribers[plan_id]
        logger.debug("SSE subscriber removed for plan %s", plan_id)

    async def publish(self, plan_id: str, event: dict) -> None:
        """Broadcast an event to all subscribers of a plan.

        Called by TaskExecutor at key execution points.
        """
        subscribers = self._subscribers.get(plan_id, [])
        for queue in subscribers:
            await queue.put(event)
        if subscribers:
            logger.debug(
                "Published event '%s' to %d subscribers for plan %s",
                event.get("event", "unknown"),
                len(subscribers),
                plan_id,
            )

    def subscriber_count(self, plan_id: str) -> int:
        """Return the number of active subscribers for a plan."""
        return len(self._subscribers.get(plan_id, []))

    def has_subscribers(self, plan_id: str) -> bool:
        """Check if a plan has any active subscribers."""
        return bool(self._subscribers.get(plan_id))

    @property
    def active_plans(self) -> list[str]:
        """Return list of plan_ids with active subscribers."""
        return list(self._subscribers.keys())
