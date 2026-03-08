"""Agent runtime — asyncio loop for LLM tool_use orchestration.

Handles the LLM call → tool_use → result → LLM cycle until stop or max rounds.
"""

from __future__ import annotations

import logging
import re
import time
import uuid
from dataclasses import dataclass, field

import litellm

from core.config import get_config
from core.constants import MAX_INPUT_LENGTH, MAX_TOOL_USE_ROUNDS
from core.memory import ContextPruner

logger = logging.getLogger(__name__)

# Unicode C0/C1 control characters to filter (keep \n \t \r)
_CONTROL_CHAR_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f-\x9f]")


@dataclass
class TokenUsage:
    """Token usage statistics."""

    input_tokens: int = 0
    output_tokens: int = 0


@dataclass
class ToolCallInfo:
    """Information about a tool call."""

    tool_name: str = ""
    tool_input: dict = field(default_factory=dict)
    tool_use_id: str = ""


@dataclass
class AgentResponse:
    """Unified agent response format (vendor-neutral)."""

    response_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    agent_id: str = ""
    session_id: str = ""
    model: str = ""
    content: str = ""
    finish_reason: str = ""  # stop | tool_use | max_tokens | error
    tool_calls: list[ToolCallInfo] = field(default_factory=list)
    usage: TokenUsage = field(default_factory=TokenUsage)
    latency_ms: int = 0


def sanitize_input(text: str) -> str:
    """Sanitize user input: filter control chars, truncate if too long.

    Args:
        text: Raw user input.

    Returns:
        Sanitized text.
    """
    # Filter C0/C1 control characters (keep \n, \t, \r)
    cleaned = _CONTROL_CHAR_RE.sub("", text)

    max_len = MAX_INPUT_LENGTH()
    if len(cleaned) > max_len:
        cleaned = cleaned[:max_len] + "\n[输入已截断]"

    return cleaned


