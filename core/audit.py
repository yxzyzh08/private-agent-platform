"""Audit logging and sensitive data redaction.

Records all tool calls with sanitized parameters.
"""

from __future__ import annotations

import re
from datetime import datetime, timezone

from core.logging import get_logger

logger = get_logger(__name__)

# Patterns to detect sensitive data for redaction
_SENSITIVE_PATTERNS = [
    # API keys: sk-ant-..., sk-..., ghp_..., gho_..., etc.
    (re.compile(r"(sk-ant-[a-zA-Z0-9]{4})[a-zA-Z0-9-]+"), r"\1****"),
    (re.compile(r"(sk-[a-zA-Z0-9]{4})[a-zA-Z0-9-]+"), r"\1****"),
    (re.compile(r"(ghp_[a-zA-Z0-9]{4})[a-zA-Z0-9]+"), r"\1****"),
    (re.compile(r"(gho_[a-zA-Z0-9]{4})[a-zA-Z0-9]+"), r"\1****"),
    (re.compile(r"(ghs_[a-zA-Z0-9]{4})[a-zA-Z0-9]+"), r"\1****"),
    # Bearer tokens
    (re.compile(r"(Bearer\s+[a-zA-Z0-9]{4})[a-zA-Z0-9._-]+"), r"\1****"),
    # Generic long hex/base64 strings that look like tokens (32+ chars)
    (re.compile(r"([a-fA-F0-9]{8})[a-fA-F0-9]{24,}"), r"\1****"),
]


def redact(text: str) -> str:
    """Redact sensitive information from text.

    Replaces API keys, tokens, and other sensitive patterns
    with truncated versions (prefix + ****).

    Args:
        text: Text that may contain sensitive data.

    Returns:
        Text with sensitive data redacted.
    """
    result = text
    for pattern, replacement in _SENSITIVE_PATTERNS:
        result = pattern.sub(replacement, result)
    return result


def log_tool_call(
    agent_id: str,
    tool_name: str,
    params: dict,
    result_status: str,
    duration_ms: int = 0,
) -> None:
    """Record a tool call in the audit log.

    All parameter values are redacted before logging.

    Args:
        agent_id: The agent that made the call.
        tool_name: Name of the tool called.
        params: Tool parameters (will be redacted).
        result_status: "success" or "error".
        duration_ms: Execution duration in milliseconds.
    """
    # Create a summary of params (redacted)
    param_summary = _summarize_params(params)

    logger.info(
        "AUDIT: agent=%s tool=%s params=%s status=%s duration_ms=%d",
        agent_id,
        tool_name,
        param_summary,
        result_status,
        duration_ms,
    )


def _summarize_params(params: dict, max_value_len: int = 100) -> dict:
    """Create a redacted summary of parameters.

    Args:
        params: The parameters to summarize.
        max_value_len: Maximum length for string values.

    Returns:
        Summarized and redacted parameter dict.
    """
    summary = {}
    for key, value in params.items():
        if isinstance(value, str):
            # Truncate long strings
            truncated = value[:max_value_len] + "..." if len(value) > max_value_len else value
            summary[key] = redact(truncated)
        elif isinstance(value, dict):
            summary[key] = "{...}"
        elif isinstance(value, list):
            summary[key] = f"[{len(value)} items]"
        else:
            summary[key] = str(value)
    return summary
