"""SSE endpoint for real-time plan execution progress (Phase 1D).

Provides Server-Sent Events streaming for plan execution status updates.
Uses PlanEventBroker for in-process event fan-out.
"""

from __future__ import annotations

import asyncio
import json
import time

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse

from core.logging import get_logger
from core.plan_event_broker import PlanEventBroker
from core.task_planner import TaskPlanStore

logger = get_logger(__name__)

router = APIRouter(prefix="/api/requirements", tags=["requirements-sse"])

DEFAULT_HEARTBEAT_INTERVAL = 30


def _get_heartbeat_interval(config: dict) -> int:
    """Get heartbeat interval from config."""
    return config.get("sse", {}).get(
        "heartbeat_interval_seconds", DEFAULT_HEARTBEAT_INTERVAL
    )


def _get_broker(request: Request) -> PlanEventBroker:
    """Get PlanEventBroker from app state."""
    broker = getattr(request.app.state, "plan_event_broker", None)
    if broker is None:
        raise HTTPException(
            status_code=500,
            detail="PlanEventBroker not initialized",
        )
    return broker


def _format_sse(event_type: str, data: dict) -> str:
    """Format a dict as an SSE message string."""
    return f"event: {event_type}\ndata: {json.dumps(data)}\n\n"


async def _event_stream(
    plan_id: str,
    broker: PlanEventBroker,
    heartbeat_interval: int,
):
    """Generate SSE event stream for a plan."""
    queue = broker.subscribe(plan_id)
    try:
        while True:
            try:
                event = await asyncio.wait_for(
                    queue.get(), timeout=heartbeat_interval
                )
                event_type = event.get("event", "update")
                yield _format_sse(event_type, event)

                # Terminal events — close stream after sending
                if event_type in ("plan_completed", "plan_failed", "plan_stopped"):
                    return
            except asyncio.TimeoutError:
                # Send heartbeat to keep connection alive
                yield _format_sse("heartbeat", {"timestamp": time.time()})
    finally:
        broker.unsubscribe(plan_id, queue)


@router.get("/{plan_id}/events")
async def stream_plan_events(plan_id: str, request: Request):
    """SSE endpoint for real-time plan execution progress."""
    # Verify plan exists
    store = TaskPlanStore()
    plan = store.load(plan_id)
    if plan is None:
        raise HTTPException(status_code=404, detail=f"Plan not found: {plan_id}")

    broker = _get_broker(request)
    config = getattr(request.app.state, "config", {})
    heartbeat_interval = _get_heartbeat_interval(config)

    return StreamingResponse(
        _event_stream(plan_id, broker, heartbeat_interval),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
