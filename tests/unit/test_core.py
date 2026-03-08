"""Unit tests for core modules."""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest
import yaml

from core.config import ConfigError, get_config, load_config, reset_config
from core.constants import (
    CONTEXT_ROUND_DEFINITION,
    DEFAULT_MODEL,
    MAX_CONTEXT_TOKENS,
    MAX_INPUT_LENGTH,
    MAX_MESSAGE_LENGTH,
    MAX_TOOL_USE_ROUNDS,
    RATE_LIMIT_PER_MINUTE,
)
from core.errors import (
    ChannelError,
    PermissionDeniedError,
    PlatformError,
    RateLimitError,
    ToolError,
    ValidationError,
)


# --- core/config.py tests ---


class TestConfig:
    def setup_method(self):
        reset_config()

    def teardown_method(self):
        reset_config()

    def test_config_load_default(self):
        config = load_config()
        assert config["platform"]["name"] == "My Agent Platform"

    def test_config_load_custom_path(self, tmp_path):
        custom = tmp_path / "test.yaml"
        custom.write_text(yaml.dump({"platform": {"name": "Test"}}))
        config = load_config(custom)
        assert config["platform"]["name"] == "Test"

    def test_config_file_not_found(self):
        with pytest.raises(ConfigError, match="not found"):
            load_config("/nonexistent/path.yaml")

    def test_config_invalid_yaml(self, tmp_path):
        bad = tmp_path / "bad.yaml"
        bad.write_text("{{invalid yaml")
        with pytest.raises(ConfigError, match="Invalid YAML"):
            load_config(bad)

    def test_config_not_mapping(self, tmp_path):
        bad = tmp_path / "list.yaml"
        bad.write_text("- item1\n- item2")
        with pytest.raises(ConfigError, match="must be a YAML mapping"):
            load_config(bad)

    def test_config_singleton(self):
        c1 = get_config()
        c2 = get_config()
        assert c1 is c2

    def test_config_reset(self):
        c1 = get_config()
        reset_config()
        c2 = get_config()
        assert c1 is not c2

    def test_config_has_required_sections(self):
        config = load_config()
        for section in ["platform", "models", "security", "storage", "channels"]:
            assert section in config, f"Missing section: {section}"

    def test_config_models_default(self):
        config = load_config()
        assert config["models"]["default"] == "claude-sonnet-4-6"
        assert isinstance(config["models"]["fallback"], list)

    def test_config_dispatch_routes(self):
        config = load_config()
        assert "dispatch" in config
        assert "routes" in config["dispatch"]
        assert len(config["dispatch"]["routes"]) > 0

    def test_config_cui_section(self):
        config = load_config()
        assert "cui" in config
        assert "host" in config["cui"]
        assert "port" in config["cui"]


# --- core/errors.py tests ---


class TestErrors:
    def test_platform_error_is_exception(self):
        assert issubclass(PlatformError, Exception)

    def test_tool_error_inherits_platform(self):
        assert issubclass(ToolError, PlatformError)

    def test_channel_error_inherits_platform(self):
        assert issubclass(ChannelError, PlatformError)

    def test_permission_denied_inherits_platform(self):
        assert issubclass(PermissionDeniedError, PlatformError)

    def test_rate_limit_inherits_platform(self):
        assert issubclass(RateLimitError, PlatformError)

    def test_validation_error_inherits_platform(self):
        assert issubclass(ValidationError, PlatformError)

    def test_error_message(self):
        err = ToolError("something broke")
        assert str(err) == "something broke"


# --- core/constants.py tests ---


class TestConstants:
    def setup_method(self):
        reset_config()

    def teardown_method(self):
        reset_config()

    def test_rate_limit_default(self):
        assert RATE_LIMIT_PER_MINUTE() == 10

    def test_default_model(self):
        assert DEFAULT_MODEL() == "claude-sonnet-4-6"

    def test_max_message_length(self):
        assert MAX_MESSAGE_LENGTH() > 0

    def test_max_context_tokens(self):
        assert MAX_CONTEXT_TOKENS() == 180_000

    def test_max_tool_use_rounds(self):
        assert MAX_TOOL_USE_ROUNDS() == 10

    def test_max_input_length(self):
        assert MAX_INPUT_LENGTH() == 16_000

    def test_context_round_definition(self):
        assert CONTEXT_ROUND_DEFINITION == "user+assistant pair"

    def test_constants_respect_config_override(self, tmp_path):
        custom = tmp_path / "override.yaml"
        custom.write_text(
            yaml.dump(
                {
                    "platform": {"name": "Test"},
                    "security": {"rate_limit_per_minute": 20},
                    "models": {"default": "gpt-4o"},
                }
            )
        )
        reset_config()
        load_config(custom)
        assert RATE_LIMIT_PER_MINUTE() == 20
        assert DEFAULT_MODEL() == "gpt-4o"
