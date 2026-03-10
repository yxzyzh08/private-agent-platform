"""Task planning data structures and persistence.

Defines TaskPlan and SubTask dataclasses for the requirement-driven
development workflow (Phase 1C). Provides JSON file persistence via
TaskPlanStore and topological sorting of task dependencies.
"""

from __future__ import annotations

import json
import time
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path

from core.errors import CyclicDependencyError
from core.logging import get_logger

logger = get_logger(__name__)

# Valid status values and allowed transitions
_SUBTASK_STATUSES = {"pending", "in_progress", "completed", "failed", "skipped"}
_SUBTASK_TRANSITIONS: dict[str, set[str]] = {
    "pending": {"in_progress"},
    "in_progress": {"completed", "failed"},
    "failed": {"pending", "skipped"},  # pending = retry
    "completed": {"pending"},  # allow re-run
    "skipped": set(),
}

_PLAN_STATUSES = {"executing", "paused", "completed", "failed", "aborted"}
_PLAN_TRANSITIONS: dict[str, set[str]] = {
    "executing": {"paused", "completed", "failed", "aborted"},
    "paused": {"executing", "aborted"},
    "failed": {"executing"},  # retry
    "completed": set(),
    "aborted": set(),
}


@dataclass
class SubTask:
    """A single subtask corresponding to a Task block in phase-N.md."""

    task_id: str
    title: str
    description: str
    status: str = "pending"
    depends_on: list[str] = field(default_factory=list)
    output_files: list[str] = field(default_factory=list)
    validation_command: str | None = None
    result_summary: str = ""
    checkpoint_sha: str = ""
    attempt_count: int = 0
    max_attempts: int = 2
    files_changed: list[str] = field(default_factory=list)
    duration_ms: int = 0

    def transition_to(self, new_status: str) -> None:
        """Transition to a new status with validation."""
        if new_status not in _SUBTASK_STATUSES:
            raise ValueError(f"Invalid subtask status: {new_status}")
        allowed = _SUBTASK_TRANSITIONS.get(self.status, set())
        if new_status not in allowed:
            raise ValueError(
                f"Invalid transition: {self.status} -> {new_status} "
                f"(allowed: {allowed})"
            )
        self.status = new_status


@dataclass
class TaskPlan:
    """A complete task plan parsed from a phase-N.md file."""

    plan_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    phase_file: str = ""
    source: str = "cui"
    source_ref: str = ""
    status: str = "executing"
    tasks: list[SubTask] = field(default_factory=list)
    branch: str = ""
    base_branch: str = "main"
    repo_path: str = ""
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)

    @property
    def completed_count(self) -> int:
        return sum(1 for t in self.tasks if t.status == "completed")

    @property
    def total_count(self) -> int:
        return len(self.tasks)

    def transition_to(self, new_status: str) -> None:
        """Transition plan to a new status with validation."""
        if new_status not in _PLAN_STATUSES:
            raise ValueError(f"Invalid plan status: {new_status}")
        allowed = _PLAN_TRANSITIONS.get(self.status, set())
        if new_status not in allowed:
            raise ValueError(
                f"Invalid transition: {self.status} -> {new_status} "
                f"(allowed: {allowed})"
            )
        self.status = new_status
        self.updated_at = time.time()

    def to_dict(self) -> dict:
        d = asdict(self)
        # Remove computed properties (they are not in asdict since they're properties)
        return d

    @classmethod
    def from_dict(cls, d: dict) -> TaskPlan:
        tasks_data = d.pop("tasks", [])
        # Remove computed fields that may exist in old JSON
        d.pop("completed_count", None)
        d.pop("total_count", None)
        plan = cls(**d)
        plan.tasks = [SubTask(**t) for t in tasks_data]
        return plan


def topological_sort(tasks: list[SubTask]) -> list[SubTask]:
    """Sort tasks by dependency order (Kahn's algorithm).

    Tasks with no dependencies maintain their original order.

    Raises:
        CyclicDependencyError: If there is a cycle in the dependency graph.
    """
    task_map = {t.task_id: t for t in tasks}
    in_degree: dict[str, int] = {t.task_id: 0 for t in tasks}

    for t in tasks:
        for dep in t.depends_on:
            if dep in task_map:
                in_degree[t.task_id] += 1

    # Start with tasks that have no dependencies (in original order)
    queue = [t.task_id for t in tasks if in_degree[t.task_id] == 0]
    result: list[SubTask] = []

    while queue:
        tid = queue.pop(0)
        result.append(task_map[tid])

        # Find tasks that depend on this one (in original order)
        for t in tasks:
            if tid in t.depends_on and t.task_id in in_degree:
                in_degree[t.task_id] -= 1
                if in_degree[t.task_id] == 0:
                    queue.append(t.task_id)

    if len(result) != len(tasks):
        sorted_ids = {t.task_id for t in result}
        cycle_ids = [t.task_id for t in tasks if t.task_id not in sorted_ids]
        raise CyclicDependencyError(
            f"Cyclic dependency detected among tasks: {cycle_ids}"
        )

    return result


class TaskPlanStore:
    """JSON file persistence for TaskPlan objects."""

    def __init__(
        self, base_dir: str = "data/agents/dev_bot/workspace/task_plans/"
    ) -> None:
        self._base_dir = Path(base_dir)

    def _plan_path(self, plan_id: str) -> Path:
        return self._base_dir / f"{plan_id}.json"

    def save(self, plan: TaskPlan) -> None:
        """Save or update a plan."""
        plan.updated_at = time.time()
        self._base_dir.mkdir(parents=True, exist_ok=True)
        path = self._plan_path(plan.plan_id)
        path.write_text(json.dumps(plan.to_dict(), indent=2, ensure_ascii=False))
        logger.debug("Saved plan %s to %s", plan.plan_id, path)

    def load(self, plan_id: str) -> TaskPlan | None:
        """Load a plan by ID. Returns None if not found."""
        path = self._plan_path(plan_id)
        if not path.exists():
            return None
        data = json.loads(path.read_text())
        return TaskPlan.from_dict(data)

    def list_active(self) -> list[TaskPlan]:
        """List plans with status not in completed/failed/aborted."""
        terminal = {"completed", "failed", "aborted"}
        result = []
        if not self._base_dir.exists():
            return result
        for path in sorted(self._base_dir.glob("*.json")):
            try:
                data = json.loads(path.read_text())
                if data.get("status") not in terminal:
                    result.append(TaskPlan.from_dict(data))
            except (json.JSONDecodeError, TypeError, KeyError) as e:
                logger.warning("Failed to load plan from %s: %s", path, e)
        return result

    def delete(self, plan_id: str) -> None:
        """Delete a plan file."""
        path = self._plan_path(plan_id)
        if path.exists():
            path.unlink()
            logger.debug("Deleted plan %s", plan_id)
