"""Unit tests for BaseAgent and DevAgent (Task 1B.3 + 1B.4)."""

from __future__ import annotations

import json
import time
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import yaml

from agents.base_agent import BaseAgent
from agents.dev_agent import (
    CONFIRMATION_TIMEOUT_SECONDS,
    STATUS_APPROVED,
    STATUS_COMPLETED,
    STATUS_EXECUTING,
    STATUS_FAILED,
    STATUS_PENDING,
    STATUS_REJECTED,
    STATUS_TIMEOUT,
    DevAgent,
    PendingIssueStore,
)
from channels.base import Message
from core.agent_runtime import AgentResponse


# --- BaseAgent tests ---


class ConcreteAgent(BaseAgent):
    """Minimal concrete agent for testing BaseAgent."""

    async def process_message(self, message: Message) -> AgentResponse:
        return AgentResponse(agent_id=self.agent_id, content="ok", finish_reason="stop")


class TestBaseAgent:
    def test_base_agent_is_abstract(self):
        with pytest.raises(TypeError):
            BaseAgent(agent_id="test")

    def test_concrete_agent(self):
        agent = ConcreteAgent(agent_id="test_agent")
        assert agent.agent_id == "test_agent"
        assert agent.name == "test_agent"

    def test_load_config(self, tmp_path):
        config_data = {
            "name": "my_bot",
            "model": "claude-sonnet-4-6",
            "tools": {"allowed": ["git_tool", "claude_code_cli"]},
            "persona": "You are helpful.",
        }
        config_file = tmp_path / "agent.yaml"
        config_file.write_text(yaml.dump(config_data))

        agent = ConcreteAgent(agent_id="my_bot", config_path=str(config_file))
        assert agent.name == "my_bot"
        assert agent.allowed_tools == ["git_tool", "claude_code_cli"]
        assert agent.system_prompt == "You are helpful."

    def test_missing_config(self):
        agent = ConcreteAgent(agent_id="test", config_path="/nonexistent.yaml")
        assert agent.config == {}
        assert agent.allowed_tools == []

    def test_get_runtime(self, mock_config):
        agent = ConcreteAgent(agent_id="test")
        runtime = agent.get_runtime()
        assert runtime is not None
        assert runtime is agent.get_runtime()  # same instance

    async def test_process_message(self):
        agent = ConcreteAgent(agent_id="test")
        msg = Message(text="hello", channel_id="test")
        resp = await agent.process_message(msg)
        assert resp.content == "ok"

    async def test_on_event_default(self):
        agent = ConcreteAgent(agent_id="test")
        await agent.on_event(None)  # should not raise


# --- DevAgent tests ---


class TestDevAgent:
    def test_dev_agent_creation(self):
        agent = DevAgent()
        assert agent.agent_id == "dev_bot"

    def test_dev_agent_with_config(self, tmp_path):
        config_data = {
            "name": "dev_bot",
            "type": "event",
            "model": "claude-sonnet-4-6",
            "tools": {"allowed": ["claude_code_cli", "git_tool"]},
            "github": {
                "repos": [
                    {"owner": "test-user", "name": "test-repo", "branch": "main"},
                ],
            },
        }
        config_file = tmp_path / "dev.yaml"
        config_file.write_text(yaml.dump(config_data))

        agent = DevAgent(config_path=str(config_file))
        assert agent.repos == [{"owner": "test-user", "name": "test-repo", "branch": "main"}]
        assert "claude_code_cli" in agent.allowed_tools

    def test_repos_empty_without_config(self):
        agent = DevAgent()
        assert agent.repos == []


# --- Helper ---

def _make_issue_message(
    title: str = "Fix login bug",
    body: str = "Login fails on mobile devices",
    number: int = 42,
) -> Message:
    return Message(
        text=f"[Issue #{number}] {title}\n\n{body}",
        channel_id="github_webhook",
        user_id="reporter",
        metadata={
            "event_type": "issues.opened",
            "issue_number": number,
            "issue_title": title,
            "issue_body": body,
            "issue_url": f"https://github.com/owner/repo/issues/{number}",
            "repo_full_name": "owner/repo",
        },
    )


