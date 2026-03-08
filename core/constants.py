"""Platform constants.

Default values can be overridden by config/platform.yaml via core.config.
"""

from __future__ import annotations

from core.config import get_config

# --- Defaults (used when config is not loaded or key is missing) ---

_DEFAULT_MAX_MESSAGE_LENGTH = 4096
_DEFAULT_RATE_LIMIT_PER_MINUTE = 10
_DEFAULT_MODEL = "claude-sonnet-4-6"
_DEFAULT_MAX_CONTEXT_TOKENS = 180_000
_DEFAULT_MAX_TOOL_USE_ROUNDS = 10
_DEFAULT_MAX_INPUT_LENGTH = 16_000
_CONTEXT_ROUND_DEFINITION = "user+assistant pair"


def _get(section: str, key: str, default: object) -> object:
    """Retrieve a config value with fallback to default."""
    try:
        cfg = get_config()
        return cfg.get(section, {}).get(key, default)
    except Exception:
        return default


# --- Public constants (resolved at access time via properties) ---
# For hot-reload friendliness, these are functions, not module-level values.


def MAX_MESSAGE_LENGTH() -> int:
    return int(_get("platform", "max_message_length", _DEFAULT_MAX_MESSAGE_LENGTH))


def RATE_LIMIT_PER_MINUTE() -> int:
    return int(_get("security", "rate_limit_per_minute", _DEFAULT_RATE_LIMIT_PER_MINUTE))


def DEFAULT_MODEL() -> str:
    return str(_get("models", "default", _DEFAULT_MODEL))


def MAX_CONTEXT_TOKENS() -> int:
    return int(_get("platform", "max_context_tokens", _DEFAULT_MAX_CONTEXT_TOKENS))


def MAX_TOOL_USE_ROUNDS() -> int:
    return int(_get("platform", "max_tool_use_rounds", _DEFAULT_MAX_TOOL_USE_ROUNDS))


def MAX_INPUT_LENGTH() -> int:
    return int(_get("platform", "max_input_length", _DEFAULT_MAX_INPUT_LENGTH))


CONTEXT_ROUND_DEFINITION: str = _CONTEXT_ROUND_DEFINITION
