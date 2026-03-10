"""Tests for core/task_executor.py — task execution engine."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from core.errors import (
    DirtyGitStateError,
    SensitiveFileError,
    TaskExecutionError,
)
from core.task_executor import TaskExecutor
from core.task_planner import SubTask, TaskPlan, TaskPlanStore
from tools.base import ToolResult


@pytest.fixture
def executor_deps(tmp_path):
    """Create executor dependencies with mocks."""
    # Tool registry with mock CLI tool (get_tool is sync, not async)
    from unittest.mock import MagicMock

    registry = MagicMock()
    cli_tool = AsyncMock()
    cli_tool.execute = AsyncMock(
        return_value=ToolResult(success=True, data={"result": "done"})
    )
    registry.get_tool = MagicMock(return_value=cli_tool)

    # Notifier
    notifier = AsyncMock()
    notifier.send = AsyncMock(return_value=True)

    # Config
    config = {
        "subtask_timeout_seconds": 900,
        "consecutive_failure_limit": 2,
        "summary_max_tokens": 1500,
        "sensitive_patterns": [".env*", "*credential*", "*.secret", "*.key", "*.pem"],
    }

    # Store
    store = TaskPlanStore(base_dir=str(tmp_path / "plans"))

    return {
        "registry": registry,
        "notifier": notifier,
        "config": config,
        "store": store,
        "cli_tool": cli_tool,
    }


def _make_executor(deps) -> TaskExecutor:
    return TaskExecutor(
        tool_registry=deps["registry"],
        notifier=deps["notifier"],
        config=deps["config"],
        store=deps["store"],
    )


def _make_plan(tmp_path, tasks=None, phase_file=None) -> TaskPlan:
    """Create a TaskPlan with optional phase file."""
    if phase_file is None:
        pf = tmp_path / "test-phase.md"
        pf.write_text("""\
### Task T.1: First

**状态**: [ ] 未开始
**依赖**: 无

### Task T.2: Second