class TestDevAgentIssueAnalysis:
    @patch("agents.dev_agent.DevAgent.get_runtime")
    async def test_issue_analysis(self, mock_get_runtime, tmp_path):
        """Issue analysis invokes the LLM runtime and returns response."""
        mock_runtime = AsyncMock()
        analysis_result = json.dumps({
            "type": "bug",
            "summary": "Login fails on mobile devices",
            "complexity": "simple",
            "suggested_approach": "Fix responsive CSS",
        })
        mock_runtime.run.return_value = AgentResponse(
            agent_id="dev_bot",
            content=analysis_result,
            finish_reason="stop",
        )
        mock_get_runtime.return_value = mock_runtime

        notifier = AsyncMock()
        notifier.send = AsyncMock(return_value=True)
        store = PendingIssueStore(store_path=str(tmp_path / "pending.json"))

        agent = DevAgent(notifier=notifier, pending_store=store)
        msg = _make_issue_message()
        resp = await agent.handle_issue(msg)

        assert resp.finish_reason == "stop"
        result = json.loads(resp.content)
        assert result["type"] == "bug"
        mock_runtime.run.assert_called_once()

        # Verify prompt contains issue info
        call_kwargs = mock_runtime.run.call_args
        prompt = call_kwargs.kwargs.get("user_input") or call_kwargs.args[0]
        assert "Fix login bug" in prompt
        assert "Login fails on mobile" in prompt

    @patch("agents.dev_agent.DevAgent.get_runtime")
    async def test_process_message_routes_to_handle_issue(self, mock_get_runtime, tmp_path):
        mock_runtime = AsyncMock()
        mock_runtime.run.return_value = AgentResponse(
            agent_id="dev_bot", content="analyzed", finish_reason="stop"
        )
        mock_get_runtime.return_value = mock_runtime

        notifier = AsyncMock()
        notifier.send = AsyncMock(return_value=True)
        store = PendingIssueStore(store_path=str(tmp_path / "pending.json"))

        agent = DevAgent(notifier=notifier, pending_store=store)
        msg = _make_issue_message()
        resp = await agent.process_message(msg)
        assert resp.content == "analyzed"

    async def test_process_message_unknown_event(self):
        agent = DevAgent()
        msg = Message(
            text="unknown",
            channel_id="github_webhook",
            metadata={"event_type": "pull_request.opened"},
        )
        resp = await agent.process_message(msg)
        assert "Unhandled" in resp.content

    async def test_on_event_bug_report(self):
        """on_event handles bug_report events without error (no repos → early return)."""
        agent = DevAgent()
        event = MagicMock()
        event.type = "bug_report"
        event.event_id = "evt-123"
        event.payload = {"title": "Test Bug", "body": "Details"}
        await agent.on_event(event)


# --- Owner Confirmation tests (Task 1B.4) ---


class TestOwnerConfirmation:
    @patch("agents.dev_agent.DevAgent.get_runtime")
    async def test_owner_confirm_approve(self, mock_get_runtime, tmp_path):
        """Owner confirms → status transitions to approved."""
        mock_runtime = AsyncMock()
        mock_runtime.run.return_value = AgentResponse(
            agent_id="dev_bot", content='{"type":"bug"}', finish_reason="stop"
        )
        mock_get_runtime.return_value = mock_runtime

        notifier = AsyncMock()
        notifier.send = AsyncMock(return_value=True)
        store = PendingIssueStore(store_path=str(tmp_path / "pending.json"))
        agent = DevAgent(notifier=notifier, pending_store=store)

        msg = _make_issue_message(number=10)
        await agent.handle_issue(msg)

        issue_key = "owner/repo#10"
        assert store.get(issue_key)["status"] == STATUS_PENDING

        result = await agent.confirm_issue(issue_key)
        assert result is True
        assert store.get(issue_key)["status"] == STATUS_APPROVED

    @patch("agents.dev_agent.DevAgent.get_runtime")
    async def test_owner_confirm_reject(self, mock_get_runtime, tmp_path):
        """Owner rejects → status transitions to rejected."""
        mock_runtime = AsyncMock()
        mock_runtime.run.return_value = AgentResponse(
            agent_id="dev_bot", content='{"type":"feature"}', finish_reason="stop"
        )
        mock_get_runtime.return_value = mock_runtime

        notifier = AsyncMock()
        notifier.send = AsyncMock(return_value=True)
        store = PendingIssueStore(store_path=str(tmp_path / "pending.json"))
        agent = DevAgent(notifier=notifier, pending_store=store)

        msg = _make_issue_message(number=20)
        await agent.handle_issue(msg)

        issue_key = "owner/repo#20"
        result = await agent.reject_issue(issue_key)
        assert result is True
        assert store.get(issue_key)["status"] == STATUS_REJECTED

    @patch("agents.dev_agent.DevAgent.get_runtime")
    async def test_owner_confirm_timeout(self, mock_get_runtime, tmp_path):
        """Issues pending for > 24h are timed out."""
        mock_runtime = AsyncMock()
        mock_runtime.run.return_value = AgentResponse(
            agent_id="dev_bot", content='{"type":"bug"}', finish_reason="stop"
        )
        mock_get_runtime.return_value = mock_runtime

        notifier = AsyncMock()
        notifier.send = AsyncMock(return_value=True)
        store = PendingIssueStore(store_path=str(tmp_path / "pending.json"))
        agent = DevAgent(notifier=notifier, pending_store=store)

        msg = _make_issue_message(number=30)
        await agent.handle_issue(msg)

        # Manually set created_at to 25 hours ago
        issue_key = "owner/repo#30"
        data = store.load()
        data[issue_key]["created_at"] = time.time() - (25 * 3600)
        store.save(data)

        timed_out = await agent.check_timeouts()
        assert issue_key in timed_out
        assert store.get(issue_key)["status"] == STATUS_TIMEOUT

    async def test_confirm_nonexistent_issue(self):
        """Confirming a non-existent issue returns False."""
        store = PendingIssueStore(store_path="/tmp/test_nonexistent.json")
        agent = DevAgent(pending_store=store)
        result = await agent.confirm_issue("nonexistent#1")
        assert result is False

    async def test_reject_nonexistent_issue(self):
        """Rejecting a non-existent issue returns False."""
        store = PendingIssueStore(store_path="/tmp/test_nonexistent2.json")
        agent = DevAgent(pending_store=store)
        result = await agent.reject_issue("nonexistent#1")
        assert result is False


