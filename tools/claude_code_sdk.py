"""Claude Agent SDK tool — programmatic Claude Code execution.

Uses the official claude-agent-sdk package to run development tasks.
Supports Hooks (PreCompact, Stop, PostToolUse) and returns structured results.
Configurable as alternative backend to claude_code_cli via config cli.backend.
"""

from __future__ import annotations

import time

from core.audit import log_tool_call
from tools.base import BaseTool, ToolResult

_DEFAULT_MAX_TURNS = 100
_DEFAULT_TIMEOUT = 600  # 10 minutes


class ClaudeCodeSDKTool(BaseTool):
    """Execute tasks via Claude Agent SDK (programmatic API).

    Alternative to ClaudeCodeCliTool — uses the SDK's query() function
    instead of subprocess. Supports Hooks for lifecycle events and
    returns structured results including session_id and usage stats.
    """

    name = "claude_code_sdk"
    description = "Run a development task using Claude Agent SDK (programmatic)"
    input_schema = {
        "type": "object",
        "properties": {
            "prompt": {
                "type": "string",
                "description": "The task prompt to send to Claude Code",
            },
            "working_directory": {
                "type": "string",
                "description": "Working directory for file operations",
            },
            "max_turns": {
                "type": "integer",
                "description": f"Maximum agent turns (default: {_DEFAULT_MAX_TURNS})",
            },
            "allowed_tools": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Tools the agent can use (e.g., ['Read', 'Edit', 'Bash'])",
            },
        },
        "required": ["prompt"],
    }

    def __init__(self) -> None:
        super().__init__()
        self._hook_events: list[dict] = []

    async def execute(self, params: dict) -> ToolResult:
        """Execute a task via Claude Agent SDK.

        Args:
            params: Must contain 'prompt'. Optional: 'working_directory',
                     'max_turns', 'allowed_tools'.

        Returns:
            ToolResult with structured data including session_id, result,
            num_turns, cost_usd, compact_count, and needs_rotation.
        """
        await self.validate_input(params)

        prompt = params["prompt"]
        cwd = params.get("working_directory", ".")
        max_turns = params.get("max_turns", _DEFAULT_MAX_TURNS)
        allowed_tools = params.get("allowed_tools", ["Read", "Edit", "Write", "Bash", "Glob", "Grep"])

        self._hook_events = []
        start_time = time.monotonic()

        try:
            from claude_agent_sdk import (
                ClaudeAgentOptions,
                HookMatcher,
                ResultMessage,
                SystemMessage,
            )

            import asyncio

            # Build hooks for lifecycle tracking
            hooks = self._build_hooks(HookMatcher)

            options = ClaudeAgentOptions(
                cwd=cwd,
                allowed_tools=allowed_tools,
                max_turns=max_turns,
                permission_mode="bypassPermissions",
                allow_dangerously_skip_permissions=True,
                hooks=hooks,
            )

            session_id = None
            result_text = ""
            stop_reason = ""
            num_turns = 0
            start_time = time.monotonic()

            from claude_agent_sdk import query

            async for message in query(prompt=prompt, options=options):
                if isinstance(message, SystemMessage) and message.subtype == "init":
                    session_id = message.session_id
                elif isinstance(message, ResultMessage):
                    result_text = message.result
                    stop_reason = getattr(message, "stop_reason", "end_turn")

            duration_ms = int((time.monotonic() - start_time) * 1000)
            compact_count = sum(1 for e in self._hook_events if e.get("type") == "PreCompact")
            needs_rotation = stop_reason == "max_turns"

            result = ToolResult(
                success=True,
                data={
                    "session_id": session_id,
                    "result": result_text,
                    "stop_reason": stop_reason,
                    "num_turns": max_turns if needs_rotation else num_turns,
                    "compact_count": compact_count,
                    "needs_rotation": needs_rotation,
                    "duration_ms": duration_ms,
                    "hook_events": len(self._hook_events),
                },
            )
            log_tool_call("unknown", self.name, params, "success", duration_ms)
            return result

        except ImportError:
            duration_ms = int((time.monotonic() - start_time) * 1000)
            log_tool_call("unknown", self.name, params, "error", duration_ms)
            return ToolResult(
                success=False,
                error="claude-agent-sdk not installed. Run: pip install claude-agent-sdk",
            )
        except Exception as e:
            duration_ms = int((time.monotonic() - start_time) * 1000)
            log_tool_call("unknown", self.name, params, "error", duration_ms)
            return ToolResult(
                success=False,
                error=f"SDK execution failed: {type(e).__name__}: {e}",
            )

    def _build_hooks(self, HookMatcher) -> dict:
        """Build hook configuration for lifecycle event tracking."""

        async def on_pre_compact(input_data, tool_use_id, context):
            self._hook_events.append({"type": "PreCompact", "time": time.time()})
            return {}

        async def on_stop(input_data, tool_use_id, context):
            self._hook_events.append({"type": "Stop", "time": time.time()})
            return {}

        async def on_post_tool_use(input_data, tool_use_id, context):
            tool_name = input_data.get("tool_input", {}).get("name", "unknown")
            self._hook_events.append({
                "type": "PostToolUse",
                "tool": tool_name,
                "time": time.time(),
            })
            return {}

        return {
            "PreCompact": [HookMatcher(matcher=".*", hooks=[on_pre_compact])],
            "Stop": [HookMatcher(matcher=".*", hooks=[on_stop])],
            "PostToolUse": [HookMatcher(matcher=".*", hooks=[on_post_tool_use])],
        }
