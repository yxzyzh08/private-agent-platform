"""Tests for core/task_planner.py — data structures and persistence."""

import json

import pytest

from core.errors import CyclicDependencyError
from core.task_planner import SubTask, TaskPlan, TaskPlanStore, topological_sort


# --- SubTask tests ---


class TestSubTaskSerialization:
    def test_subtask_serialization(self):
        """SubTask JSON round-trip."""
        st = SubTask(
            task_id="1C.1",
            title="Data model",
            description="Implement data structures",
            status="pending",
            depends_on=["1C.0"],
            output_files=["core/task_planner.py"],
            validation_command="uv run pytest tests/ -v",
            max_attempts=3,
        )
        d = st.__dict__.copy()
        restored = SubTask(**d)
        assert restored.task_id == "1C.1"
        assert restored.depends_on == ["1C.0"]
        assert restored.max_attempts == 3
        assert restored.status == "pending"

    def test_subtask_defaults(self):
        st = SubTask(task_id="X.1", title="T", description="D")
        assert st.status == "pending"
        assert st.depends_on == []
        assert st.output_files == []
        assert st.validation_command is None
        assert st.result_summary == ""
        assert st.checkpoint_sha == ""
        assert st.attempt_count == 0
        assert st.max_attempts == 2
        assert st.files_changed == []
        assert st.duration_ms == 0


class TestSubTaskTransition:
    def test_status_transition_valid(self):
        st = SubTask(task_id="X.1", title="T", description="D")
        st.transition_to("in_progress")
        assert st.status == "in_progress"
        st.transition_to("completed")
        assert st.status == "completed"

    def test_status_transition_valid_failure_retry(self):
        st = SubTask(task_id="X.1", title="T", description="D", status="failed")
        st.transition_to("pending")  # retry
        assert st.status == "pending"

    def test_status_transition_valid_failure_skip(self):
        st = SubTask(task_id="X.1", title="T", description="D", status="failed")
        st.transition_to("skipped")
        assert st.status == "skipped"

    def test_status_transition_invalid_pending_to_completed(self):
        st = SubTask(task_id="X.1", title="T", description="D")
        with pytest.raises(ValueError, match="Invalid transition"):
            st.transition_to("completed")

    def test_status_transition_invalid_unknown_status(self):
        st = SubTask(task_id="X.1", title="T", description="D")
        with pytest.raises(ValueError, match="Invalid subtask status"):
            st.transition_to("unknown")


# --- TaskPlan tests ---


class TestTaskPlanSerialization:
    def test_taskplan_serialization(self):
        """TaskPlan JSON round-trip."""
        plan = TaskPlan(
            plan_id="test-123",
            phase_file="docs/phases/phase-1c.md",
            source="cui",
            repo_path="/tmp/repo",
            tasks=[
                SubTask(task_id="1.1", title="A", description="Do A"),
                SubTask(
                    task_id="1.2",
                    title="B",
                    description="Do B",
                    depends_on=["1.1"],
                    status="completed",
                ),
            ],
        )
        d = plan.to_dict()
        json_str = json.dumps(d)
        restored = TaskPlan.from_dict(json.loads(json_str))

        assert restored.plan_id == "test-123"
        assert restored.phase_file == "docs/phases/phase-1c.md"
        assert len(restored.tasks) == 2
        assert restored.tasks[1].depends_on == ["1.1"]
        assert restored.completed_count == 1
        assert restored.total_count == 2

    def test_taskplan_computed_properties(self):
        plan = TaskPlan(
            tasks=[
                SubTask(task_id="1", title="A", description="D", status="completed"),
                SubTask(task_id="2", title="B", description="D", status="pending"),
                SubTask(task_id="3", title="C", description="D", status="completed"),
            ]
        )
        assert plan.completed_count == 2
        assert plan.total_count == 3


class TestTaskPlanTransition:
    def test_plan_transition_valid(self):
        plan = TaskPlan()
        assert plan.status == "executing"
        plan.transition_to("paused")
        assert plan.status == "paused"
        plan.transition_to("executing")
        assert plan.status == "executing"
        plan.transition_to("completed")
        assert plan.status == "completed"

    def test_plan_transition_invalid(self):
        plan = TaskPlan(status="completed")
        with pytest.raises(ValueError, match="Invalid transition"):
            plan.transition_to("executing")

    def test_plan_transition_updates_timestamp(self):
        plan = TaskPlan()
        old_ts = plan.updated_at
        plan.transition_to("paused")
        assert plan.updated_at >= old_ts