class TestPendingIssueStore:
    def test_add_and_get(self, tmp_path):
        store = PendingIssueStore(store_path=str(tmp_path / "pending.json"))
        store.add("repo#1", {"status": "pending", "title": "Bug fix"})
        issue = store.get("repo#1")
        assert issue is not None
        assert issue["title"] == "Bug fix"

    def test_remove(self, tmp_path):
        store = PendingIssueStore(store_path=str(tmp_path / "pending.json"))
        store.add("repo#1", {"status": "pending"})
        store.remove("repo#1")
        assert store.get("repo#1") is None

    def test_update_status(self, tmp_path):
        store = PendingIssueStore(store_path=str(tmp_path / "pending.json"))
        store.add("repo#1", {"status": "pending"})
        store.update_status("repo#1", "approved")
        assert store.get("repo#1")["status"] == "approved"

    def test_persistence(self, tmp_path):
        """Data survives across store instances."""
        path = str(tmp_path / "pending.json")
        store1 = PendingIssueStore(store_path=path)
        store1.add("repo#1", {"status": "pending", "data": "test"})

        store2 = PendingIssueStore(store_path=path)
        assert store2.get("repo#1")["data"] == "test"

    def test_load_empty(self, tmp_path):
        store = PendingIssueStore(store_path=str(tmp_path / "nonexistent.json"))
        assert store.load() == {}

    def test_get_timed_out(self, tmp_path):
        store = PendingIssueStore(store_path=str(tmp_path / "pending.json"))
        store.add("repo#1", {"status": STATUS_PENDING, "created_at": time.time() - 90000})
        store.add("repo#2", {"status": STATUS_PENDING, "created_at": time.time()})
        store.add("repo#3", {"status": STATUS_APPROVED, "created_at": time.time() - 90000})

        timed_out = store.get_timed_out()
        assert "repo#1" in timed_out
        assert "repo#2" not in timed_out  # not expired
        assert "repo#3" not in timed_out  # already approved


# --- Notifier tests (Task 1B.4) ---


class TestNtfyNotification:
    @patch("agents.dev_agent.DevAgent.get_runtime")
    async def test_ntfy_notification_sent(self, mock_get_runtime, tmp_path):
        """ntfy notification is sent after issue analysis."""
        mock_runtime = AsyncMock()
        mock_runtime.run.return_value = AgentResponse(
            agent_id="dev_bot", content='{"type":"bug"}', finish_reason="stop"
        )
        mock_get_runtime.return_value = mock_runtime

        notifier = AsyncMock()
        notifier.send = AsyncMock(return_value=True)
        store = PendingIssueStore(store_path=str(tmp_path / "pending.json"))
        agent = DevAgent(notifier=notifier, pending_store=store)

        msg = _make_issue_message(number=50, title="Critical bug")
        await agent.handle_issue(msg)

        notifier.send.assert_called_once()
        call_kwargs = notifier.send.call_args
        assert "Critical bug" in (call_kwargs.kwargs.get("message") or call_kwargs.args[0])
        assert call_kwargs.kwargs.get("priority") == "high"


# --- Issue Execution tests (Task 1B.5) ---


