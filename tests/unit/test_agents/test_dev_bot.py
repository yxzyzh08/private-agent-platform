"""Unit tests for BaseAgent and DevAgent (Task 1B.3)."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest
import yaml

from agents.base_agent import BaseAgent
from agents.dev_agent import DevAgent
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


class TestDevAgentIssueAnalysis:
    def _make_issue_message(
        self,
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

    @patch("agents.dev_agent.DevAgent.get_runtime")
    async def test_issue_analysis(self, mock_get_runtime):
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

        agent = DevAgent()
        msg = self._make_issue_message()
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
    async def test_process_message_routes_to_handle_issue(self, mock_get_runtime):
        mock_runtime = AsyncMock()
        mock_runtime.run.return_value = AgentResponse(
            agent_id="dev_bot", content="analyzed", finish_reason="stop"
        )
        mock_get_runtime.return_value = mock_runtime

        agent = DevAgent()
        msg = self._make_issue_message()
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
        from unittest.mock import MagicMock

        agent = DevAgent()
        event = MagicMock()
        event.type = "bug_report"
        event.event_id = "evt-123"
        await agent.on_event(event)
