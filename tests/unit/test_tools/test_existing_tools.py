"""Unit tests for the tools layer."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from core.errors import ValidationError
from tools.base import BaseTool, ToolResult
from tools.claude_code_cli import ClaudeCodeCliTool
from tools.event_bus_tool import EventBusTool
from tools.git_tool import GitTool


# --- tools/base.py tests ---


class ConcreteTool(BaseTool):
    """Concrete tool for testing BaseTool ABC."""

    name = "test_tool"
    description = "A test tool"
    input_schema = {
        "type": "object",
        "properties": {
            "message": {"type": "string"},
            "count": {"type": "integer"},
        },
        "required": ["message"],
    }

    async def execute(self, params: dict) -> ToolResult:
        return ToolResult(success=True, data={"echo": params.get("message")})


class TestBaseTool:
    async def test_base_tool_is_abstract(self):
        with pytest.raises(TypeError):
            BaseTool()

    async def test_concrete_tool_instantiation(self):
        tool = ConcreteTool()
        assert tool.name == "test_tool"
        assert tool.description == "A test tool"

    async def test_validate_input_passes(self):
        tool = ConcreteTool()
        result = await tool.validate_input({"message": "hello"})
        assert result is True

    async def test_validate_input_with_optional(self):
        tool = ConcreteTool()
        result = await tool.validate_input({"message": "hello", "count": 5})
        assert result is True

    async def test_validate_input_fails_missing_required(self):
        tool = ConcreteTool()
        with pytest.raises(ValidationError, match="Input validation failed"):
            await tool.validate_input({"count": 5})

    async def test_validate_input_fails_wrong_type(self):
        tool = ConcreteTool()
        with pytest.raises(ValidationError, match="Input validation failed"):
            await tool.validate_input({"message": "hello", "count": "not_a_number"})

    async def test_validate_input_no_schema(self):
        tool = ConcreteTool()
        tool.input_schema = {}
        result = await tool.validate_input({"anything": "goes"})
        assert result is True

    async def test_execute_returns_tool_result(self):
        tool = ConcreteTool()
        result = await tool.execute({"message": "hello"})
        assert result.success is True
        assert result.data == {"echo": "hello"}

    async def test_cleanup_default_noop(self):
        tool = ConcreteTool()
        await tool.cleanup()  # Should not raise

    async def test_tool_result_defaults(self):
        result = ToolResult(success=True)
        assert result.data is None
        assert result.error is None

    async def test_tool_result_error(self):
        result = ToolResult(success=False, error="something broke")
        assert result.success is False
        assert result.error == "something broke"


# --- tools/claude_code_cli.py tests ---


class TestClaudeCodeCliTool:
    def setup_method(self):
        self.tool = ClaudeCodeCliTool()

    async def test_name_and_schema(self):
        assert self.tool.name == "claude_code_cli"
        assert "prompt" in self.tool.input_schema["properties"]

    async def test_validate_input_requires_prompt(self):
        with pytest.raises(ValidationError):
            await self.tool.validate_input({})

    async def test_validate_input_passes(self):
        result = await self.tool.validate_input({"prompt": "fix bug"})
        assert result is True

    async def test_execute_binary_not_found(self):
        with patch("asyncio.create_subprocess_exec", side_effect=FileNotFoundError):
            result = await self.tool.execute({"prompt": "test"})
            assert result.success is False
            assert "not found" in result.error

    async def test_execute_timeout(self):
        mock_process = AsyncMock()
        mock_process.communicate = AsyncMock(side_effect=asyncio.TimeoutError)
        mock_process.kill = MagicMock()
        mock_process.wait = AsyncMock()

        with patch("asyncio.create_subprocess_exec", return_value=mock_process):
            with patch("asyncio.wait_for", side_effect=asyncio.TimeoutError):
                result = await self.tool.execute({"prompt": "test", "timeout": 1})
                assert result.success is False
                assert "timed out" in result.error

    async def test_execute_success(self):
        mock_process = AsyncMock()
        mock_process.returncode = 0
        mock_process.communicate = AsyncMock(return_value=(b'{"result": "ok"}', b""))

        async def mock_wait_for(coro, timeout):
            return await coro

        with patch("asyncio.create_subprocess_exec", return_value=mock_process):
            with patch("asyncio.wait_for", side_effect=mock_wait_for):
                result = await self.tool.execute({"prompt": "test"})
                assert result.success is True
                assert result.data == {"result": "ok"}

    async def test_execute_nonzero_exit(self):
        mock_process = AsyncMock()
        mock_process.returncode = 1
        mock_process.communicate = AsyncMock(return_value=(b"", b"error output"))

        async def mock_wait_for(coro, timeout):
            return await coro

        with patch("asyncio.create_subprocess_exec", return_value=mock_process):
            with patch("asyncio.wait_for", side_effect=mock_wait_for):
                result = await self.tool.execute({"prompt": "test"})
                assert result.success is False
                assert "exited with code 1" in result.error

    async def test_env_isolation(self):
        """Verify sensitive env vars are not passed to subprocess."""
        captured_env = {}

        async def capture_exec(*args, **kwargs):
            captured_env.update(kwargs.get("env", {}))
            mock = AsyncMock()
            mock.returncode = 0
            mock.communicate = AsyncMock(return_value=(b'{"ok": true}', b""))
            return mock

        async def mock_wait_for(coro, timeout):
            return await coro

        with (
            patch.dict("os.environ", {"ANTHROPIC_API_KEY": "secret", "PATH": "/usr/bin"}),
            patch("asyncio.create_subprocess_exec", side_effect=capture_exec),
            patch("asyncio.wait_for", side_effect=mock_wait_for),
        ):
            await self.tool.execute({"prompt": "test"})
            assert "ANTHROPIC_API_KEY" not in captured_env
            assert "PATH" in captured_env


# --- tools/git_tool.py tests ---


class TestGitTool:
    def setup_method(self):
        self.tool = GitTool()

    async def test_name_and_schema(self):
        assert self.tool.name == "git"
        assert "operation" in self.tool.input_schema["properties"]

    async def test_validate_input_requires_operation(self):
        with pytest.raises(ValidationError):
            await self.tool.validate_input({})

    async def test_validate_input_invalid_operation(self):
        with pytest.raises(ValidationError):
            await self.tool.validate_input({"operation": "invalid"})

    async def test_clone_requires_repo_url(self):
        result = await self.tool.execute({"operation": "clone"})
        assert result.success is False
        assert "repo_url" in result.error

    async def test_checkout_requires_branch(self):
        result = await self.tool.execute({"operation": "checkout"})
        assert result.success is False
        assert "branch" in result.error

    async def test_commit_requires_message(self):
        result = await self.tool.execute({"operation": "commit"})
        assert result.success is False
        assert "message" in result.error

    async def test_clone_success(self):
        with patch.object(self.tool, "_run_git", return_value=(0, "Cloning...", "")):
            result = await self.tool.execute({"operation": "clone", "repo_url": "https://github.com/test/repo.git"})
            assert result.success is True

    async def test_push_success(self):
        with patch.object(self.tool, "_run_git", return_value=(0, "", "Everything up-to-date")):
            result = await self.tool.execute({"operation": "push"})
            assert result.success is True

    async def test_create_pr_no_token(self):
        with patch.dict("os.environ", {}, clear=True):
            result = await self.tool.execute({"operation": "create_pr", "pr_title": "test"})
            assert result.success is False
            assert "GITHUB_TOKEN" in result.error

    async def test_create_pr_missing_params(self):
        with patch.dict("os.environ", {"GITHUB_TOKEN": "fake"}):
            result = await self.tool.execute({"operation": "create_pr"})
            assert result.success is False
            assert "Missing required" in result.error


# --- tools/event_bus_tool.py tests ---


class TestEventBusTool:
    def setup_method(self):
        self.mock_bus = AsyncMock()
        self.mock_bus.publish = AsyncMock()
        self.tool = EventBusTool(event_bus=self.mock_bus)

    async def test_name_and_schema(self):
        assert self.tool.name == "event_bus"
        assert "operation" in self.tool.input_schema["properties"]

    async def test_validate_input_requires_operation_and_event_type(self):
        with pytest.raises(ValidationError):
            await self.tool.validate_input({})

    async def test_publish_calls_event_bus(self):
        result = await self.tool.execute({
            "operation": "publish",
            "event_type": "test_event",
            "payload": {"key": "value"},
        })
        assert result.success is True
        assert result.data["event_type"] == "test_event"
        self.mock_bus.publish.assert_called_once()

    async def test_subscribe_returns_confirmation(self):
        result = await self.tool.execute({
            "operation": "subscribe",
            "event_type": "test_event",
        })
        assert result.success is True
        assert result.data["status"] == "subscription_registered"

    async def test_publish_handles_error(self):
        self.mock_bus.publish = AsyncMock(side_effect=Exception("bus error"))
        result = await self.tool.execute({
            "operation": "publish",
            "event_type": "test_event",
            "payload": {},
        })
        assert result.success is False
        assert "bus error" in result.error

    async def test_unknown_operation(self):
        # This should fail validation due to enum constraint
        with pytest.raises(ValidationError):
            await self.tool.validate_input({
                "operation": "unknown",
                "event_type": "test",
            })
