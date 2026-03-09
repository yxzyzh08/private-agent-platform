"""Integration tests for the complete Issue flow (Task 1B.7).

Tests multi-step flows chaining Webhook → Analysis → Notification → Confirmation
→ Execution → PR creation, as well as error paths and bug_report→Issue flows.
"""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import yaml

from agents.dev_agent import (
    STATUS_APPROVED,
    STATUS_COMPLETED,
    STATUS_EXECUTING,
    STATUS_FAILED,
    STATUS_PENDING,
    STATUS_REJECTED,
    DevAgent,
    PendingIssueStore,
)
from core.agent_runtime import AgentResponse
from channels.base import Message


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_config(tmp_path, repos=None):
    """Create a dev agent config file and return its path."""
    repos = repos or [{"owner": "myorg", "name": "myrepo", "working_directory": "/tmp/repo"}]
    config_data = {"name": "dev_bot", "github": {"repos": repos}}
    config_file = tmp_path / "dev.yaml"
    config_file.write_text(yaml.dump(config_data))
    return str(config_file)


def _make_agent(tmp_path, repos=None) -> DevAgent:
    """Create a DevAgent with mocked notifier and pending store."""
    config_path = _make_config(tmp_path, repos)
    notifier = AsyncMock()
    notifier.send = AsyncMock(return_value=True)
    store = PendingIssueStore(store_path=str(tmp_path / "pending.json"))
    return DevAgent(config_path=config_path, notifier=notifier, pending_store=store)


def _make_issue_message(issue_number=42, title="Login bug", body="Cannot login"):
    """Create a Message simulating a GitHub Webhook Issue event."""
    return Message(
        text=f"[Issue #{issue_number}] {title}\n\n{body}",
        channel_id="github_webhook",
        user_id="github",
        metadata={
            "event_type": "issues.opened",
            "issue_number": issue_number,
            "issue_title": title,
            "issue_body": body,
            "issue_url": f"https://github.com/myorg/myrepo/issues/{issue_number}",
            "repo_full_name": "myorg/myrepo",
        },
    )


# ---------------------------------------------------------------------------
# 1. Complete happy path flow
# ---------------------------------------------------------------------------


class TestCompleteIssueFlow:
    """End-to-end flow: Webhook → Analysis → Notify → Confirm → Execute → PR."""

    @patch("agents.dev_agent.DevAgent.get_runtime")
    @patch("agents.dev_agent.DevAgent._get_execution_tool")
    @patch("tools.git_tool.GitTool")
    async def test_full_happy_path(
        self, mock_git_cls, mock_get_exec_tool, mock_get_runtime, tmp_path
    ):
        """Complete flow from Issue creation to PR."""
        from tools.base import ToolResult

        agent = _make_agent(tmp_path)

        # Step 1: Runtime returns analysis result
        mock_runtime = AsyncMock()
        mock_runtime.run.return_value = AgentResponse(
            agent_id="dev_bot",
            content=json.dumps({
                "type": "bug",
                "complexity": "simple",
                "summary": "Login form validation broken",
            }),
            finish_reason="stop",
        )
        mock_get_runtime.return_value = mock_runtime

        # Step 2: Handle Issue → triggers analysis + ntfy notification
        msg = _make_issue_message()
        resp = await agent.handle_issue(msg)

        assert resp.finish_reason == "stop"
        # Issue should be in pending store with PENDING status
        issue_key = "myorg/myrepo#42"
        issue = agent._pending_store.get(issue_key)
        assert issue is not None
        assert issue["status"] == STATUS_PENDING
        # Notifier should have been called
        agent._notifier.send.assert_called_once()

        # Step 3: Owner confirms
        confirmed = await agent.confirm_issue(issue_key)
        assert confirmed is True
        assert agent._pending_store.get(issue_key)["status"] == STATUS_APPROVED

        # Step 4: Execute the fix
        mock_exec_tool = AsyncMock()
        mock_exec_tool.execute.return_value = ToolResult(
            success=True,
            data={"result": "Fixed login validation", "needs_rotation": False},
        )
        mock_get_exec_tool.return_value = mock_exec_tool

        # Mock PR creation
        mock_git = AsyncMock()
        mock_git.execute.return_value = ToolResult(
            success=True,
            data={"pr_url": "https://github.com/myorg/myrepo/pull/1", "pr_number": 1},
        )
        mock_git_cls.return_value = mock_git

        exec_resp = await agent.execute_issue(issue_key)
        assert exec_resp.finish_reason == "stop"

        # Verify final state
        final = agent._pending_store.get(issue_key)
        assert final["status"] == STATUS_COMPLETED

    @patch("agents.dev_agent.DevAgent.get_runtime")
    async def test_analysis_stores_issue_and_notifies(self, mock_get_runtime, tmp_path):
        """handle_issue stores issue details and sends ntfy notification."""
        agent = _make_agent(tmp_path)

        mock_runtime = AsyncMock()
        mock_runtime.run.return_value = AgentResponse(
            agent_id="dev_bot",
            content=json.dumps({"type": "feature", "complexity": "medium", "summary": "Add search"}),
            finish_reason="stop",
        )
        mock_get_runtime.return_value = mock_runtime

        msg = _make_issue_message(issue_number=99, title="Search feature", body="Add search")
        await agent.handle_issue(msg)

        issue_key = "myorg/myrepo#99"
        issue = agent._pending_store.get(issue_key)
        assert issue["title"] == "Search feature"
        assert issue["issue_number"] == 99
        assert issue["repo"] == "myorg/myrepo"
        assert "medium" in issue.get("analysis", "")