def _make_approved_issue(store, tmp_path, number=42, complexity="simple"):
    """Helper: create an approved issue in the store."""
    issue_key = f"owner/repo#{number}"
    store.add(issue_key, {
        "status": STATUS_APPROVED,
        "issue_number": number,
        "title": f"Fix bug #{number}",
        "body": "Something is broken",
        "repo": "owner/repo",
        "issue_url": f"https://github.com/owner/repo/issues/{number}",
        "analysis": json.dumps({
            "type": "bug",
            "summary": "A bug",
            "complexity": complexity,
            "suggested_approach": "Fix it",
        }),
        "created_at": time.time(),
    })
    return issue_key


class TestIssueExecution:
    @patch("agents.dev_agent.DevAgent._create_pr")
    @patch("agents.dev_agent.DevAgent._get_execution_tool")
    async def test_execute_issue_success(self, mock_get_tool, mock_create_pr, tmp_path):
        """Approved issue executes via CLI/SDK tool and creates PR."""
        from tools.base import ToolResult

        mock_tool = AsyncMock()
        mock_tool.execute.return_value = ToolResult(
            success=True,
            data={"result": "Bug fixed", "session_id": "sess-1"},
        )
        mock_get_tool.return_value = mock_tool

        mock_create_pr.return_value = ToolResult(
            success=True,
            data={"pr_url": "https://github.com/owner/repo/pull/1", "pr_number": 1},
        )

        notifier = AsyncMock()
        notifier.send = AsyncMock(return_value=True)
        store = PendingIssueStore(store_path=str(tmp_path / "pending.json"))
        agent = DevAgent(notifier=notifier, pending_store=store)

        issue_key = _make_approved_issue(store, tmp_path)
        resp = await agent.execute_issue(issue_key)

        assert resp.finish_reason == "stop"
        assert store.get(issue_key)["status"] == STATUS_COMPLETED
        mock_tool.execute.assert_called_once()
        mock_create_pr.assert_called_once()

    @patch("agents.dev_agent.DevAgent._get_execution_tool")
    async def test_execute_issue_not_approved(self, mock_get_tool, tmp_path):
        """Cannot execute an issue that is not approved."""
        store = PendingIssueStore(store_path=str(tmp_path / "pending.json"))
        store.add("owner/repo#99", {"status": STATUS_PENDING})
        agent = DevAgent(pending_store=store)

        resp = await agent.execute_issue("owner/repo#99")
        assert resp.finish_reason == "error"
        assert "not in approved state" in resp.content
        mock_get_tool.assert_not_called()

    @patch("agents.dev_agent.DevAgent._create_pr")
    @patch("agents.dev_agent.DevAgent._get_execution_tool")
    async def test_execute_issue_tool_failure(self, mock_get_tool, mock_create_pr, tmp_path):
        """Tool execution failure marks issue as failed and notifies Owner."""
        from tools.base import ToolResult

        mock_tool = AsyncMock()
        mock_tool.execute.return_value = ToolResult(
            success=False,
            error="CLI timed out",
        )
        mock_get_tool.return_value = mock_tool

        notifier = AsyncMock()
        notifier.send = AsyncMock(return_value=True)
        store = PendingIssueStore(store_path=str(tmp_path / "pending.json"))
        agent = DevAgent(notifier=notifier, pending_store=store)

        issue_key = _make_approved_issue(store, tmp_path)
        resp = await agent.execute_issue(issue_key)

        assert resp.finish_reason == "error"
        assert store.get(issue_key)["status"] == STATUS_FAILED
        notifier.send.assert_called_once()  # Owner notified of failure
        mock_create_pr.assert_not_called()

    @patch("agents.dev_agent.DevAgent._create_pr")
    @patch("agents.dev_agent.DevAgent._get_execution_tool")
    async def test_execute_issue_complexity_max_turns(self, mock_get_tool, mock_create_pr, tmp_path):
        """Complex issues get higher max_turns."""
        from tools.base import ToolResult

        mock_tool = AsyncMock()
        mock_tool.execute.return_value = ToolResult(success=True, data={"result": "done"})
        mock_get_tool.return_value = mock_tool

        mock_create_pr.return_value = ToolResult(success=True, data={"pr_url": "url"})

        store = PendingIssueStore(store_path=str(tmp_path / "pending.json"))
        agent = DevAgent(pending_store=store)

        issue_key = _make_approved_issue(store, tmp_path, number=77, complexity="complex")
        await agent.execute_issue(issue_key)

        call_params = mock_tool.execute.call_args.args[0]
        assert call_params["max_turns"] == 200

    @patch("agents.dev_agent.get_config")
    async def test_get_execution_tool_subprocess(self, mock_config):
        """Default backend returns ClaudeCodeCliTool."""
        mock_config.return_value = {"cli": {"backend": "subprocess"}}
        agent = DevAgent()
        tool = agent._get_execution_tool()
        assert tool.name == "claude_code_cli"

    @patch("agents.dev_agent.get_config")
    async def test_get_execution_tool_sdk(self, mock_config):
        """SDK backend returns ClaudeCodeSDKTool."""
        mock_config.return_value = {"cli": {"backend": "sdk"}}
        agent = DevAgent()
        tool = agent._get_execution_tool()
        assert tool.name == "claude_code_sdk"

    def test_parse_complexity(self):
        """_parse_complexity extracts complexity from JSON."""
        assert DevAgent._parse_complexity('{"complexity": "complex"}') == "complex"
        assert DevAgent._parse_complexity('{"complexity": "medium"}') == "medium"
        assert DevAgent._parse_complexity("not json") == "simple"
        assert DevAgent._parse_complexity('{"type": "bug"}') == "simple"

    async def test_execute_nonexistent_issue(self, tmp_path):
        """Executing a non-existent issue returns error."""
        store = PendingIssueStore(store_path=str(tmp_path / "pending.json"))
        agent = DevAgent(pending_store=store)
        resp = await agent.execute_issue("nonexistent#1")
        assert resp.finish_reason == "error"


