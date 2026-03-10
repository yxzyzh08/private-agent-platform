"""Unit tests for core/session_rotation.py (Task 1B.5a)."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from core.session_rotation import (
    CONTINUATION_PROMPT,
    RotationConfig,
    RotationRecord,
    RotationResult,
    SessionRotator,
)
from tools.base import ToolResult


class TestRotationConfig:
    def test_defaults(self):
        config = RotationConfig()
        assert config.context_threshold == 0.80
        assert config.max_rotations == 3
        assert config.summary_max_tokens == 2000

    @patch("core.session_rotation.get_config")
    def test_from_config(self, mock_config):
        mock_config.return_value = {
            "session_rotation": {
                "context_threshold": 0.90,
                "max_rotations": 5,
                "summary_max_tokens": 3000,
            }
        }
        config = RotationConfig.from_config()
        assert config.context_threshold == 0.90
        assert config.max_rotations == 5
        assert config.summary_max_tokens == 3000

    @patch("core.session_rotation.get_config")
    def test_from_config_missing_section(self, mock_config):
        """Missing session_rotation section falls back to defaults."""
        mock_config.return_value = {}
        config = RotationConfig.from_config()
        assert config.max_rotations == 3


class TestRotationRecord:
    def test_creation(self):
        record = RotationRecord(rotation_number=1, reason="max_turns", summary="Did X")
        assert record.rotation_number == 1
        assert record.reason == "max_turns"
        assert record.summary == "Did X"


class TestSessionRotator:
    async def test_execute_no_rotation(self):
        """Task completes without needing rotation."""
        mock_tool = AsyncMock()
        mock_tool.execute.return_value = ToolResult(
            success=True,
            data={"result": "Task done", "needs_rotation": False},
        )

        rotator = SessionRotator(config=RotationConfig(max_rotations=3))
        result = await rotator.execute_with_rotation(
            tool=mock_tool,
            prompt="Fix the bug",
            working_directory="/tmp/repo",
        )

        assert result.success is True
        assert result.result == "Task done"
        assert result.total_rotations == 0
        assert len(result.rotations) == 0
        mock_tool.execute.assert_called_once()

    async def test_execute_single_rotation(self):
        """First attempt hits max_turns, second completes."""
        mock_tool = AsyncMock()
        mock_tool.execute.side_effect = [
            ToolResult(
                success=True,
                data={"result": "Partial work", "needs_rotation": True},
            ),
            ToolResult(
                success=True,
                data={"result": "All done", "needs_rotation": False},
            ),
        ]

        rotator = SessionRotator(config=RotationConfig(max_rotations=3))
        result = await rotator.execute_with_rotation(
            tool=mock_tool,
            prompt="Refactor auth",
        )

        assert result.success is True
        assert result.result == "All done"
        assert result.total_rotations == 1
        assert len(result.rotations) == 1
        assert result.rotations[0].reason == "max_turns"
        assert mock_tool.execute.call_count == 2

    async def test_execute_max_rotations_exceeded(self):
        """All attempts need rotation → exceeds max."""
        mock_tool = AsyncMock()
        mock_tool.execute.return_value = ToolResult(
            success=True,
            data={"result": "Still working", "needs_rotation": True},
        )

        config = RotationConfig(max_rotations=2)
        rotator = SessionRotator(config=config)
        result = await rotator.execute_with_rotation(
            tool=mock_tool,
            prompt="Complex task",
        )

        assert result.success is False
        assert "Max rotations (2) exceeded" in result.error
        assert result.total_rotations == 2
        # 3 calls: initial + 2 rotations, then 3rd iteration sees max exceeded
        assert mock_tool.execute.call_count == 3

    async def test_execute_tool_failure(self):
        """Tool execution fails on first attempt."""
        mock_tool = AsyncMock()
        mock_tool.execute.return_value = ToolResult(
            success=False,
            error="Connection failed",
        )

        rotator = SessionRotator()
        result = await rotator.execute_with_rotation(
            tool=mock_tool,
            prompt="task",
        )

        assert result.success is False
        assert "Connection failed" in result.error
        assert result.total_rotations == 0

    async def test_progress_summary_with_runtime(self):
        """Summary generation uses LLM runtime when available."""
        from core.agent_runtime import AgentResponse

        mock_runtime = AsyncMock()
        mock_runtime.run.return_value = AgentResponse(
            agent_id="test",
            content="Completed step 1 and 2. Remaining: step 3.",
            finish_reason="stop",
        )

        mock_tool = AsyncMock()
        mock_tool.execute.side_effect = [
            ToolResult(success=True, data={"result": "output", "needs_rotation": True}),
            ToolResult(success=True, data={"result": "done", "needs_rotation": False}),
        ]

        rotator = SessionRotator(
            config=RotationConfig(max_rotations=3),
            runtime=mock_runtime,
        )
        result = await rotator.execute_with_rotation(tool=mock_tool, prompt="task")

        assert result.success is True
        assert result.total_rotations == 1
        mock_runtime.run.assert_called_once()
        assert "Completed step 1" in result.rotations[0].summary

    async def test_progress_summary_fallback(self):
        """Without runtime, summary is truncated output."""
        mock_tool = AsyncMock()
        mock_tool.execute.side_effect = [
            ToolResult(success=True, data={"result": "x" * 3000, "needs_rotation": True}),
            ToolResult(success=True, data={"result": "done", "needs_rotation": False}),
        ]

        config = RotationConfig(summary_max_tokens=100)
        rotator = SessionRotator(config=config)
        result = await rotator.execute_with_rotation(tool=mock_tool, prompt="task")

        assert result.success is True
        assert len(result.rotations[0].summary) <= 120  # 100 + "...(truncated)"

    def test_continuation_prompt_format(self):
        """Continuation prompt includes original task and summary."""
        prompt = SessionRotator._build_continuation_prompt(
            original_prompt="Fix login bug",
            summary="Step 1 done, need to fix CSS",
        )

        assert "Fix login bug" in prompt
        assert "Step 1 done" in prompt
        assert "Continue" in prompt
        assert "NOT redo work" in prompt

    async def test_multiple_rotations(self):
        """Multiple rotations accumulate records correctly."""
        mock_tool = AsyncMock()
        mock_tool.execute.side_effect = [
            ToolResult(success=True, data={"result": "r1", "needs_rotation": True}),
            ToolResult(success=True, data={"result": "r2", "needs_rotation": True}),
            ToolResult(success=True, data={"result": "final", "needs_rotation": False}),
        ]

        config = RotationConfig(max_rotations=5)
        rotator = SessionRotator(config=config)
        result = await rotator.execute_with_rotation(tool=mock_tool, prompt="big task")

        assert result.success is True
        assert result.total_rotations == 2
        assert result.rotations[0].rotation_number == 1
        assert result.rotations[1].rotation_number == 2