class AgentRuntime:
    """Runs the LLM tool_use loop for an agent.

    Orchestrates: user input → LLM call → tool execution → result feedback → repeat.
    """

    def __init__(
        self,
        agent_id: str,
        model: str | None = None,
        system_prompt: str = "",
        tool_registry=None,
    ) -> None:
        self._agent_id = agent_id
        self._model = model or get_config().get("models", {}).get("default", "claude-sonnet-4-6")
        self._system_prompt = system_prompt
        self._tool_registry = tool_registry
        self._fallback_models = get_config().get("models", {}).get("fallback", [])

    async def run(self, user_input: str, session_id: str = "", messages: list | None = None) -> AgentResponse:
        """Run the agent loop: LLM call → tool_use → result → until stop.

        Args:
            user_input: The user's message (will be sanitized).
            session_id: Session identifier for tracking.
            messages: Optional pre-existing message history.

        Returns:
            Final AgentResponse after the loop completes.
        """
        sanitized = sanitize_input(user_input)
        session_id = session_id or str(uuid.uuid4())

        # Build message list
        msgs = list(messages) if messages else []
        if self._system_prompt and not any(m.get("role") == "system" for m in msgs):
            msgs.insert(0, {"role": "system", "content": self._system_prompt})
        msgs.append({"role": "user", "content": sanitized})

        # Get available tools for this agent
        tools_schema = self._get_tools_schema()

        max_rounds = MAX_TOOL_USE_ROUNDS()
        round_count = 0
        final_response = None

        while round_count < max_rounds:
            round_count += 1

            # Prune context before each LLM call
            # (ContextPruner works on ChatMessage, but here we use raw dicts for LiteLLM)

            start_time = time.time()
            response = await self._call_llm(msgs, tools_schema)
            latency_ms = int((time.time() - start_time) * 1000)

            final_response = AgentResponse(
                agent_id=self._agent_id,
                session_id=session_id,
                model=response.get("model", self._model),
                content=self._extract_text(response),
                finish_reason=response.get("finish_reason", "stop"),
                usage=TokenUsage(
                    input_tokens=response.get("usage", {}).get("prompt_tokens", 0),
                    output_tokens=response.get("usage", {}).get("completion_tokens", 0),
                ),
                latency_ms=latency_ms,
            )

            # Check if model wants to use tools
            tool_calls = response.get("tool_calls", [])
            if not tool_calls:
                final_response.finish_reason = "stop"
                break

            # Execute tool calls
            final_response.finish_reason = "tool_use"
            final_response.tool_calls = [
                ToolCallInfo(
                    tool_name=tc.get("function", {}).get("name", ""),
                    tool_input=tc.get("function", {}).get("arguments", {}),
                    tool_use_id=tc.get("id", ""),
                )
                for tc in tool_calls
            ]

            # Add assistant message with tool calls to history
            msgs.append(response.get("message", {"role": "assistant", "content": ""}))

            # Execute tools and add results
            for tc in tool_calls:
                tool_result = await self._execute_tool(tc)
                msgs.append({
                    "role": "tool",
                    "tool_call_id": tc.get("id", ""),
                    "content": tool_result,
                })

        if round_count >= max_rounds and final_response:
            final_response.finish_reason = "max_rounds"
            logger.warning("Agent %s hit max tool_use rounds (%d)", self._agent_id, max_rounds)

        return final_response or AgentResponse(
            agent_id=self._agent_id,
            session_id=session_id,
            content="No response generated",
            finish_reason="error",
        )

    async def _call_llm(self, messages: list[dict], tools: list[dict] | None = None) -> dict:
        """Call LLM with fallback chain.

        Tries the primary model first, then falls back to alternatives.
        """
        models_to_try = [self._model, *self._fallback_models]

        for model in models_to_try:
            try:
                kwargs = {"model": model, "messages": messages}
                if tools:
                    kwargs["tools"] = tools
                response = await litellm.acompletion(**kwargs)
                result = response.model_dump()
                choice = result.get("choices", [{}])[0]
                return {
                    "model": model,
                    "message": choice.get("message", {}),
                    "finish_reason": choice.get("finish_reason", "stop"),
                    "tool_calls": choice.get("message", {}).get("tool_calls", []),
                    "usage": result.get("usage", {}),
                }
            except Exception:
                logger.warning("Model %s failed, trying next fallback", model, exc_info=True)
                continue

        logger.error("All models failed for agent %s", self._agent_id)
        return {"finish_reason": "error", "message": {"role": "assistant", "content": "All models unavailable"}}

    async def _execute_tool(self, tool_call: dict) -> str:
        """Execute a single tool call via the tool registry."""
        tool_name = tool_call.get("function", {}).get("name", "")
        try:
            import json

            args_raw = tool_call.get("function", {}).get("arguments", "{}")
            args = json.loads(args_raw) if isinstance(args_raw, str) else args_raw
        except (json.JSONDecodeError, TypeError):
            return f"Error: Invalid tool arguments for {tool_name}"

        if not self._tool_registry:
            return f"Error: No tool registry configured for agent {self._agent_id}"

        try:
            tool = self._tool_registry.get_tool(tool_name, self._agent_id)
            result = await tool.execute(args)
            if result.success:
                return json.dumps(result.data) if result.data else "Success"
            return f"Error: {result.error}"
        except Exception as e:
            logger.warning("Tool %s execution failed: %s", tool_name, e)
            return f"Error executing {tool_name}: {e}"

    def _get_tools_schema(self) -> list[dict]:
        """Get tool schemas for LLM function calling."""
        if not self._tool_registry:
            return []

        tools = self._tool_registry.list_tools(self._agent_id)
        return [
            {
                "type": "function",
                "function": {
                    "name": t.name,
                    "description": t.description,
                    "parameters": t.input_schema,
                },
            }
            for t in tools
        ]

    @staticmethod
    def _extract_text(response: dict) -> str:
        """Extract text content from LLM response."""
        message = response.get("message", {})
        content = message.get("content", "")
        return content if isinstance(content, str) else ""