# ---------------------------------------------------------------------------
# 2. Error and rejection paths
# ---------------------------------------------------------------------------


class TestErrorPaths:
    """Test error and rejection flows."""

    @patch("agents.dev_agent.DevAgent.get_runtime")
    async def test_owner_reject_terminates_flow(self, mock_get_runtime, tmp_path):
        """Owner rejection stops the flow; status becomes rejected."""
        agent = _make_agent(tmp_path)

        mock_runtime = AsyncMock()
        mock_runtime.run.return_value = AgentResponse(
            agent_id="dev_bot",
            content=json.dumps({"type": "bug", "complexity": "simple", "summary": "Fix typo"}),
            finish_reason="stop",
        )
        mock_get_runtime.return_value = mock_runtime

        msg = _make_issue_message(issue_number=50, title="Typo fix")
        await agent.handle_issue(msg)

        issue_key = "myorg/myrepo#50"
        rejected = await agent.reject_issue(issue_key)
        assert rejected is True
        assert agent._pending_store.get(issue_key)["status"] == STATUS_REJECTED

    @patch("agents.dev_agent.DevAgent.get_runtime")
    @patch("agents.dev_agent.DevAgent._get_execution_tool")
    async def test_execution_failure_marks_failed(
        self, mock_get_exec_tool, mock_get_runtime, tmp_path
    ):
        """Execution tool failure → status=failed, ntfy notification sent."""
        agent = _make_agent(tmp_path)

        mock_runtime = AsyncMock()
        mock_runtime.run.return_value = AgentResponse(
            agent_id="dev_bot",
            content=json.dumps({"type": "bug", "complexity": "simple", "summary": "Bug"}),
            finish_reason="stop",
        )
        mock_get_runtime.return_value = mock_runtime

        msg = _make_issue_message(issue_number=60, title="Crash on save")
        await agent.handle_issue(msg)

        issue_key = "myorg/myrepo#60"
        await agent.confirm_issue(issue_key)

        from tools.base import ToolResult

        mock_exec_tool = AsyncMock()
        mock_exec_tool.execute.return_value = ToolResult(
            success=False, error="Timeout: execution took too long"
        )
        mock_get_exec_tool.return_value = mock_exec_tool

        exec_resp = await agent.execute_issue(issue_key)
        assert exec_resp.finish_reason == "error"
        assert agent._pending_store.get(issue_key)["status"] == STATUS_FAILED
        # Should send failure notification
        assert agent._notifier.send.call_count >= 2  # 1 for analysis, 1 for failure

    @patch("agents.dev_agent.DevAgent.get_runtime")
    @patch("agents.dev_agent.DevAgent._get_execution_tool")
    @patch("tools.git_tool.GitTool")
    async def test_pr_creation_failure_still_completes(
        self, mock_git_cls, mock_get_exec_tool, mock_get_runtime, tmp_path
    ):
        """PR creation failure doesn't crash; issue still marked completed."""
        from tools.base import ToolResult

        agent = _make_agent(tmp_path)

        mock_runtime = AsyncMock()
        mock_runtime.run.return_value = AgentResponse(
            agent_id="dev_bot",
            content=json.dumps({"type": "bug", "complexity": "simple", "summary": "Fix"}),
            finish_reason="stop",
        )
        mock_get_runtime.return_value = mock_runtime

        msg = _make_issue_message(issue_number=70, title="PR fail test")
        await agent.handle_issue(msg)

        issue_key = "myorg/myrepo#70"
        await agent.confirm_issue(issue_key)

        mock_exec_tool = AsyncMock()
        mock_exec_tool.execute.return_value = ToolResult(
            success=True, data={"result": "Fixed", "needs_rotation": False}
        )
        mock_get_exec_tool.return_value = mock_exec_tool

        mock_git = AsyncMock()
        mock_git.execute.return_value = ToolResult(
            success=False, error="GITHUB_TOKEN not set"
        )
        mock_git_cls.return_value = mock_git

        exec_resp = await agent.execute_issue(issue_key)
        # Should still complete (PR failure is not fatal)
        assert exec_resp.finish_reason == "stop"
        assert agent._pending_store.get(issue_key)["status"] == STATUS_COMPLETED

    async def test_confirm_timeout_marks_expired(self, tmp_path):
        """Issues past timeout are detected by get_timed_out."""
        store = PendingIssueStore(store_path=str(tmp_path / "pending.json"))
        store.add("org/repo#10", {
            "title": "Old issue",
            "status": STATUS_PENDING,
            "timestamp": 0,  # epoch — always timed out
        })

        timed_out = store.get_timed_out(timeout_seconds=3600)
        assert "org/repo#10" in timed_out

    async def test_execute_unapproved_issue_rejected(self, tmp_path):
        """Cannot execute an issue that hasn't been approved."""
        agent = _make_agent(tmp_path)

        # Add issue in pending state (not approved)
        agent._pending_store.add("myorg/myrepo#80", {
            "title": "Not approved",
            "status": STATUS_PENDING,
            "repo": "myorg/myrepo",
        })

        resp = await agent.execute_issue("myorg/myrepo#80")
        assert resp.finish_reason == "error"
        assert "not in approved state" in resp.content