# --- TaskPlanStore tests ---


class TestTaskPlanStore:
    def test_taskplan_store_crud(self, tmp_path):
        store = TaskPlanStore(base_dir=str(tmp_path / "plans"))
        plan = TaskPlan(plan_id="p1", phase_file="test.md", repo_path="/tmp")
        plan.tasks = [SubTask(task_id="1", title="A", description="D")]

        # Save
        store.save(plan)
        assert (tmp_path / "plans" / "p1.json").exists()

        # Load
        loaded = store.load("p1")
        assert loaded is not None
        assert loaded.plan_id == "p1"
        assert len(loaded.tasks) == 1

        # List active
        active = store.list_active()
        assert len(active) == 1

        # Update status and save again
        plan.transition_to("completed")
        store.save(plan)
        active = store.list_active()
        assert len(active) == 0

        # Delete
        store.delete("p1")
        assert store.load("p1") is None

    def test_load_nonexistent(self, tmp_path):
        store = TaskPlanStore(base_dir=str(tmp_path / "plans"))
        assert store.load("nonexistent") is None

    def test_list_active_empty_dir(self, tmp_path):
        store = TaskPlanStore(base_dir=str(tmp_path / "nope"))
        assert store.list_active() == []

    def test_list_active_filters_terminal(self, tmp_path):
        store = TaskPlanStore(base_dir=str(tmp_path / "plans"))
        for pid, status in [("a", "executing"), ("b", "paused"), ("c", "failed"), ("d", "aborted")]:
            p = TaskPlan(plan_id=pid, status=status)
            store.save(p)
        active = store.list_active()
        active_ids = {p.plan_id for p in active}
        assert active_ids == {"a", "b"}


# --- Topological sort tests ---


class TestTopologicalSort:
    def test_topological_sort_linear(self):
        """Linear dependency: A -> B -> C."""
        tasks = [
            SubTask(task_id="C", title="C", description="D", depends_on=["B"]),
            SubTask(task_id="B", title="B", description="D", depends_on=["A"]),
            SubTask(task_id="A", title="A", description="D"),
        ]
        result = topological_sort(tasks)
        ids = [t.task_id for t in result]
        assert ids.index("A") < ids.index("B") < ids.index("C")

    def test_topological_sort_parallel(self):
        """No dependencies — preserve original order."""
        tasks = [
            SubTask(task_id="X", title="X", description="D"),
            SubTask(task_id="Y", title="Y", description="D"),
            SubTask(task_id="Z", title="Z", description="D"),
        ]
        result = topological_sort(tasks)
        ids = [t.task_id for t in result]
        assert ids == ["X", "Y", "Z"]

    def test_topological_sort_diamond(self):
        """Diamond dependency: A -> B, A -> C, B+C -> D."""
        tasks = [
            SubTask(task_id="A", title="A", description="D"),
            SubTask(task_id="B", title="B", description="D", depends_on=["A"]),
            SubTask(task_id="C", title="C", description="D", depends_on=["A"]),
            SubTask(task_id="D", title="D", description="D", depends_on=["B", "C"]),
        ]
        result = topological_sort(tasks)
        ids = [t.task_id for t in result]
        assert ids[0] == "A"
        assert ids[-1] == "D"
        assert ids.index("B") < ids.index("D")
        assert ids.index("C") < ids.index("D")

    def test_topological_sort_cycle(self):
        """Cyclic dependency detected."""
        tasks = [
            SubTask(task_id="A", title="A", description="D", depends_on=["C"]),
            SubTask(task_id="B", title="B", description="D", depends_on=["A"]),
            SubTask(task_id="C", title="C", description="D", depends_on=["B"]),
        ]
        with pytest.raises(CyclicDependencyError, match="Cyclic dependency"):
            topological_sort(tasks)

    def test_topological_sort_ignores_external_deps(self):
        """Dependencies on tasks not in the list are ignored."""
        tasks = [
            SubTask(task_id="B", title="B", description="D", depends_on=["A"]),
        ]
        result = topological_sort(tasks)
        assert len(result) == 1
        assert result[0].task_id == "B"
