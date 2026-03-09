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
        """on_event handles bug_report events without error."""
        agent = DevAgent()
        event = MagicMock()
        event.type = "bug_report"
        event.event_id = "evt-123"
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
