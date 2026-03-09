"""Shared test fixtures for all test modules."""

from __future__ import annotations

import shutil
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest
import yaml

from core.config import load_config, reset_config


@pytest.fixture
def mock_config(tmp_path):
    """Load a test-specific platform config.

    Creates a minimal test config in a temp directory and loads it.
    Resets config after the test.
    """
    config_data = {
        "platform": {
            "name": "Test Platform",
            "owner_telegram_id": "test_owner",
        },
        "models": {
            "default": "claude-sonnet-4-6",
            "fallback": ["gpt-4o"],
        },
        "security": {
            "dm_policy": "open",
            "allowed_users": [],
            "rate_limit_per_minute": 10,
        },
        "storage": {
            "vector_db": "chroma",
            "vector_db_path": str(tmp_path / "chroma"),
            "session_db": str(tmp_path / "sessions"),
        },
        "logging": {
            "level": "DEBUG",
            "format": "text",
        },
        "channels": {
            "plugins": [],
        },
        "dispatch": {
            "routes": [
                {"channel": "test_channel", "agent": "test_agent"},
            ],
        },
        "cui": {
            "host": "localhost",
            "port": 3001,
            "working_directory": ".",
        },
    }

    config_path = tmp_path / "platform.yaml"
    config_path.write_text(yaml.dump(config_data))
    reset_config()
    config = load_config(config_path)
    yield config
    reset_config()


@pytest.fixture
def tmp_data_dir(tmp_path):
    """Provide a temporary data directory, cleaned up after test.

    Creates standard data subdirectories matching the project structure.
    """
    data_dir = tmp_path / "data"
    for subdir in ["knowledge", "chroma", "agents", "sessions"]:
        (data_dir / subdir).mkdir(parents=True)

    yield data_dir

    # Cleanup is handled by tmp_path fixture automatically


@pytest.fixture
def mock_github_webhook():
    """Mock GitHubWebhookChannel for tests that need a webhook channel."""
    from channels.github_webhook.channel import GitHubWebhookChannel

    channel = GitHubWebhookChannel(webhook_secret="test-secret")
    channel.on_message = AsyncMock()
    return channel


@pytest.fixture
def mock_claude_cli():
    """Mock ClaudeCodeCliTool for tests that need CLI execution."""
    from tools.base import ToolResult

    tool = AsyncMock()
    tool.name = "claude_code_cli"
    tool.execute = AsyncMock(
        return_value=ToolResult(success=True, data={"result": "done", "needs_rotation": False})
    )
    return tool


@pytest.fixture
def mock_claude_sdk():
    """Mock ClaudeCodeSDKTool for tests that need SDK execution."""
    from tools.base import ToolResult

    tool = AsyncMock()
    tool.name = "claude_code_sdk"
    tool.execute = AsyncMock(
        return_value=ToolResult(
            success=True,
            data={
                "session_id": "test-session",
                "result": "done",
                "stop_reason": "end_turn",
                "needs_rotation": False,
                "compact_count": 0,
            },
        )
    )
    return tool


@pytest.fixture
def mock_session_rotator():
    """Mock SessionRotator for tests that need rotation logic."""
    from core.session_rotation import RotationResult

    rotator = AsyncMock()
    rotator.execute_with_rotation = AsyncMock(
        return_value=RotationResult(success=True, result="done", total_rotations=0)
    )
    return rotator