# ---------------------------------------------------------------------------
# 3. bug_report → Issue → Analysis flow
# ---------------------------------------------------------------------------


class TestBugReportIntegration:
    """bug_report event creates Issue then triggers full analysis."""

    @patch("agents.dev_agent.DevAgent.handle_issue")
    @patch("tools.git_tool.GitTool")
    async def test_bug_report_full_chain(self, mock_git_cls, mock_handle_issue, tmp_path):
        """bug_report event → create GitHub Issue → handle_issue called."""
        from tools.base import ToolResult

        mock_git = AsyncMock()
        mock_git.execute.return_value = ToolResult(
            success=True,
            data={"issue_number": 200, "issue_url": "https://github.com/myorg/myrepo/issues/200"},
        )
        mock_git_cls.return_value = mock_git

        mock_handle_issue.return_value = AgentResponse(
            agent_id="dev_bot", content="analyzed", finish_reason="stop"
        )

        agent = _make_agent(tmp_path)
        event = MagicMock()
        event.type = "bug_report"
        event.event_id = "evt-flow-1"
        event.payload = {
            "title": "Memory leak",
            "body": "Detected high memory usage",
        }

        await agent.on_event(event)

        # GitTool should have been called with create_issue
        mock_git.execute.assert_called_once()
        call_params = mock_git.execute.call_args.args[0]
        assert call_params["operation"] == "create_issue"
        assert call_params["issue_title"] == "Memory leak"
        assert call_params["repo_owner"] == "myorg"
        assert call_params["repo_name"] == "myrepo"

        # handle_issue should have been called with the created issue
        mock_handle_issue.assert_called_once()
        msg = mock_handle_issue.call_args.args[0]
        assert msg.metadata["issue_number"] == 200

    @patch("tools.git_tool.GitTool")
    async def test_bug_report_issue_creation_failure_graceful(self, mock_git_cls, tmp_path):
        """Failed GitHub Issue creation doesn't crash the agent."""
        from tools.base import ToolResult

        mock_git = AsyncMock()
        mock_git.execute.return_value = ToolResult(
            success=False, error="GitHub API rate limited"
        )
        mock_git_cls.return_value = mock_git

        agent = _make_agent(tmp_path)
        event = MagicMock()
        event.type = "bug_report"
        event.event_id = "evt-flow-2"
        event.payload = {"title": "Crash", "body": "App crashes"}

        # Should not raise
        await agent.on_event(event)
        mock_git.execute.assert_called_once()
