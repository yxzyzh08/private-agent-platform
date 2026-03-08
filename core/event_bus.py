"""Event bus — Redis-backed publish/subscribe for platform events.

Full implementation in Task 1.11. PlatformEvent dataclass defined here
as it's used by multiple modules.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone


@dataclass
class PlatformEvent:
    """Platform event data structure for inter-agent communication."""

    type: str
    source_agent: str
    payload: dict
    event_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    correlation_id: str = ""