**状态**: [ ] 未开始
**依赖**: Task T.1
""")
        phase_file = str(pf)

    if tasks is None:
        tasks = [
            SubTask(task_id="T.1", title="First", description="Do first"),
            SubTask(task_id="T.2", title="Second", description="Do second", depends_on=["T.1"]),
        ]

    return TaskPlan(
        plan_id="test-plan",
        phase_file=phase_file,
        repo_path=str(tmp_path),
        tasks=tasks,
    )


# Mock git to return clean status and a fake SHA
async def _mock_git_clean(args, cwd):
    """Simulate clean git state."""
    if args[0] == "status" and "--porcelain" in args:
        return (0, "")
    if args[0] == "rev-parse":
        return (0, "abc123")
    if args[0] == "diff" and "--name-only" in args:
        return (0, "")
    if args[0] == "add":
        return (0, "")
    if args[0] == "commit":
        return (0, "")
    if args[0] == "reset":
        return (0, "")
    return (0, "")


# --- Prompt building tests (L1 — pure logic) ---


class TestBuildTaskPrompt:
    def test_build_task_prompt_session_recovery_override(self, tmp_path, executor_deps):
        executor = _make_executor(executor_deps)
        plan = _make_plan(tmp_path)
        prompt = executor.build_task_prompt(plan.tasks[0], plan)
        assert "不要执行 CLAUDE.md 的 Session Recovery 流程" in prompt
        assert "直接执行下面的任务" in prompt

    def test_build_task_prompt_with_summaries(self, tmp_path, executor_deps):
        executor = _make_executor(executor_deps)
        plan = _make_plan(tmp_path)
        # Mark first task as completed with summary
        plan.tasks[0].status = "completed"
        plan.tasks[0].result_summary = "Created module.py successfully"
        prompt = executor.build_task_prompt(plan.tasks[1], plan)
        assert "前置任务完成情况" in prompt
        assert "Created module.py" in prompt

    def test_build_task_prompt_includes_task_info(self, tmp_path, executor_deps):
        executor = _make_executor(executor_deps)
        plan = _make_plan(tmp_path)
        plan.tasks[0].output_files = ["src/main.py"]
        plan.tasks[0].validation_command = "pytest tests/ -v"
        prompt = executor.build_task_prompt(plan.tasks[0], plan)
        assert "src/main.py" in prompt
        assert "pytest tests/ -v" in prompt
        assert "禁止修改 .env" in prompt

    def test_build_task_prompt_no_summaries_when_none_completed(self, tmp_path, executor_deps):
        executor = _make_executor(executor_deps)
        plan = _make_plan(tmp_path)
        prompt = executor.build_task_prompt(plan.tasks[0], plan)
        assert "前置任务完成情况" not in prompt


# --- Execute plan tests (L2 — mock git + CLI) ---


class TestExecutePlan:
    async def test_execute_plan_all_success(self, tmp_path, executor_deps):
        """All tasks succeed — plan completed."""
        executor = _make_executor(executor_deps)
        plan = _make_plan(tmp_path)

        with patch("core.task_executor._run_git", side_effect=_mock_git_clean):
            result = await executor.execute_plan(plan)

        assert result.status == "completed"
        assert all(t.status == "completed" for t in result.tasks)
        assert result.completed_count == 2

    async def test_execute_plan_skip_completed(self, tmp_path, executor_deps):
        """Completed tasks are skipped."""
        executor = _make_executor(executor_deps)
        plan = _make_plan(tmp_path)
        plan.tasks[0].status = "completed"
        plan.tasks[0].result_summary = "Already done"

        with patch("core.task_executor._run_git", side_effect=_mock_git_clean):
            result = await executor.execute_plan(plan)

        assert result.status == "completed"
        # CLI should only be called once (for T.2)
        cli_tool = executor_deps["cli_tool"]
        assert cli_tool.execute.call_count == 1

    async def test_execute_plan_with_dependencies(self, tmp_path, executor_deps):
        """Tasks are executed in dependency order."""
        executor = _make_executor(executor_deps)
        tasks = [
            SubTask(task_id="C", title="C", description="D", depends_on=["B"]),
            SubTask(task_id="A", title="A", description="D"),
            SubTask(task_id="B", title="B", description="D", depends_on=["A"]),
        ]
        plan = _make_plan(tmp_path, tasks=tasks)

        execution_order = []
        original_execute = executor.execute_subtask

        async def track_execute(task, plan):
            execution_order.append(task.task_id)
            # Call original but with mocked git
            with patch("core.task_executor._run_git", side_effect=_mock_git_clean):
                await original_execute(task, plan)

        with patch.object(executor, "execute_subtask", side_effect=track_execute):
            result = await executor.execute_plan(plan)

        assert execution_order == ["A", "B", "C"]

    async def test_execute_plan_pauses_on_failure(self, tmp_path, executor_deps):
        """Single failure pauses the plan."""
        executor = _make_executor(executor_deps)
        executor_deps["cli_tool"].execute = AsyncMock(
            return_value=ToolResult(success=False, error="CLI failed")
        )
        plan = _make_plan(tmp_path)

        with patch("core.task_executor._run_git", side_effect=_mock_git_clean):
            result = await executor.execute_plan(plan)

        assert result.status == "paused"
        assert result.tasks[0].status == "failed"

    async def test_execute_plan_fails_on_consecutive_failures(self, tmp_path, executor_deps):
        """Two consecutive failures → plan fails."""
        executor = _make_executor(executor_deps)
        executor_deps["cli_tool"].execute = AsyncMock(
            return_value=ToolResult(success=False, error="CLI failed")
        )
        tasks = [
            SubTask(task_id="A", title="A", description="D"),
            SubTask(task_id="B", title="B", description="D"),
            SubTask(task_id="C", title="C", description="D"),
        ]
        plan = _make_plan(tmp_path, tasks=tasks)

        # First call pauses, re-execute to get second failure
        with patch("core.task_executor._run_git", side_effect=_mock_git_clean):
            result = await executor.execute_plan(plan)

        # First failure pauses
        assert result.status == "paused"

        # Retry A (fails again), then B would be second consecutive
        result.tasks[0].status = "pending"
        result.transition_to("executing")

        with patch("core.task_executor._run_git", side_effect=_mock_git_clean):
            result = await executor.execute_plan(plan)

        assert result.status == "failed"

    async def test_execute_plan_stop_requested(self, tmp_path, executor_deps):
        """Graceful stop pauses the plan."""
        executor = _make_executor(executor_deps)
        plan = _make_plan(tmp_path)
        executor.request_stop()

        result = await executor.execute_plan(plan)
        assert result.status == "paused"


# --- Execute subtask tests (L2) ---


class TestExecuteSubtask:
    async def test_execute_subtask_success(self, tmp_path, executor_deps):
        """Successful subtask execution with smart checkpoint."""
        executor = _make_executor(executor_deps)
        plan = _make_plan(tmp_path)
        task = plan.tasks[0]
        task.status = "in_progress"

        with patch("core.task_executor._run_git", side_effect=_mock_git_clean):
            await executor.execute_subtask(task, plan)

        assert task.status == "completed"
        assert task.checkpoint_sha == "abc123"

    async def test_execute_subtask_failure_cleanup(self, tmp_path, executor_deps):
        """Failed execution triggers git reset to checkpoint."""
        executor = _make_executor(executor_deps)
        executor_deps["cli_tool"].execute = AsyncMock(
            return_value=ToolResult(success=False, error="fail")
        )
        plan = _make_plan(tmp_path)
        task = plan.tasks[0]
        task.status = "in_progress"

        git_calls = []

        async def track_git(args, cwd):
            git_calls.append(args)
            return await _mock_git_clean(args, cwd)

        with patch("core.task_executor._run_git", side_effect=track_git):
            with pytest.raises(TaskExecutionError):
                await executor.execute_subtask(task, plan)

        assert task.status == "failed"
        # Verify git reset was called with checkpoint SHA
        reset_calls = [c for c in git_calls if c[0] == "reset"]
        assert len(reset_calls) >= 1
        assert "abc123" in reset_calls[0]

    async def test_dirty_git_state_rejected(self, tmp_path, executor_deps):
        """Dirty git state prevents execution."""
        executor = _make_executor(executor_deps)
        plan = _make_plan(tmp_path)
        task = plan.tasks[0]
        task.status = "in_progress"

        async def dirty_git(args, cwd):
            if args[0] == "status" and "--porcelain" in args:
                return (0, "M dirty_file.py")
            return await _mock_git_clean(args, cwd)

        with patch("core.task_executor._run_git", side_effect=dirty_git):
            with pytest.raises(DirtyGitStateError):
                await executor.execute_subtask(task, plan)

    async def test_cli_already_committed(self, tmp_path, executor_deps):
        """When CLI already committed, smart checkpoint is skipped."""
        executor = _make_executor(executor_deps)
        plan = _make_plan(tmp_path)
        task = plan.tasks[0]
        task.status = "in_progress"

        git_calls = []

        async def track_git(args, cwd):
            git_calls.append(args)
            return await _mock_git_clean(args, cwd)  # status --porcelain returns empty

        with patch("core.task_executor._run_git", side_effect=track_git):
            await executor.execute_subtask(task, plan)

        # No git add/commit should have been called (status was clean)
        commit_calls = [c for c in git_calls if c[0] == "commit"]
        assert len(commit_calls) == 0


# --- Sensitive file tests ---


class TestSensitiveFiles:
    async def test_sensitive_file_detected_in_post_check(self, tmp_path, executor_deps):
        """Sensitive file in CLI commits triggers rollback."""
        executor = _make_executor(executor_deps)
        plan = _make_plan(tmp_path)
        task = plan.tasks[0]
        task.status = "in_progress"

        call_count = 0

        async def git_with_sensitive(args, cwd):
            nonlocal call_count
            call_count += 1
            if args[0] == "status" and "--porcelain" in args:
                return (0, "")
            if args[0] == "rev-parse":
                return (0, "abc123")
            if args[0] == "diff" and "--name-only" in args:
                # The full-range check (checkpoint..HEAD)
                if "abc123" in args:
                    return (0, ".env.production")
                return (0, "")
            if args[0] == "reset":
                return (0, "")
            return (0, "")

        with patch("core.task_executor._run_git", side_effect=git_with_sensitive):
            with pytest.raises(SensitiveFileError, match="sensitive"):
                await executor.execute_subtask(task, plan)

        assert task.status == "failed"

    def test_match_sensitive_patterns(self, executor_deps):
        """Sensitive pattern matching against basename."""
        executor = _make_executor(executor_deps)

        # Should match
        assert executor._match_sensitive(".env") == [".env"]
        assert executor._match_sensitive(".env.production") == [".env.production"]
        assert executor._match_sensitive("src/credentials.json") == ["src/credentials.json"]
        assert executor._match_sensitive("keys/server.key") == ["keys/server.key"]
        assert executor._match_sensitive("certs/ca.pem") == ["certs/ca.pem"]

        # Should NOT match
        assert executor._match_sensitive("src/main.py") == []
        assert executor._match_sensitive("tokenizer.py") == []
        assert executor._match_sensitive("src/token/utils.py") == []

    def test_match_sensitive_empty(self, executor_deps):
        executor = _make_executor(executor_deps)
        assert executor._match_sensitive("") == []
        assert executor._match_sensitive("  ") == []


# --- Plan persistence tests (L1) ---


class TestPlanPersistence:
    async def test_plan_persisted_after_each_task(self, tmp_path, executor_deps):
        """Plan JSON is saved after each task completes."""
        executor = _make_executor(executor_deps)
        plan = _make_plan(tmp_path)

        with patch("core.task_executor._run_git", side_effect=_mock_git_clean):
            result = await executor.execute_plan(plan)

        # Verify plan was persisted
        loaded = executor_deps["store"].load(plan.plan_id)
        assert loaded is not None
        assert loaded.status == "completed"

    async def test_markdown_writeback_after_success(self, tmp_path, executor_deps):
        """Phase markdown is updated with [x] after success."""
        executor = _make_executor(executor_deps)
        plan = _make_plan(tmp_path)

        with patch("core.task_executor._run_git", side_effect=_mock_git_clean):
            await executor.execute_plan(plan)

        # Read the phase file and verify [x]
        content = (tmp_path / "test-phase.md").read_text()
        assert "[x]" in content


# --- Failure handling & control tests (Task 1C.4) ---


class TestRetrySubtask:
    async def test_retry_failed_task(self, tmp_path, executor_deps):
        """Retry resets status to pending and re-executes."""
        executor = _make_executor(executor_deps)
        plan = _make_plan(tmp_path)
        plan.tasks[0].status = "in_progress"
        plan.tasks[0].transition_to("failed")

        with patch("core.task_executor._run_git", side_effect=_mock_git_clean):
            result = await executor.retry_subtask(plan, "T.1")

        assert result.tasks[0].status == "completed"

    async def test_retry_non_failed_task_raises(self, tmp_path, executor_deps):
        """Retrying a non-failed task raises error."""
        executor = _make_executor(executor_deps)
        plan = _make_plan(tmp_path)

        with pytest.raises(TaskExecutionError, match="only 'failed'"):
            await executor.retry_subtask(plan, "T.1")

    async def test_retry_with_feedback_appends_description(self, tmp_path, executor_deps):
        """Feedback is appended to task description."""
        executor = _make_executor(executor_deps)
        plan = _make_plan(tmp_path)
        plan.tasks[0].status = "in_progress"
        plan.tasks[0].transition_to("failed")

        with patch("core.task_executor._run_git", side_effect=_mock_git_clean):
            result = await executor.retry_subtask_with_feedback(
                plan, "T.1", "请使用 asyncio 而不是 threading"
            )

        assert "请使用 asyncio" in result.tasks[0].description
        assert result.tasks[0].status == "completed"

    async def test_retry_resets_consecutive_failures(self, tmp_path, executor_deps):
        """Retry resets the consecutive failure counter."""
        executor = _make_executor(executor_deps)
        executor._consecutive_failures = 1
        plan = _make_plan(tmp_path)
        plan.tasks[0].status = "in_progress"
        plan.tasks[0].transition_to("failed")
        plan.transition_to("paused")

        with patch("core.task_executor._run_git", side_effect=_mock_git_clean):
            await executor.retry_subtask(plan, "T.1")

        assert executor._consecutive_failures == 0


class TestSkipSubtask:
    async def test_skip_failed_task(self, tmp_path, executor_deps):
        """Skip a failed task, marking it as skipped."""
        executor = _make_executor(executor_deps)
        plan = _make_plan(tmp_path)
        plan.tasks[0].status = "in_progress"
        plan.tasks[0].transition_to("failed")

        result, dependents = await executor.skip_subtask(plan, "T.1")

        assert result.tasks[0].status == "skipped"
        # T.2 depends on T.1
        assert "T.2" in dependents

    async def test_skip_no_dependents(self, tmp_path, executor_deps):
        """Skip a task with no dependents returns empty warning list."""
        executor = _make_executor(executor_deps)
        tasks = [
            SubTask(task_id="A", title="A", description="D"),
            SubTask(task_id="B", title="B", description="D"),
        ]
        plan = _make_plan(tmp_path, tasks=tasks)
        plan.tasks[0].status = "in_progress"
        plan.tasks[0].transition_to("failed")

        _, dependents = await executor.skip_subtask(plan, "A")
        assert dependents == []

    async def test_skip_completed_task_raises(self, tmp_path, executor_deps):
        """Cannot skip a completed task."""
        executor = _make_executor(executor_deps)
        plan = _make_plan(tmp_path)
        plan.tasks[0].status = "in_progress"
        plan.tasks[0].transition_to("completed")

        with pytest.raises(TaskExecutionError, match="cannot skip"):
            await executor.skip_subtask(plan, "T.1")


class TestAbortPlan:
    async def test_abort_plan(self, tmp_path, executor_deps):
        """Abort plan sets status to aborted and notifies."""
        executor = _make_executor(executor_deps)
        plan = _make_plan(tmp_path)

        result = await executor.abort_plan(plan)

        assert result.status == "aborted"
        executor_deps["notifier"].send.assert_called_once()
        call_kwargs = executor_deps["notifier"].send.call_args[1]
        assert call_kwargs["priority"] == "high"

    async def test_abort_preserves_completed_tasks(self, tmp_path, executor_deps):
        """Abort preserves already completed task states."""
        executor = _make_executor(executor_deps)
        plan = _make_plan(tmp_path)
        plan.tasks[0].status = "in_progress"
        plan.tasks[0].transition_to("completed")
        plan.tasks[0].checkpoint_sha = "abc123"

        result = await executor.abort_plan(plan)

        assert result.tasks[0].status == "completed"
        assert result.tasks[0].checkpoint_sha == "abc123"


class TestStopCurrent:
    async def test_stop_current_sets_flag(self, tmp_path, executor_deps):
        """stop_current sets the stop flag."""
        executor = _make_executor(executor_deps)

        await executor.stop_current()

        assert executor._stop_requested is True

    async def test_stop_current_kills_process(self, tmp_path, executor_deps):
        """stop_current kills the current process group."""
        executor = _make_executor(executor_deps)
        mock_proc = AsyncMock()
        mock_proc.pid = 99999
        mock_proc.wait = AsyncMock()
        executor._current_process = mock_proc

        with patch("os.getpgid", return_value=99999), \
             patch("os.killpg") as mock_killpg:
            await executor.stop_current()

        mock_killpg.assert_called_once_with(99999, __import__("signal").SIGTERM)


class TestFindTask:
    def test_find_existing_task(self, tmp_path, executor_deps):
        executor = _make_executor(executor_deps)
        plan = _make_plan(tmp_path)
        task = executor._find_task(plan, "T.1")
        assert task.task_id == "T.1"

    def test_find_nonexistent_task_raises(self, tmp_path, executor_deps):
        executor = _make_executor(executor_deps)
        plan = _make_plan(tmp_path)
        with pytest.raises(TaskExecutionError, match="not found"):
            executor._find_task(plan, "T.99")


# --- Phase 1D: Event Broker Integration ---


class TestEventBrokerIntegration:
    """Test that TaskExecutor emits events through PlanEventBroker."""

    def _make_executor_with_broker(self, deps, broker=None):
        if broker is None:
            broker = AsyncMock()
            broker.publish = AsyncMock()
        return TaskExecutor(
            tool_registry=deps["registry"],
            notifier=deps["notifier"],
            config=deps["config"],
            store=deps["store"],
            event_broker=broker,
        ), broker

    @pytest.mark.asyncio
    async def test_event_broker_optional(self, tmp_path, executor_deps):
        """event_broker=None should not break anything."""
        executor = _make_executor(executor_deps)
        assert executor._event_broker is None
        # _emit should be a no-op
        await executor._emit("plan-1", "test", {"data": "x"})

    @pytest.mark.asyncio
    async def test_emit_publishes_event(self, tmp_path, executor_deps):
        """_emit should call broker.publish with correct structure."""
        executor, broker = self._make_executor_with_broker(executor_deps)
        await executor._emit("plan-1", "task_started", {"task_id": "T.1"})
        broker.publish.assert_called_once()
        args = broker.publish.call_args
        assert args[0][0] == "plan-1"
        event = args[0][1]
        assert event["event"] == "task_started"
        assert event["plan_id"] == "plan-1"
        assert event["task_id"] == "T.1"

    @pytest.mark.asyncio
    async def test_emit_failure_isolated(self, tmp_path, executor_deps):
        """_emit failure should not raise, just log warning."""
        broker = AsyncMock()
        broker.publish = AsyncMock(side_effect=RuntimeError("broker down"))
        executor, _ = self._make_executor_with_broker(executor_deps, broker)
        # Should not raise
        await executor._emit("plan-1", "test_event", {})

    @pytest.mark.asyncio
    async def test_plan_started_event(self, tmp_path, executor_deps):
        """execute_plan should emit plan_started event."""
        executor, broker = self._make_executor_with_broker(executor_deps)
        plan = _make_plan(tmp_path, tasks=[
            SubTask(task_id="T.1", title="Test", description="Test task"),
        ])

        with patch("core.task_executor._run_git", new_callable=AsyncMock) as mock_git:
            mock_git.return_value = (0, "")
            await executor.execute_plan(plan)

        # Check plan_started was emitted
        events = [call[0][1]["event"] for call in broker.publish.call_args_list]
        assert "plan_started" in events

    @pytest.mark.asyncio
    async def test_task_completed_event(self, tmp_path, executor_deps):
        """execute_plan should emit task_completed for successful tasks."""
        executor, broker = self._make_executor_with_broker(executor_deps)
        plan = _make_plan(tmp_path, tasks=[
            SubTask(task_id="T.1", title="Test", description="Test task"),
        ])

        with patch("core.task_executor._run_git", new_callable=AsyncMock) as mock_git:
            mock_git.return_value = (0, "")
            await executor.execute_plan(plan)

        events = [call[0][1]["event"] for call in broker.publish.call_args_list]
        assert "task_started" in events
        assert "task_completed" in events

    @pytest.mark.asyncio
    async def test_plan_completed_event(self, tmp_path, executor_deps):
        """execute_plan should emit plan_completed when all tasks done."""
        executor, broker = self._make_executor_with_broker(executor_deps)
        plan = _make_plan(tmp_path, tasks=[
            SubTask(task_id="T.1", title="Test", description="Test task"),
        ])

        with patch("core.task_executor._run_git", new_callable=AsyncMock) as mock_git:
            mock_git.return_value = (0, "")
            await executor.execute_plan(plan)

        events = [call[0][1]["event"] for call in broker.publish.call_args_list]
        assert "plan_completed" in events

    @pytest.mark.asyncio
    async def test_task_failed_event(self, tmp_path, executor_deps):
        """task failure should emit task_failed event."""
        executor_deps["cli_tool"].execute = AsyncMock(
            return_value=ToolResult(success=False, data=None, error="CLI error")
        )
        executor, broker = self._make_executor_with_broker(executor_deps)
        plan = _make_plan(tmp_path, tasks=[
            SubTask(task_id="T.1", title="Test", description="Test task"),
        ])

        with patch("core.task_executor._run_git", new_callable=AsyncMock) as mock_git:
            mock_git.return_value = (0, "abc123")
            await executor.execute_plan(plan)

        events = [call[0][1]["event"] for call in broker.publish.call_args_list]
        assert "task_failed" in events

    @pytest.mark.asyncio
    async def test_plan_stopped_event(self, tmp_path, executor_deps):
        """request_stop should emit plan_stopped event."""
        executor, broker = self._make_executor_with_broker(executor_deps)
        plan = _make_plan(tmp_path, tasks=[
            SubTask(task_id="T.1", title="Test", description="Test task"),
        ])
        executor.request_stop()

        with patch("core.task_executor._run_git", new_callable=AsyncMock) as mock_git:
            mock_git.return_value = (0, "")
            await executor.execute_plan(plan)

        events = [call[0][1]["event"] for call in broker.publish.call_args_list]
        assert "plan_stopped" in events
