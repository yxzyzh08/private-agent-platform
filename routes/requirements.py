"""REST API endpoints for requirement-driven development workflow (Phase 1C).

Provides endpoints for:
- Submitting phase-N.md for execution
- Querying plan status
- Controlling execution (retry, skip, abort)
"""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from core.logging import get_logger, set_trace_id

logger = get_logger(__name__)

router = APIRouter(prefix="/api/requirements", tags=["requirements"])


# --- Request/Response models ---


class FromPhaseRequest(BaseModel):
    phase_file: str
    repo_path: str
    source: str = "cui"


class RetryRequest(BaseModel):
    feedback: str = ""


class PlanResponse(BaseModel):
    plan_id: str
    status: str
    total_count: int
    completed_count: int
    tasks: list[dict]


class ErrorResponse(BaseModel):
    error: str


# --- Helper ---


def _get_dev_agent(request: Request):
    """Get DevAgent from app state, creating if needed."""
    agent = getattr(request.app.state, "dev_agent", None)
    if agent is None:
        from agents.dev_agent import DevAgent

        config = getattr(request.app.state, "config", {})
        tool_registry = getattr(request.app.state, "tool_registry", None)
        agent = DevAgent(tool_registry=tool_registry)
        request.app.state.dev_agent = agent
    return agent


def _plan_to_response(plan) -> dict:
    """Convert TaskPlan to response dict."""
    return {
        "plan_id": plan.plan_id,
        "status": plan.status,
        "total_count": plan.total_count,
        "completed_count": plan.completed_count,
        "tasks": [
            {
                "task_id": t.task_id,
                "title": t.title,
                "status": t.status,
                "attempt_count": t.attempt_count,
                "duration_ms": t.duration_ms,
            }
            for t in plan.tasks
        ],
    }


# --- Endpoints ---


@router.post("/from-phase")
async def submit_from_phase(body: FromPhaseRequest, request: Request):
    """Parse phase-N.md and start execution."""
    set_trace_id()
    phase_path = Path(body.phase_file)
    if not phase_path.exists():
        raise HTTPException(status_code=404, detail=f"Phase file not found: {body.phase_file}")
    if not phase_path.is_file():
        raise HTTPException(status_code=400, detail=f"Not a file: {body.phase_file}")

    agent = _get_dev_agent(request)
    try:
        plan = await agent.execute_from_phase(
            phase_file=body.phase_file,
            repo_path=body.repo_path,
            source=body.source,
        )
    except Exception as e:
        logger.error("execute_from_phase failed: %s", e)
        raise HTTPException(status_code=500, detail=str(e)) from e

    if plan is None:
        return {"message": "No pending tasks to execute"}

    return _plan_to_response(plan)


@router.get("/{plan_id}")
async def get_plan_status(plan_id: str, request: Request):
    """Query plan execution status."""
    agent = _get_dev_agent(request)
    plan = await agent.get_plan_status(plan_id)
    if plan is None:
        raise HTTPException(status_code=404, detail=f"Plan not found: {plan_id}")
    return _plan_to_response(plan)


@router.post("/{plan_id}/abort")
async def abort_plan(plan_id: str, request: Request):
    """Abort an executing plan."""
    agent = _get_dev_agent(request)
    plan = await agent.abort_plan(plan_id)
    if plan is None:
        raise HTTPException(status_code=404, detail=f"Plan not found: {plan_id}")
    return _plan_to_response(plan)


@router.post("/{plan_id}/tasks/{task_id}/retry")
async def retry_task(plan_id: str, task_id: str, body: RetryRequest, request: Request):
    """Retry a failed subtask, optionally with feedback."""
    agent = _get_dev_agent(request)
    try:
        plan = await agent.retry_task(plan_id, task_id, feedback=body.feedback)
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    if plan is None:
        raise HTTPException(status_code=404, detail=f"Plan not found: {plan_id}")
    return _plan_to_response(plan)


@router.post("/{plan_id}/tasks/{task_id}/skip")
async def skip_task(plan_id: str, task_id: str, request: Request):
    """Skip a subtask."""
    agent = _get_dev_agent(request)
    try:
        result = await agent.skip_task(plan_id, task_id)
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    if result is None:
        raise HTTPException(status_code=404, detail=f"Plan not found: {plan_id}")
    return {
        "plan": _plan_to_response(result["plan"]),
        "warnings": result["warnings"],
    }


@router.delete("/{plan_id}")
async def delete_plan(plan_id: str, request: Request):
    """Delete a plan record."""
    from core.task_planner import TaskPlanStore

    store = TaskPlanStore()
    plan = store.load(plan_id)
    if plan is None:
        raise HTTPException(status_code=404, detail=f"Plan not found: {plan_id}")
    store.delete(plan_id)
    return {"message": f"Plan {plan_id} deleted"}
