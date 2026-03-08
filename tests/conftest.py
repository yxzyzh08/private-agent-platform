"""Shared test fixtures for all test modules."""

from __future__ import annotations

import shutil
from pathlib import Path

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