# --- Bug Report → Issue tests (Task 1B.6) ---


class TestBugReportToIssue:
    @patch("agents.dev_agent.DevAgent.handle_issue")
    @patch("tools.git_tool.GitTool")
    async def test_bug_report_creates_issue(self, mock_git_cls, mock_handle_issue, tmp_path):
        """bug_report event creates a GitHub Issue and triggers analysis."""
        from tools.base import ToolResult

        mock_git = AsyncMock()
        mock_git.execute.return_value = ToolResult(
            success=True,
            data={"issue_number": 100, "issue_url": "https://github.com/owner/repo/issues/100"},
        )
        mock_git_cls.return_value = mock_git

        mock_handle_issue.return_value = AgentResponse(
            agent_id="dev_bot", content="analyzed", finish_reason="stop"
        )

        config_data = {
            "name": "dev_bot",
            "github": {"repos": [{"owner": "owner", "name": "repo"}]},
        }
        config_file = tmp_path / "dev.yaml"
        import yaml
        config_file.write_text(yaml.dump(config_data))

        notifier = AsyncMock()
        notifier.send = AsyncMock(return_value=True)
        store = PendingIssueStore(store_path=str(tmp_path / "pending.json"))
        agent = DevAgent(
            config_path=str(config_file),
            notifier=notifier,
            pending_store=store,
        )

        event = MagicMock()
        event.type = "bug_report"
        event.event_id = "evt-999"
        event.payload = {
            "title": "Login crash",
            "body": "App crashes on login",
        }

        await agent.on_event(event)

        mock_git.execute.assert_called_once()
        call_params = mock_git.execute.call_args.args[0]
        assert call_params["operation"] == "create_issue"
        assert call_params["issue_title"] == "Login crash"

        mock_handle_issue.assert_called_once()
        msg_arg = mock_handle_issue.call_args.args[0]
        assert msg_arg.metadata["issue_number"] == 100

    @patch("tools.git_tool.GitTool")
    async def test_bug_report_no_repo_configured(self, mock_git_cls):
        """bug_report with no repo configured returns None."""
        agent = DevAgent()
        event = MagicMock()
        event.type = "bug_report"
        event.event_id = "evt-1"
        event.payload = {"title": "Bug"}

        await agent.on_event(event)
        mock_git_cls.assert_not_called()

    @patch("tools.git_tool.GitTool")
    async def test_bug_report_issue_creation_fails(self, mock_git_cls, tmp_path):
        """Failed issue creation logs error and returns None."""
        from tools.base import ToolResult

        mock_git = AsyncMock()
        mock_git.execute.return_value = ToolResult(success=False, error="API error")
        mock_git_cls.return_value = mock_git

        config_data = {
            "name": "dev_bot",
            "github": {"repos": [{"owner": "o", "name": "r"}]},
        }
        config_file = tmp_path / "dev.yaml"
        import yaml
        config_file.write_text(yaml.dump(config_data))

        agent = DevAgent(config_path=str(config_file))

        event = MagicMock()
        event.type = "bug_report"
        event.event_id = "evt-2"
        event.payload = {"title": "Bug"}

        await agent.on_event(event)
        mock_git.execute.assert_called_once()
