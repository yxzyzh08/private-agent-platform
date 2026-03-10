"""Session rotation — handles context exhaustion during long tasks.

When a Claude Code session hits max_turns, the SessionRotator generates
a progress summary via LLM, builds a continuation prompt, and starts
a new session to resume the work.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from core.config import get_config
from core.logging import get_logger

logger = get_logger(__name__)

# Default config values
_DEFAULT_CONTEXT_THRESHOLD = 0.80
_DEFAULT_MAX_ROTATIONS = 3
_DEFAULT_SUMMARY_MAX_TOKENS = 2000

SUMMARY_PROMPT = """Summarize the progress so far for this task.

Original task:
{original_prompt}

Output from the session:
{session_output}

Provide a concise summary containing:
1. What has been completed
2. What remains to be done
3. Any important context for continuing

Respond in plain text, not JSON."""

CONTINUATION_PROMPT = """Continue the following task. A previous session was interrupted.

## Original Task
{original_prompt}

## Progress Summary
{summary}

## Instructions
- Pick up where the previous session left off
- Do NOT redo work that is already completed
- Focus on the remaining items listed above
"""


@dataclass
class RotationConfig:
    """Configuration for session rotation behavior."""

    context_threshold: float = _DEFAULT_CONTEXT_THRESHOLD
    max_rotations: int = _DEFAULT_MAX_ROTATIONS
    summary_max_tokens: int = _DEFAULT_SUMMARY_MAX_TOKENS

    @classmethod
    def from_config(cls) -> RotationConfig:
        """Load rotation config from platform.yaml."""
        config = get_config()
        section = config.get("session_rotation", {})
        return cls(
            context_threshold=section.get("context_threshold", _DEFAULT_CONTEXT_THRESHOLD),
            max_rotations=section.get("max_rotations", _DEFAULT_MAX_ROTATIONS),
            summary_max_tokens=section.get("summary_max_tokens", _DEFAULT_SUMMARY_MAX_TOKENS),
        )


@dataclass
class RotationRecord:
    """Record of a single rotation event."""

    rotation_number: int
    reason: str
    summary: str


@dataclass
class RotationResult:
    """Result of execute_with_rotation."""

    success: bool
    result: str = ""
    rotations: list[RotationRecord] = field(default_factory=list)
    error: str = ""
    total_rotations: int = 0


class SessionRotator:
    """Manages session rotation for long-running tasks.

    Wraps CLI/SDK execution with rotation logic: if a session ends
    due to max_turns, it generates a progress summary and starts
    a new session with a continuation prompt.
    """

    def __init__(
        self,
        config: RotationConfig | None = None,
        runtime: Any = None,
    ) -> None:
        self._config = config or RotationConfig()
        self._runtime = runtime

    async def execute_with_rotation(
        self,
        tool: Any,
        prompt: str,
        working_directory: str = ".",
        max_turns: int = 100,
    ) -> RotationResult:
        """Execute a task with automatic session rotation on max_turns.

        Args:
            tool: A BaseTool instance (claude_code_cli or claude_code_sdk).
            prompt: The original task prompt.
            working_directory: Working directory for execution.
            max_turns: Max turns per session.

        Returns:
            RotationResult with final output and rotation records.
        """
        current_prompt = prompt
        rotations: list[RotationRecord] = []

        for rotation_num in range(self._config.max_rotations + 1):
            logger.info(
                "Session rotation: attempt %d/%d",
                rotation_num,
                self._config.max_rotations,
            )

            result = await tool.execute({
                "prompt": current_prompt,
                "working_directory": working_directory,
                "max_turns": max_turns,
            })

            if not result.success:
                return RotationResult(
                    success=False,
                    error=result.error or "Tool execution failed",
                    rotations=rotations,
                    total_rotations=len(rotations),
                )

            needs_rotation = result.data and result.data.get("needs_rotation", False)
            session_output = (result.data or {}).get("result", "")

            if not needs_rotation:
                # Task completed successfully — no rotation needed
                return RotationResult(
                    success=True,
                    result=session_output,
                    rotations=rotations,
                    total_rotations=len(rotations),
                )

            # Check if we've hit max rotations
            if rotation_num >= self._config.max_rotations:
                logger.warning(
                    "Max rotations (%d) exceeded", self._config.max_rotations
                )
                return RotationResult(
                    success=False,
                    result=session_output,
                    error=f"Max rotations ({self._config.max_rotations}) exceeded",
                    rotations=rotations,
                    total_rotations=len(rotations),
                )

            # Generate progress summary
            summary = await self._generate_summary(prompt, session_output)

            record = RotationRecord(
                rotation_number=rotation_num + 1,
                reason="max_turns",
                summary=summary,
            )
            rotations.append(record)
            logger.info("Rotation %d: %s", record.rotation_number, record.reason)

            # Build continuation prompt
            current_prompt = self._build_continuation_prompt(prompt, summary)

        # Should not reach here, but defensive
        return RotationResult(
            success=False,
            error="Unexpected end of rotation loop",
            rotations=rotations,
            total_rotations=len(rotations),
        )

    async def _generate_summary(self, original_prompt: str, session_output: str) -> str:
        """Generate a progress summary via LLM runtime.

        Falls back to a simple truncation if no runtime is available.
        """
        if self._runtime:
            from core.agent_runtime import AgentResponse

            summary_prompt = SUMMARY_PROMPT.format(
                original_prompt=original_prompt,
                session_output=session_output[:self._config.summary_max_tokens],
            )
            response: AgentResponse = await self._runtime.run(user_input=summary_prompt)
            return response.content

        # Fallback: use truncated output as summary
        max_len = self._config.summary_max_tokens
        if len(session_output) > max_len:
            return session_output[:max_len] + "\n...(truncated)"
        return session_output

    @staticmethod
    def _build_continuation_prompt(original_prompt: str, summary: str) -> str:
        """Build a continuation prompt for the next session."""
        return CONTINUATION_PROMPT.format(
            original_prompt=original_prompt,
            summary=summary,
        )
