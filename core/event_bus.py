"""Event bus — Redis-backed publish/subscribe for platform events.

Uses Redis Lists (LPUSH/BRPOP) for persistent event delivery.
Events survive process restarts as they're stored in Redis until consumed.
"""

from __future__ import annotations

import asyncio
import json
import uuid
from collections import defaultdict
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Callable

import redis.asyncio as aioredis

from core.logging import get_logger

logger = get_logger(__name__)

_QUEUE_PREFIX = "platform:events:"


@dataclass
class PlatformEvent:
    """Platform event data structure for inter-agent communication."""

    type: str
    source_agent: str
    payload: dict
    event_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    correlation_id: str = ""

    def to_json(self) -> str:
        """Serialize event to JSON string."""
        data = asdict(self)
        data["timestamp"] = self.timestamp.isoformat()
        return json.dumps(data)

    @classmethod
    def from_json(cls, raw: str) -> PlatformEvent:
        """Deserialize event from JSON string."""
        data = json.loads(raw)
        data["timestamp"] = datetime.fromisoformat(data["timestamp"])
        return cls(**data)


class EventBus:
    """Redis-backed event bus using Lists (LPUSH/BRPOP).

    Events are pushed to per-type Redis lists. Subscriber tasks
    continuously BRPOP from their subscribed lists and invoke handlers.
    """

    def __init__(self, redis_url: str = "redis://localhost:6379/0") -> None:
        self._redis_url = redis_url
        self._redis: aioredis.Redis | None = None
        self._handlers: dict[str, list[Callable]] = defaultdict(list)
        self._consumer_tasks: list[asyncio.Task] = []
        self._running = False

    async def start(self) -> None:
        """Connect to Redis and start consumer loops for all subscribed event types."""
        self._redis = aioredis.from_url(self._redis_url, decode_responses=True)
        self._running = True

        # Start a consumer task for each subscribed event type
        for event_type in self._handlers:
            task = asyncio.create_task(self._consume_loop(event_type))
            self._consumer_tasks.append(task)

        logger.info("EventBus started with %d subscriptions", len(self._handlers))

    async def stop(self) -> None:
        """Stop all consumer loops and close Redis connection."""
        self._running = False

        for task in self._consumer_tasks:
            task.cancel()

        if self._consumer_tasks:
            await asyncio.gather(*self._consumer_tasks, return_exceptions=True)
        self._consumer_tasks.clear()

        if self._redis:
            await self._redis.aclose()
            self._redis = None

        logger.info("EventBus stopped")

    async def publish(self, event: PlatformEvent) -> None:
        """Publish an event to Redis list.

        Args:
            event: The event to publish.

        Raises:
            RuntimeError: If EventBus is not started.
        """
        if self._redis is None:
            raise RuntimeError("EventBus not started. Call start() first.")

        queue_name = f"{_QUEUE_PREFIX}{event.type}"
        await self._redis.lpush(queue_name, event.to_json())
        logger.debug("Published event %s (type=%s)", event.event_id, event.type)

    async def subscribe(self, event_type: str, handler: Callable) -> None:
        """Register a handler for an event type.

        If the bus is already running, starts a new consumer task immediately.

        Args:
            event_type: The event type to subscribe to.
            handler: Async callable that receives a PlatformEvent.
        """
        self._handlers[event_type].append(handler)
        logger.debug("Subscribed handler to event type: %s", event_type)

        # If already running, start consumer for new subscription
        if self._running and self._redis:
            task = asyncio.create_task(self._consume_loop(event_type))
            self._consumer_tasks.append(task)

    async def _consume_loop(self, event_type: str) -> None:
        """Continuously consume events from a Redis list via BRPOP."""
        queue_name = f"{_QUEUE_PREFIX}{event_type}"

        while self._running and self._redis:
            try:
                result = await self._redis.brpop(queue_name, timeout=1)
                if result is None:
                    continue

                _, raw_event = result
                event = PlatformEvent.from_json(raw_event)

                for handler in self._handlers.get(event_type, []):
                    try:
                        await handler(event)
                    except Exception:
                        logger.warning("Handler failed for event %s (type=%s)", event.event_id, event_type, exc_info=True)

            except asyncio.CancelledError:
                break
            except Exception:
                logger.warning("Error in consume loop for %s, retrying...", event_type, exc_info=True)
                await asyncio.sleep(1)
