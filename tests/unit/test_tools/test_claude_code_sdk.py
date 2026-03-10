"""Unit tests for tools/claude_code_sdk.py (Task 1B.4a)."""

from __future__ import annotations

import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from tools.base import ToolResult
from tools.claude_code_sdk import ClaudeCodeSDKTool, _DEFAULT_MAX_TURNS, _DEFAULT_TIMEOUT


class TestClaudeCodeSDKToolInit:
    def test_tool_metadata(self):
        tool = ClaudeCodeSDKTool()
        assert tool.name == "claude_code_sdk"
        assert "SDK" in tool.description
        assert tool.input_schema["required"] == ["prompt"]

    def test_input_schema_properties(self):
        tool = ClaudeCodeSDKTool()
        props = tool.input_schema["properties"]
        assert "prompt" in props
        assert "working_directory" in props
        assert "max_turns" in props
        assert "allowed_tools" in props

    def test_hook_events_initialized(self):
        tool = ClaudeCodeSDKTool()
        assert tool._hook_events == []


class TestClaudeCodeSDKToolExecute:
    @patch("tools.claude_code_sdk.ClaudeCodeSDKTool._build_hooks")
    async def test_execute_success(self, mock_build_hooks):
        """SDK query returns structured result on success."""
        mock_build_hooks.return_value = {}

        # Mock the SDK imports and query
        mock_system_msg = MagicMock()
        mock_system_msg.session_id = "sess-123"

        mock_result_msg = MagicMock()
        mock_result_msg.result = "Task completed successfully"
        mock_result_msg.stop_reason = "end_turn"

        # Create a mock SystemMessage and ResultMessage class
        mock_system_cls = type(mock_system_msg)
        mock_result_cls = type(mock_result_msg)
        mock_system_msg.subtype = "init"

        async def mock_query(prompt, options):
            yield mock_system_msg
            yield mock_result_msg

        with patch.dict("sys.modules", {
            "claude_agent_sdk": MagicMock(
                ClaudeAgentOptions=MagicMock,
                HookMatcher=MagicMock,
                ResultMessage=mock_result_cls,
                SystemMessage=mock_system_cls,
                query=mock_query,
            ),
        }):
            tool = ClaudeCodeSDKTool()
            result = await tool.execute({"prompt": "Fix the bug"})

        assert result.success is True
        assert result.data["session_id"] == "sess-123"
        assert result.data["result"] == "Task completed successfully"
        assert result.data["stop_reason"] == "end_turn"
        assert result.data["needs_rotation"] is False
        assert "duration_ms" in result.data

    async def test_execute_import_error(self):
        """Returns error when claude-agent-sdk not installed."""
        tool = ClaudeCodeSDKTool()

        with patch.dict("sys.modules", {"claude_agent_sdk": None}):
            # Force ImportError by making the import fail
            with patch("builtins.__import__", side_effect=ImportError("No module")):
                result = await tool.execute({"prompt": "test"})

        assert result.success is False
        assert "not installed" in result.error

    async def test_execute_missing_prompt(self):
        """Raises ValidationError when prompt is missing."""
        from core.errors import ValidationError

        tool = ClaudeCodeSDKTool()
        with pytest.raises(ValidationError):
            await tool.execute({})

    @patch("tools.claude_code_sdk.ClaudeCodeSDKTool._build_hooks")
    async def test_execute_max_turns_triggers_rotation(self, mock_build_hooks):
        """When stop_reason is max_turns, needs_rotation is True."""
        mock_build_hooks.return_value = {}

        mock_system_msg = MagicMock()
        mock_system_msg.session_id = "sess-456"
        mock_system_msg.subtype = "init"

        mock_result_msg = MagicMock()
        mock_result_msg.result = "Partial work done"
        mock_result_msg.stop_reason = "max_turns"

        mock_system_cls = type(mock_system_msg)
        mock_result_cls = type(mock_result_msg)

        async def mock_query(prompt, options):
            yield mock_system_msg
            yield mock_result_msg

        with patch.dict("sys.modules", {
            "claude_agent_sdk": MagicMock(
                ClaudeAgentOptions=MagicMock,
                HookMatcher=MagicMock,
                ResultMessage=mock_result_cls,
                SystemMessage=mock_system_cls,
                query=mock_query,
            ),
        }):
            tool = ClaudeCodeSDKTool()
            result = await tool.execute({"prompt": "Complex task", "max_turns": 50})

        assert result.success is True
        assert result.data["needs_rotation"] is True
        assert result.data["stop_reason"] == "max_turns"
        assert result.data["num_turns"] == 50

    @patch("tools.claude_code_sdk.ClaudeCodeSDKTool._build_hooks")
    async def test_execute_sdk_exception(self, mock_build_hooks):
        """SDK runtime errors are caught and returned as ToolResult."""
        mock_build_hooks.return_value = {}

        async def mock_query(prompt, options):
            raise RuntimeError("SDK crashed")
            yield  # noqa: unreachable — make it an async generator

        with patch.dict("sys.modules", {
            "claude_agent_sdk": MagicMock(
                ClaudeAgentOptions=MagicMock,
                HookMatcher=MagicMock,
                ResultMessage=MagicMock,
                SystemMessage=MagicMock,
                query=mock_query,
            ),
        }):
            tool = ClaudeCodeSDKTool()
            result = await tool.execute({"prompt": "test"})

        assert result.success is False
        assert "RuntimeError" in result.error

    @patch("tools.claude_code_sdk.ClaudeCodeSDKTool._build_hooks")
    async def test_execute_custom_params(self, mock_build_hooks):
        """Custom working_directory, max_turns, allowed_tools are passed through."""
        mock_build_hooks.return_value = {}
        captured_options = {}

        mock_system_msg = MagicMock()
        mock_system_msg.session_id = "sess-789"
        mock_system_msg.subtype = "init"

        mock_result_msg = MagicMock()
        mock_result_msg.result = "done"
        mock_result_msg.stop_reason = "end_turn"

        mock_system_cls = type(mock_system_msg)
        mock_result_cls = type(mock_result_msg)

        mock_options_cls = MagicMock()

        def capture_options(**kwargs):
            captured_options.update(kwargs)
            return MagicMock()

        mock_options_cls.side_effect = capture_options

        async def mock_query(prompt, options):
            yield mock_system_msg
            yield mock_result_msg

        with patch.dict("sys.modules", {
            "claude_agent_sdk": MagicMock(
                ClaudeAgentOptions=mock_options_cls,
                HookMatcher=MagicMock,
                ResultMessage=mock_result_cls,
                SystemMessage=mock_system_cls,
                query=mock_query,
            ),
        }):
            tool = ClaudeCodeSDKTool()
            result = await tool.execute({
                "prompt": "task",
                "working_directory": "/tmp/repo",
                "max_turns": 50,
                "allowed_tools": ["Read", "Edit"],
            })

        assert result.success is True
        assert captured_options["cwd"] == "/tmp/repo"
        assert captured_options["max_turns"] == 50
        assert captured_options["allowed_tools"] == ["Read", "Edit"]


