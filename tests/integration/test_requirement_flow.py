"""L2 Integration tests — requirement-driven development full flow.

Tests the complete pipeline: API → DevAgent → PhaseFileParser → TaskExecutor →
markdown writeback. Claude CLI and git operations are fully mocked.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from core.errors import TaskExecutionError
from core.task_executor import TaskExecutor
from core.task_planner import TaskPlan, TaskPlanStore
from core.phase_parser import parse_phase_file_safe, phase_tasks_to_subtasks
from tools.base import ToolResult


# --- Mock factories ---


def make_mock_cli(results: list[ToolResult]) -> MagicMock:
    """Create a mock CLI tool that returns results in sequence."""
    registry = MagicMock()
    cli_tool = AsyncMock()
    cli_tool.execute = AsyncMock(side_effect=results)
    registry.get_tool = MagicMock(return_value=cli_tool)
    return registry, cli_tool


async def mock_git_clean(args, cwd):
    """Simulate a clean git repository."""
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


def make_executor(registry, tmp_path, config_overrides=None):
    """Create a TaskExecutor with mock dependencies."""
    notifier = AsyncMock()
    notifier.send = AsyncMock(return_value=True)
    config = {
        "subtask_timeout_seconds": 900,
        "consecutive_failure_limit": 2,
        "summary_max_tokens": 1500,
        "sensitive_patterns": [".env*", "*credential*", "*.secret", "*.key", "*.pem"],
    }
    if config_overrides:
        config.update(config_overrides)
    store = TaskPlanStore(base_dir=str(tmp_path / "plans"))
    return TaskExecutor(
        tool_registry=registry,
        notifier=notifier,
        config=config,
        store=store,
    ), notifier, store


def write_phase_file(tmp_path, tasks_spec):
    """Write a phase file from a list of (task_id, title, deps, done) tuples."""
    lines = ["# Phase Test\n\n---\n"]
    for tid, title, deps, done in tasks_spec:
        status = "[x] 完成" if done else "[ ] 未开始"
        dep_str = ", ".join(f"Task {d}" for d in deps) if deps else "无"
        lines.append(f"### Task {tid}: {title}\n")
        lines.append(f"**状态**: {status}\n")
        lines.append(f"**依赖**: {dep_str}\n")
        lines.append(f"\n**描述**: Do {title}\n\n")
    pf = tmp_path / "phase-test.md"
    pf.write_text("\n".join(lines))
    return str(pf)


# --- Integration tests ---


class TestFullSuccessFlow:
    async def test_three_tasks_all_success(self, tmp_path):
        """Full success: 3 tasks → all completed → markdown [x]."""
        phase_file = write_phase_file(tmp_path, [
            ("T.1", "First", [], False),
            ("T.2", "Second", ["T.1"], False),
            ("T.3", "Third", ["T.2"], False),
        ])

        results = [
            ToolResult(success=True, data={"result": "done1"}),
            ToolResult(success=True, data={"result": "done2"}),
            ToolResult(success=True, data={"result": "done3"}),
        ]
        registry, cli = make_mock_cli(results)
        executor, notifier, store = make_executor(registry, tmp_path)

        # Parse → plan → execute
        phase_tasks, _ = parse_phase_file_safe(phase_file)
        subtasks = phase_tasks_to_subtasks(phase_tasks)
        plan = TaskPlan(
            plan_id="test-full",
            phase_file=phase_file,
            repo_path=str(tmp_path),
            tasks=subtasks,
        )

        with patch("core.task_executor._run_git", side_effect=mock_git_clean):
            result = await executor.execute_plan(plan)

        assert result.status == "completed"
        assert result.completed_count == 3
        assert cli.execute.call_count == 3

        # Verify markdown writeback
        content = (tmp_path / "phase-test.md").read_text()
        assert content.count("[x]") == 3


class TestBreakpointResume:
    async def test_resume_with_completed_tasks(self, tmp_path):
        """Resume: 2 done + 2 pending → only execute 2."""
        phase_file = write_phase_file(tmp_path, [
            ("T.1", "First", [], True),
            ("T.2", "Second", [], True),
            ("T.3", "Third", ["T.1"], False),
            ("T.4", "Fourth", ["T.2"], False),
        ])

        results = [
            ToolResult(success=True, data={"result": "done3"}),
            ToolResult(success=True, data={"result": "done4"}),
        ]
        registry, cli = make_mock_cli(results)
        executor, _, store = make_executor(registry, tmp_path)

        phase_tasks, _ = parse_phase_file_safe(phase_file)
        # Filter out completed tasks (status == "x")
        pending = [t for t in phase_tasks if t.status != "x"]
        subtasks = phase_tasks_to_subtasks(pending)
        plan = TaskPlan(
            plan_id="test-resume",
            phase_file=phase_file,
            repo_path=str(tmp_path),
            tasks=subtasks,
        )

        with patch("core.task_executor._run_git", side_effect=mock_git_clean):
            result = await executor.execute_plan(plan)

        assert result.status == "completed"
        assert cli.execute.call_count == 2


class TestFailureAndRetry:
    async def test_fail_pause_retry_success(self, tmp_path):
        """Fail → pause → retry → success → continue."""
        phase_file = write_phase_file(tmp_path, [
            ("T.1", "First", [], False),
            ("T.2", "Second", ["T.1"], False),
        ])

        # First call fails, retry succeeds, T.2 succeeds
        results = [
            ToolResult(success=False, error="compilation error"),
            ToolResult(success=True, data={"result": "fixed"}),
            ToolResult(success=True, data={"result": "done2"}),
        ]
        registry, cli = make_mock_cli(results)
        executor, notifier, store = make_executor(registry, tmp_path)

        phase_tasks, _ = parse_phase_file_safe(phase_file)
        subtasks = phase_tasks_to_subtasks(phase_tasks)
        plan = TaskPlan(
            plan_id="test-retry",
            phase_file=phase_file,
            repo_path=str(tmp_path),
            tasks=subtasks,
        )

        # First run — T.1 fails → paused
        with patch("core.task_executor._run_git", side_effect=mock_git_clean):
            result = await executor.execute_plan(plan)

        assert result.status == "paused"
        assert result.tasks[0].status == "failed"

        # Retry T.1
        with patch("core.task_executor._run_git", side_effect=mock_git_clean):
            result = await executor.retry_subtask(result, "T.1")

        assert result.status == "completed"
        assert result.completed_count == 2


class TestSkipFlow:
    async def test_skip_and_continue(self, tmp_path):
        """Skip failed task → continue with remaining."""
        phase_file = write_phase_file(tmp_path, [
            ("T.1", "First", [], False),
            ("T.2", "Second", [], False),
        ])

        results = [
            ToolResult(success=False, error="broken"),
            ToolResult(success=True, data={"result": "done2"}),
        ]
        registry, cli = make_mock_cli(results)
        executor, _, store = make_executor(registry, tmp_path)

        phase_tasks, _ = parse_phase_file_safe(phase_file)
        subtasks = phase_tasks_to_subtasks(phase_tasks)
        plan = TaskPlan(
            plan_id="test-skip",
            phase_file=phase_file,
            repo_path=str(tmp_path),
            tasks=subtasks,
        )

        # T.1 fails
        with patch("core.task_executor._run_git", side_effect=mock_git_clean):
            result = await executor.execute_plan(plan)

        assert result.status == "paused"

        # Skip T.1, continue
        result, warnings = await executor.skip_subtask(result, "T.1")
        assert result.tasks[0].status == "skipped"

        # Resume plan — T.2 should execute
        result.transition_to("executing")
        with patch("core.task_executor._run_git", side_effect=mock_git_clean):
            result = await executor.execute_plan(result)

        # All done (1 skipped + 1 completed)
        assert result.status == "completed"


class TestAbortFlow:
    async def test_abort_preserves_checkpoints(self, tmp_path):
        """Abort plan preserves completed tasks."""
        phase_file = write_phase_file(tmp_path, [
            ("T.1", "First", [], False),
            ("T.2", "Second", [], False),
        ])

        results = [
            ToolResult(success=True, data={"result": "done1"}),
            ToolResult(success=True, data={"result": "done2"}),
        ]
        registry, cli = make_mock_cli(results)
        executor, _, store = make_executor(registry, tmp_path)

        phase_tasks, _ = parse_phase_file_safe(phase_file)
        subtasks = phase_tasks_to_subtasks(phase_tasks)
        plan = TaskPlan(
            plan_id="test-abort",
            phase_file=phase_file,
            repo_path=str(tmp_path),
            tasks=subtasks,
        )

        # Run T.1 only, then stop
        original_execute = executor.execute_subtask
        call_count = 0

        async def execute_then_stop(task, plan):
            nonlocal call_count
            call_count += 1
            with patch("core.task_executor._run_git", side_effect=mock_git_clean):
                await original_execute(task, plan)
            if call_count == 1:
                executor.request_stop()

        with patch.object(executor, "execute_subtask", side_effect=execute_then_stop):
            result = await executor.execute_plan(plan)

        assert result.tasks[0].status == "completed"
        assert result.status == "paused"

        # Abort
        result = await executor.abort_plan(result)
        assert result.status == "aborted"
        assert result.tasks[0].status == "completed"  # Preserved


class TestConsecutiveFailures:
    async def test_two_consecutive_failures_aborts(self, tmp_path):
        """Two consecutive failures → plan failed."""
        phase_file = write_phase_file(tmp_path, [
            ("T.1", "First", [], False),
            ("T.2", "Second", [], False),
            ("T.3", "Third", [], False),
        ])

        results = [
            ToolResult(success=False, error="fail1"),
            ToolResult(success=False, error="fail2"),
        ]
        registry, cli = make_mock_cli(results)
        executor, notifier, store = make_executor(registry, tmp_path)

        phase_tasks, _ = parse_phase_file_safe(phase_file)
        subtasks = phase_tasks_to_subtasks(phase_tasks)
        plan = TaskPlan(
            plan_id="test-consecutive",
            phase_file=phase_file,
            repo_path=str(tmp_path),
            tasks=subtasks,
        )

        # T.1 fails → paused
        with patch("core.task_executor._run_git", side_effect=mock_git_clean):
            result = await executor.execute_plan(plan)
        assert result.status == "paused"

        # Reset T.1, retry plan
        result.tasks[0].transition_to("pending")
        result.transition_to("executing")

        with patch("core.task_executor._run_git", side_effect=mock_git_clean):
            result = await executor.execute_plan(result)

        assert result.status == "failed"


class TestSensitiveFileProtection:
    async def test_sensitive_file_triggers_rollback(self, tmp_path):
        """Sensitive file in commit → rollback + task failed."""
        phase_file = write_phase_file(tmp_path, [
            ("T.1", "First", [], False),
        ])

        results = [ToolResult(success=True, data={"result": "done"})]
        registry, cli = make_mock_cli(results)
        executor, notifier, store = make_executor(registry, tmp_path)

        phase_tasks, _ = parse_phase_file_safe(phase_file)
        subtasks = phase_tasks_to_subtasks(phase_tasks)
        plan = TaskPlan(
            plan_id="test-sensitive",
            phase_file=phase_file,
            repo_path=str(tmp_path),
            tasks=subtasks,
        )

        async def git_with_sensitive(args, cwd):
            if args[0] == "status" and "--porcelain" in args:
                return (0, "")
            if args[0] == "rev-parse":
                return (0, "abc123")
            if args[0] == "diff" and "--name-only" in args:
                if "abc123" in args:
                    return (0, ".env.production")
                return (0, "")
            if args[0] == "reset":
                return (0, "")
            return (0, "")

        with patch("core.task_executor._run_git", side_effect=git_with_sensitive):
            result = await executor.execute_plan(plan)

        assert result.status == "paused"
        assert result.tasks[0].status == "failed"
