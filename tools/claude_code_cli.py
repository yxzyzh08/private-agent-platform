"""Claude Code CLI tool — async subprocess wrapper.

Spawns a Claude Code CLI subprocess with JSON output mode.
Used by Phase 1B GitHub Issue automation.
"""

from __future__ import annotations

import asyncio
import json
import os
import time

from core.audit import log_tool_call
from tools.base import BaseTool, ToolResult

_DEFAULT_TIMEOUT = 600  # 10 minutes
_SENSITIVE_ENV_VARS = ("ANTHROPIC_API_KEY", "OPENAI_API_KEY", "GITHUB_TOKEN")


class ClaudeCodeCliTool(BaseTool):
    """Execute tasks via Claude Code CLI subprocess."""

    name = "claude_code_cli"
    description = "Run a development task using Claude Code CLI subprocess"
    input_schema = {
        "type": "object",
        "properties": {
            "prompt": {
                "type": "string",
                "description": "The task prompt to send to Claude Code",
            },
            "working_directory": {
                "type": "string",
                "description": "Working directory for the CLI process",
            },
            "timeout": {
                "type": "integer",
                "description": f"Timeout in seconds (default: {_DEFAULT_TIMEOUT})",
            },
        },
        "required": ["prompt"],
    }

    async def execute(self, params: dict) -> ToolResult:
        """Execute Claude Code CLI as an async subprocess.

        Args:
            params: Must contain 'prompt', optionally 'working_directory' and 'timeout'.

        Returns:
            ToolResult with CLI output or error details.
        """
        await self.validate_input(params)
        start_time = time.monotonic()
        result = await self._execute_cli(params)
        duration_ms = int((time.monotonic() - start_time) * 1000)
        log_tool_call(
            agent_id="unknown",
            tool_name=self.name,
            params=params,
            result_status="success" if result.success else "error",
            duration_ms=duration_ms,
        )
        return result

    async def _execute_cli(self, params: dict) -> ToolResult:
        """Internal CLI execution logic."""
        prompt = params["prompt"]
        cwd = params.get("working_directory", ".")
        timeout = params.get("timeout", _DEFAULT_TIMEOUT)

        # Build safe environment: remove sensitive vars
        env = {k: v for k, v in os.environ.items() if k not in _SENSITIVE_ENV_VARS}

        cmd = [
            "claude",
            "--output-format",
            "json",
            "--permission-mode",
            "dontAsk",
            "-p",
            prompt,
        ]

        try:
            process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=cwd,
                env=env,
            )

            try:
                stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=timeout)
            except asyncio.TimeoutError:
                process.kill()
                await process.wait()
                return ToolResult(
                    success=False,
                    error=f"Claude Code CLI timed out after {timeout}s and was terminated",
                )

            stdout_text = stdout.decode("utf-8", errors="replace")
            stderr_text = stderr.decode("utf-8", errors="replace")

            if process.returncode != 0:
                return ToolResult(
                    success=False,
                    error=f"CLI exited with code {process.returncode}: {stderr_text[:1000]}",
                )

            # Try to parse JSON output
            try:
                output = json.loads(stdout_text)
            except json.JSONDecodeError:
                output = {"raw_output": stdout_text[:5000]}

            return ToolResult(success=True, data=output)

        except FileNotFoundError:
            return ToolResult(
                success=False,
                error="Claude Code CLI binary not found. Ensure 'claude' is in PATH.",
            )
        except OSError as e:
            return ToolResult(success=False, error=f"Failed to start CLI process: {e}")