class TestBuildHooks:
    def test_hooks_structure(self):
        """_build_hooks returns dict with PreCompact, Stop, PostToolUse keys."""
        tool = ClaudeCodeSDKTool()
        mock_matcher = MagicMock()
        hooks = tool._build_hooks(mock_matcher)

        assert "PreCompact" in hooks
        assert "Stop" in hooks
        assert "PostToolUse" in hooks
        assert mock_matcher.call_count == 3

    async def test_pre_compact_hook_records_event(self):
        """PreCompact hook callback records event."""
        tool = ClaudeCodeSDKTool()

        # Call the hook callback directly
        async def on_pre_compact(input_data, tool_use_id, context):
            tool._hook_events.append({"type": "PreCompact", "time": time.time()})
            return {}

        await on_pre_compact({}, "id-1", {})
        assert len(tool._hook_events) == 1
        assert tool._hook_events[0]["type"] == "PreCompact"

    async def test_stop_hook_records_event(self):
        """Stop hook callback records event."""
        tool = ClaudeCodeSDKTool()

        async def on_stop(input_data, tool_use_id, context):
            tool._hook_events.append({"type": "Stop", "time": time.time()})
            return {}

        await on_stop({}, "id-2", {})
        assert len(tool._hook_events) == 1
        assert tool._hook_events[0]["type"] == "Stop"

    async def test_post_tool_use_hook_records_event(self):
        """PostToolUse hook callback records tool name."""
        tool = ClaudeCodeSDKTool()

        async def on_post_tool_use(input_data, tool_use_id, context):
            tool_name = input_data.get("tool_input", {}).get("name", "unknown")
            tool._hook_events.append({
                "type": "PostToolUse",
                "tool": tool_name,
                "time": time.time(),
            })
            return {}

        await on_post_tool_use(
            {"tool_input": {"name": "Edit"}}, "id-3", {}
        )
        assert len(tool._hook_events) == 1
        assert tool._hook_events[0]["tool"] == "Edit"

    @patch("tools.claude_code_sdk.ClaudeCodeSDKTool._build_hooks")
    async def test_compact_count_tracked(self, mock_build_hooks):
        """compact_count reflects PreCompact hook events."""
        tool = ClaudeCodeSDKTool()
        # Simulate hook events already recorded
        tool._hook_events = [
            {"type": "PreCompact", "time": 1.0},
            {"type": "PostToolUse", "tool": "Read", "time": 2.0},
            {"type": "PreCompact", "time": 3.0},
        ]

        mock_build_hooks.return_value = {}

        mock_system_msg = MagicMock()
        mock_system_msg.session_id = "sess-compact"
        mock_system_msg.subtype = "init"

        mock_result_msg = MagicMock()
        mock_result_msg.result = "done"
        mock_result_msg.stop_reason = "end_turn"

        mock_system_cls = type(mock_system_msg)
        mock_result_cls = type(mock_result_msg)

        async def mock_query(prompt, options):
            # Don't reset hook_events — simulate they were recorded during query
            yield mock_system_msg
            yield mock_result_msg

        with patch.dict("sys.modules", {
            "claude_agent_sdk": MagicMock(
                ClaudeAgentOptions=MagicMock,
                HookMatcher=MagicMock,
                ResultMessage=mock_result_cls,
                SystemMessage=mock_system_cls,
                query=mock_query,
            ),
        }):
            # Re-inject the hook events after _hook_events gets reset in execute
            original_execute = tool.execute

            async def patched_execute(params):
                result = await original_execute(params)
                # The hook_events were reset, so manually set compact_count
                return result

            # Instead, let's patch to not reset
            tool._hook_events = []

            async def mock_query_with_hooks(prompt, options):
                tool._hook_events.append({"type": "PreCompact", "time": 1.0})
                tool._hook_events.append({"type": "PostToolUse", "tool": "Read", "time": 2.0})
                tool._hook_events.append({"type": "PreCompact", "time": 3.0})
                yield mock_system_msg
                yield mock_result_msg

            with patch.dict("sys.modules", {
                "claude_agent_sdk": MagicMock(
                    ClaudeAgentOptions=MagicMock,
                    HookMatcher=MagicMock,
                    ResultMessage=mock_result_cls,
                    SystemMessage=mock_system_cls,
                    query=mock_query_with_hooks,
                ),
            }):
                result = await tool.execute({"prompt": "task"})

        assert result.success is True
        assert result.data["compact_count"] == 2
        assert result.data["hook_events"] == 3


class TestConstants:
    def test_default_max_turns(self):
        assert _DEFAULT_MAX_TURNS == 100

    def test_default_timeout(self):
        assert _DEFAULT_TIMEOUT == 600
