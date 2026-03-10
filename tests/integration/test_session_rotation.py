"""Integration tests for session rotation (Task 1B.6a).

Tests the interaction between SessionRotator, CLI/SDK tools, and DevAgent's
complexity-adaptive execution. All external calls are mocked.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from core.session_rotation import (
    RotationConfig,
    RotationResult,
    SessionRotator,
)
from tools.base import ToolResult


# ---------------------------------------------------------------------------
# 1. SDK Hooks trigger rotation
# ---------------------------------------------------------------------------


class TestSDKHooksRotation:
    """Verify that SDK hook events integrate with rotation tracking."""

    async def test_precompact_hook_triggers_rotation_awareness(self):
        """PreCompact events are recorded and contribute to rotation decision."""
        mock_tool = AsyncMock()
        # First call: needs rotation, second: completes
        mock_tool.execute.side_effect = [
            ToolResult(
                success=True,
                data={
                    "result": "Partial",
                    "needs_rotation": True,
                    "compact_count": 2,
                    "hook_events": 3,
                },
            ),
            ToolResult(
                success=True,
                data={
                    "result": "Done",
                    "needs_rotation": False,
                    "compact_count": 0,
                    "hook_events": 1,
                },
            ),
        ]

        rotator = SessionRotator(config=RotationConfig(max_rotations=3))
        result = await rotator.execute_with_rotation(
            tool=mock_tool,
            prompt="Refactor the auth module",
            max_turns=100,
        )

        assert result.success is True
        assert result.total_rotations == 1
        assert result.rotations[0].reason == "max_turns"
        # Second call should have continuation prompt
        second_call_prompt = mock_tool.execute.call_args_list[1].args[0]["prompt"]
        assert "Continue" in second_call_prompt
        assert "Refactor the auth module" in second_call_prompt

    async def test_sdk_hook_events_preserved_across_rotations(self):
        """Hook event data in tool results is accessible for each rotation."""
        mock_tool = AsyncMock()
        mock_tool.execute.side_effect = [
            ToolResult(
                success=True,
                data={
                    "result": "Step 1 done",
                    "needs_rotation": True,
                    "compact_count": 1,
                    "hook_events": 5,
                },
            ),
            ToolResult(
                success=True,
                data={
                    "result": "Step 2 done",
                    "needs_rotation": True,
                    "compact_count": 0,
                    "hook_events": 2,
                },
            ),
            ToolResult(
                success=True,
                data={
                    "result": "All done",
                    "needs_rotation": False,
                    "compact_count": 0,
                    "hook_events": 1,
                },
            ),
        ]

        rotator = SessionRotator(config=RotationConfig(max_rotations=5))
        result = await rotator.execute_with_rotation(
            tool=mock_tool, prompt="Complex refactor"
        )

        assert result.success is True
        assert result.total_rotations == 2
        assert len(result.rotations) == 2
        assert result.rotations[0].rotation_number == 1
        assert result.rotations[1].rotation_number == 2


# ---------------------------------------------------------------------------
# 2. Subprocess (CLI) result detection → rotation
# ---------------------------------------------------------------------------


class TestSubprocessRotation:
    """Test rotation triggered by CLI tool returning max_turns stop."""

    async def test_cli_max_turns_triggers_rotation(self):
        """CLI returning needs_rotation=True triggers summary → continuation."""
        mock_tool = AsyncMock()
        mock_tool.execute.side_effect = [
            ToolResult(
                success=True,
                data={
                    "result": "Fixed 3 of 5 files",
                    "needs_rotation": True,
                    "stop_reason": "error_max_turns",
                },
            ),
            ToolResult(
                success=True,
                data={
                    "result": "All 5 files fixed, tests pass",
                    "needs_rotation": False,
                    "stop_reason": "end_turn",
                },
            ),
        ]

        rotator = SessionRotator(config=RotationConfig(max_rotations=3))
        result = await rotator.execute_with_rotation(
            tool=mock_tool,
            prompt="Fix all linting errors in src/",
            working_directory="/home/user/repo",
        )

        assert result.success is True
        assert result.result == "All 5 files fixed, tests pass"
        assert result.total_rotations == 1

        # Verify continuation prompt was built correctly
        second_prompt = mock_tool.execute.call_args_list[1].args[0]["prompt"]
        assert "Fix all linting errors" in second_prompt
        assert "Fixed 3 of 5 files" in second_prompt

    async def test_cli_with_runtime_summary(self):
        """CLI rotation uses LLM runtime for summary when available."""
        from core.agent_runtime import AgentResponse

        mock_runtime = AsyncMock()
        mock_runtime.run.return_value = AgentResponse(
            agent_id="summarizer",
            content="Completed: auth refactor. Remaining: test updates and docs.",
            finish_reason="stop",
        )

        mock_tool = AsyncMock()
        mock_tool.execute.side_effect = [
            ToolResult(success=True, data={"result": "WIP output", "needs_rotation": True}),
            ToolResult(success=True, data={"result": "Done", "needs_rotation": False}),
        ]

        rotator = SessionRotator(
            config=RotationConfig(max_rotations=3),
            runtime=mock_runtime,
        )
        result = await rotator.execute_with_rotation(
            tool=mock_tool, prompt="Refactor auth and update tests"
        )

        assert result.success is True
        mock_runtime.run.assert_called_once()
        assert "auth refactor" in result.rotations[0].summary

    async def test_cli_failure_no_rotation(self):
        """CLI failure returns immediately without attempting rotation."""
        mock_tool = AsyncMock()
        mock_tool.execute.return_value = ToolResult(
            success=False,
            error="git clone failed: permission denied",
        )

        rotator = SessionRotator(config=RotationConfig(max_rotations=3))
        result = await rotator.execute_with_rotation(
            tool=mock_tool, prompt="Clone and fix"
        )

        assert result.success is False
        assert "permission denied" in result.error
        assert result.total_rotations == 0
        mock_tool.execute.assert_called_once()


# ---------------------------------------------------------------------------
# 3. Complexity-adaptive routing
# ---------------------------------------------------------------------------


class TestComplexityAdaptiveRouting:
    """Test that complexity level determines execution parameters."""

    async def test_simple_issue_single_call(self):
        """Simple issues use low max_turns and complete in one session."""
        mock_tool = AsyncMock()
        mock_tool.execute.return_value = ToolResult(
            success=True,
            data={"result": "Typo fixed", "needs_rotation": False},
        )

        rotator = SessionRotator(config=RotationConfig(max_rotations=3))
        result = await rotator.execute_with_rotation(
            tool=mock_tool,
            prompt="Fix typo in README",
            max_turns=100,  # simple complexity
        )

        assert result.success is True
        assert result.total_rotations == 0
        call_params = mock_tool.execute.call_args.args[0]
        assert call_params["max_turns"] == 100

    async def test_complex_issue_uses_rotation(self):
        """Complex issues may trigger rotation when hitting max_turns."""
        mock_tool = AsyncMock()
        mock_tool.execute.side_effect = [
            ToolResult(success=True, data={"result": "Phase 1 done", "needs_rotation": True}),
            ToolResult(success=True, data={"result": "Phase 2 done", "needs_rotation": True}),
            ToolResult(success=True, data={"result": "Complete", "needs_rotation": False}),
        ]

        rotator = SessionRotator(config=RotationConfig(max_rotations=5))
        result = await rotator.execute_with_rotation(
            tool=mock_tool,
            prompt="Full architecture refactor",
            max_turns=200,  # complex complexity
        )

        assert result.success is True
        assert result.total_rotations == 2
        # All calls should use the same max_turns
        for call in mock_tool.execute.call_args_list:
            assert call.args[0]["max_turns"] == 200

    async def test_medium_complexity_single_rotation(self):
        """Medium complexity may need one rotation."""
        mock_tool = AsyncMock()
        mock_tool.execute.side_effect = [
            ToolResult(success=True, data={"result": "Halfway", "needs_rotation": True}),
            ToolResult(success=True, data={"result": "Done", "needs_rotation": False}),
        ]

        rotator = SessionRotator(config=RotationConfig(max_rotations=3))
        result = await rotator.execute_with_rotation(
            tool=mock_tool,
            prompt="Add validation to 3 endpoints",
            max_turns=150,  # medium complexity
        )

        assert result.success is True
        assert result.total_rotations == 1


# ---------------------------------------------------------------------------
# 4. Multi-rotation count and limits
# ---------------------------------------------------------------------------


class TestMultiRotationLimits:
    """Test rotation counting and maximum enforcement."""

    async def test_rotation_count_tracks_correctly(self):
        """Rotation records accumulate with correct numbering."""
        mock_tool = AsyncMock()
        mock_tool.execute.side_effect = [
            ToolResult(success=True, data={"result": "r1", "needs_rotation": True}),
            ToolResult(success=True, data={"result": "r2", "needs_rotation": True}),
            ToolResult(success=True, data={"result": "r3", "needs_rotation": True}),
            ToolResult(success=True, data={"result": "final", "needs_rotation": False}),
        ]

        config = RotationConfig(max_rotations=5)
        rotator = SessionRotator(config=config)
        result = await rotator.execute_with_rotation(tool=mock_tool, prompt="big task")

        assert result.success is True
        assert result.total_rotations == 3
        assert [r.rotation_number for r in result.rotations] == [1, 2, 3]
        assert all(r.reason == "max_turns" for r in result.rotations)

    async def test_max_rotations_enforced(self):
        """Exceeding max_rotations returns failure."""
        mock_tool = AsyncMock()
        mock_tool.execute.return_value = ToolResult(
            success=True,
            data={"result": "Still working...", "needs_rotation": True},
        )

        config = RotationConfig(max_rotations=2)
        rotator = SessionRotator(config=config)
        result = await rotator.execute_with_rotation(tool=mock_tool, prompt="infinite task")

        assert result.success is False
        assert "Max rotations (2) exceeded" in result.error
        assert result.total_rotations == 2
        # initial + 2 rotations + final attempt that exceeds
        assert mock_tool.execute.call_count == 3

    async def test_rotation_summaries_chain_correctly(self):
        """Each rotation's continuation prompt includes the latest summary."""
        mock_tool = AsyncMock()
        mock_tool.execute.side_effect = [
            ToolResult(success=True, data={"result": "Added auth middleware", "needs_rotation": True}),
            ToolResult(success=True, data={"result": "Added route guards", "needs_rotation": True}),
            ToolResult(success=True, data={"result": "All done", "needs_rotation": False}),
        ]

        rotator = SessionRotator(config=RotationConfig(max_rotations=5))
        result = await rotator.execute_with_rotation(
            tool=mock_tool, prompt="Implement auth system"
        )

        assert result.success is True
        # Second call should contain summary of first output
        second_prompt = mock_tool.execute.call_args_list[1].args[0]["prompt"]
        assert "auth middleware" in second_prompt
        # Third call should contain summary of second output
        third_prompt = mock_tool.execute.call_args_list[2].args[0]["prompt"]
        assert "route guards" in third_prompt

    async def test_zero_max_rotations_no_retry(self):
        """With max_rotations=0, first max_turns hit fails immediately."""
        mock_tool = AsyncMock()
        mock_tool.execute.return_value = ToolResult(
            success=True,
            data={"result": "Incomplete", "needs_rotation": True},
        )

        config = RotationConfig(max_rotations=0)
        rotator = SessionRotator(config=config)
        result = await rotator.execute_with_rotation(tool=mock_tool, prompt="task")

        assert result.success is False
        assert "Max rotations (0) exceeded" in result.error
        assert result.total_rotations == 0
        mock_tool.execute.assert_called_once()
