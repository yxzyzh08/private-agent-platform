"""Task executor — multi-task serial execution engine.

Executes subtasks from a TaskPlan in topological order, each in a fresh
Claude CLI context. Handles smart checkpoints, markdown writeback, and
git state management.
"""

from __future__ import annotations

import asyncio
import fnmatch
import time
from pathlib import Path
from typing import TYPE_CHECKING

from core.errors import (
    DirtyGitStateError,
    SensitiveFileError,
    SubtaskTimeoutError,
    TaskExecutionError,
)
from core.logging import get_logger
from core.phase_parser import update_task_status
from core.task_planner import SubTask, TaskPlan, TaskPlanStore, topological_sort

if TYPE_CHECKING:
    from core.notifier import Notifier
    from core.tool_registry import ToolRegistry

logger = get_logger(__name__)


async def _run_git(args: list[str], cwd: str) -> tuple[int, str]:
    """Run a git command and return (returncode, stdout)."""
    proc = await asyncio.create_subprocess_exec(
        "git", *args,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        cwd=cwd,
    )
    stdout, _ = await proc.communicate()
    return proc.returncode, stdout.decode("utf-8", errors="replace").strip()


class TaskExecutor:
    """Execute a TaskPlan's subtasks serially in topological order."""

    def __init__(
        self,
        tool_registry: ToolRegistry,
        notifier: Notifier,
        config: dict,
        store: TaskPlanStore | None = None,
    ) -> None:
        self._registry = tool_registry
        self._notifier = notifier
        self._config = config
        self._store = store or TaskPlanStore()
        self._stop_requested = False
        self._consecutive_failures = 0
        self._current_process: asyncio.subprocess.Process | None = None

    def request_stop(self) -> None:
        """Request graceful stop of the current execution."""
        self._stop_requested = True

    async def retry_subtask(self, plan: TaskPlan, task_id: str) -> TaskPlan:
        """Retry a failed subtask by resetting to pending and re-executing."""
        task = self._find_task(plan, task_id)
        if task.status != "failed":
            raise TaskExecutionError(
                f"Task {task_id} is '{task.status}', only 'failed' tasks can be retried"
            )
        task.transition_to("pending")
        if plan.status in ("paused", "failed"):
            plan.transition_to("executing")
        self._consecutive_failures = 0
        self._store.save(plan)
        return await self.execute_plan(plan)

    async def retry_subtask_with_feedback(
        self, plan: TaskPlan, task_id: str, feedback: str
    ) -> TaskPlan:
        """Retry a failed subtask with additional feedback appended to description."""
        task = self._find_task(plan, task_id)
        task.description += f"\n\n## Owner 反馈\n{feedback}"
        return await self.retry_subtask(plan, task_id)

    async def skip_subtask(self, plan: TaskPlan, task_id: str) -> tuple[TaskPlan, list[str]]:
        """Skip a subtask. Returns (plan, warning_list) where warnings list dependent tasks."""
        task = self._find_task(plan, task_id)
        if task.status not in ("failed", "pending"):
            raise TaskExecutionError(
                f"Task {task_id} is '{task.status}', cannot skip"
            )
        if task.status == "failed":
            task.transition_to("pending")
        # Find dependents that will be affected
        dependents = [
            t.task_id for t in plan.tasks
            if task_id in t.depends_on and t.status == "pending"
        ]
        task.transition_to("in_progress")
        task.transition_to("failed")
        task.transition_to("skipped")
        self._store.save(plan)
        await self._notify(
            f"Task {task_id} skipped by owner."
            + (f" Warning: {dependents} depend on it." if dependents else ""),
            title="Task Skipped",
        )
        return plan, dependents

    async def abort_plan(self, plan: TaskPlan) -> TaskPlan:
        """Abort the entire plan. Kills current process if running."""
        await self._kill_current_process()
        plan.transition_to("aborted")
        self._store.save(plan)
        await self._notify(
            f"Plan {plan.plan_id} aborted. {plan.completed_count}/{plan.total_count} completed.",
            title="Plan Aborted",
            priority="high",
        )
        return plan

    async def stop_current(self) -> None:
        """Emergency stop: kill current CLI process group immediately."""
        self._stop_requested = True
        await self._kill_current_process()

    def _find_task(self, plan: TaskPlan, task_id: str) -> SubTask:
        """Find a task by ID, raise if not found."""
        for task in plan.tasks:
            if task.task_id == task_id:
                return task
        raise TaskExecutionError(f"Task {task_id} not found in plan")

    async def _kill_current_process(self) -> None:
        """Kill the currently running CLI process if any."""
        proc = self._current_process
        if proc is None:
            return
        try:
            import os
            import signal
            pgid = os.getpgid(proc.pid)
            os.killpg(pgid, signal.SIGTERM)
            try:
                await asyncio.wait_for(proc.wait(), timeout=5)
            except asyncio.TimeoutError:
                os.killpg(pgid, signal.SIGKILL)
                await proc.wait()
        except ProcessLookupError:
            pass
        except PermissionError:
            logger.warning("Permission denied killing process group for pid %d", proc.pid)

    async def execute_plan(self, plan: TaskPlan) -> TaskPlan:
        """Execute all pending subtasks in topological order.

        Skips completed/skipped tasks. Pauses on failure.
        Returns the updated plan.
        """
        failure_limit = self._config.get("consecutive_failure_limit", 2)

        # Sort tasks by dependencies
        sorted_tasks = topological_sort(plan.tasks)

        for task in sorted_tasks:
            if self._stop_requested:
                plan.transition_to("paused")
                self._store.save(plan)
                await self._notify("Plan paused by owner request", title="Plan Paused")
                break

            if task.status in ("completed", "skipped"):
                continue

            task.transition_to("in_progress")
            self._store.save(plan)

            try:
                await self.execute_subtask(task, plan)
                self._consecutive_failures = 0
            except (TaskExecutionError, SubtaskTimeoutError) as e:
                self._consecutive_failures += 1
                logger.error("Subtask %s failed: %s", task.task_id, e)

                if self._consecutive_failures >= failure_limit:
                    plan.transition_to("failed")
                    self._store.save(plan)
                    await self._notify(
                        f"Plan failed: {self._consecutive_failures} consecutive failures. "
                        f"Last: {task.task_id} — {e}",
                        title="Plan Failed",
                        priority="high",
                    )
                    return plan

                plan.transition_to("paused")
                self._store.save(plan)
                await self._notify(
                    f"Task {task.task_id} failed: {e}\nPlan paused. Use retry/skip/abort.",
                    title="Task Failed",
                )
                return plan

        # Check if all tasks are done
        all_done = all(t.status in ("completed", "skipped") for t in plan.tasks)
        if all_done and plan.status == "executing":
            plan.transition_to("completed")
            self._store.save(plan)
            await self._notify(
                f"All {plan.completed_count}/{plan.total_count} tasks completed!",
                title="Plan Completed",
                tags=["white_check_mark"],
            )

        return plan

    async def execute_subtask(self, task: SubTask, plan: TaskPlan) -> None:
        """Execute a single subtask with safety wrappers.

        1. Check git clean
        2. Record checkpoint SHA
        3. Execute CLI
        4. Smart checkpoint (git add/commit with sensitive file check)
        5. Full sensitive file scan
        6. Write back markdown [x]
        7. Persist plan JSON

        Raises:
            DirtyGitStateError: If git state is not clean.
            TaskExecutionError: If CLI execution fails.
            SubtaskTimeoutError: If the task exceeds timeout.
            SensitiveFileError: If sensitive files are detected.
        """
        repo_path = plan.repo_path
        start_time = time.monotonic()

        # 1. Check git clean
        rc, status_output = await _run_git(["status", "--porcelain"], repo_path)
        if status_output:
            raise DirtyGitStateError(
                f"Git working tree not clean:\n{status_output[:500]}"
            )

        # 2. Record checkpoint
        _, checkpoint_sha = await _run_git(["rev-parse", "HEAD"], repo_path)
        task.checkpoint_sha = checkpoint_sha

        # 3. Execute CLI
        try:
            prompt = self.build_task_prompt(task, plan)
            timeout = self._config.get("subtask_timeout_seconds", 900)
            cli_tool = self._registry.get_tool("claude_code_cli", "dev_bot")
            result = await cli_tool.execute(
                {
                    "prompt": prompt,
                    "working_directory": repo_path,
                    "timeout": timeout,
                },
                agent_id="dev_bot",
            )
        except asyncio.TimeoutError:
            await self._cleanup_on_failure(repo_path, checkpoint_sha)
            task.transition_to("failed")
            task.attempt_count += 1
            raise SubtaskTimeoutError(f"Task {task.task_id} timed out")
        except Exception as e:
            await self._cleanup_on_failure(repo_path, checkpoint_sha)
            task.transition_to("failed")
            task.attempt_count += 1
            raise TaskExecutionError(f"Task {task.task_id} execution error: {e}") from e

        task.duration_ms = int((time.monotonic() - start_time) * 1000)

        if not result.success:
            await self._cleanup_on_failure(repo_path, checkpoint_sha)
            task.transition_to("failed")
            task.attempt_count += 1
            raise TaskExecutionError(
                f"Task {task.task_id} CLI failed: {result.error}"
            )

        # 4. Smart checkpoint
        await self._smart_checkpoint(repo_path, task, plan)

        # 5. Full sensitive file scan across all commits since checkpoint
        sensitive = await self._check_sensitive_files(repo_path, checkpoint_sha)
        if sensitive:
            await _run_git(["reset", "--hard", checkpoint_sha], repo_path)
            task.transition_to("failed")
            task.attempt_count += 1
            await self._notify(
                f"Task {task.task_id} rolled back: modified sensitive files: {sensitive}",
                title="Sensitive File Alert",
                priority="high",
            )
            raise SensitiveFileError(
                f"Task {task.task_id} modified sensitive files: {sensitive}"
            )

        # 6. Write back markdown
        if plan.phase_file:
            update_task_status(plan.phase_file, task.task_id, "x")

        # 7. Update task state and persist
        task.transition_to("completed")
        raw_output = result.data.get("raw_output", str(result.data)) if result.data else ""
        task.result_summary = raw_output[:self._config.get("summary_max_tokens", 1500)]

        # Track changed files
        _, diff_output = await _run_git(
            ["diff", "--name-only", checkpoint_sha, "HEAD"], repo_path
        )
        task.files_changed = [f for f in diff_output.split("\n") if f]

        self._store.save(plan)

    def build_task_prompt(self, task: SubTask, plan: TaskPlan) -> str:
        """Build the prompt for a subtask execution."""
        parts = [
            "## 重要：不要执行 CLAUDE.md 的 Session Recovery 流程",
            "直接执行下面的任务，不需要读取 progress.md 或查找 [ ] 任务。",
            "",
            f"## 任务：{task.title}",
            "",
            task.description,
            "",
        ]

        # Add predecessor summaries
        completed = [t for t in plan.tasks if t.status == "completed" and t.result_summary]
        if completed:
            parts.append("## 前置任务完成情况")
            for t in completed:
                parts.append(f"- Task {t.task_id} \"{t.title}\": {t.result_summary[:200]}")
            parts.append("")

        # Output files
        if task.output_files:
            parts.append("## 需要关注的文件")
            for f in task.output_files:
                parts.append(f"- {f}")
            parts.append("")

        # Notes
        parts.append("## 注意事项")
        parts.append(f"- 工作目录：{plan.repo_path}")
        parts.append("- 不要重复已完成的工作，代码已在 git 中")
        if task.validation_command:
            parts.append(f"- 完成后运行：{task.validation_command}")
        parts.append("- 禁止修改 .env、credentials 等敏感文件")

        return "\n".join(parts)

    async def _smart_checkpoint(
        self, repo_path: str, task: SubTask, plan: TaskPlan
    ) -> None:
        """Git add + sensitive pre-check + commit if there are changes."""
        rc, status_output = await _run_git(["status", "--porcelain"], repo_path)
        if not status_output:
            return  # CLI already committed or no changes

        # Stage all changes
        await _run_git(["add", "-A"], repo_path)

        # Pre-commit sensitive check on staged files
        _, cached_files = await _run_git(["diff", "--cached", "--name-only"], repo_path)
        sensitive = self._match_sensitive(cached_files)
        if sensitive:
            # Unstage sensitive files
            for f in sensitive:
                await _run_git(["reset", "HEAD", "--", f], repo_path)
            await self._notify(
                f"Task {task.task_id}: removed sensitive files from staging: {sensitive}",
                title="Sensitive File Warning",
            )

        # Commit remaining staged files (if any)
        rc, status_after = await _run_git(["diff", "--cached", "--name-only"], repo_path)
        if status_after:
            await _run_git(
                ["commit", "-m", f"auto: {task.task_id} — {task.title}"],
                repo_path,
            )

    async def _check_sensitive_files(
        self, repo_path: str, checkpoint_sha: str
    ) -> list[str]:
        """Check all commits since checkpoint for sensitive file changes."""
        _, diff_output = await _run_git(
            ["diff", "--name-only", checkpoint_sha, "HEAD"], repo_path
        )
        return self._match_sensitive(diff_output)

    def _match_sensitive(self, file_list_str: str) -> list[str]:
        """Match file basenames against sensitive patterns."""
        if not file_list_str.strip():
            return []
        patterns = self._config.get("sensitive_patterns", [])
        matched = []
        for filepath in file_list_str.strip().split("\n"):
            basename = Path(filepath).name
            for pattern in patterns:
                if fnmatch.fnmatch(basename, pattern):
                    matched.append(filepath)
                    break
        return matched

    async def _cleanup_on_failure(self, repo_path: str, checkpoint_sha: str) -> None:
        """Reset to checkpoint SHA on failure."""
        await _run_git(["reset", "--hard", checkpoint_sha], repo_path)

    async def _notify(
        self,
        message: str,
        title: str = "",
        priority: str = "default",
        tags: list[str] | None = None,
    ) -> None:
        """Send notification, log on failure."""
        try:
            await self._notifier.send(
                message=message, title=title, priority=priority, tags=tags
            )
        except Exception:
            logger.warning("Failed to send notification: %s", message)
