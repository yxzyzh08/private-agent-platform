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


# --- Phase 1C fixtures ---


@pytest.fixture
def sample_phase_file(tmp_path):
    """Generate a standard-format phase-N.md test file with 3 tasks."""
    content = """\
# Phase Test: Sample

**分支**: `feat/test`
**目标**: Test phase file

---

### Task T.1: Create module

**状态**: [ ] 未开始
**依赖**: 无
**产出文件**: `src/module.py`

**描述**:
Create the main module.

**测试命令**:
```bash
uv run pytest tests/ -v
```

---

### Task T.2: Add tests

**状态**: [ ] 未开始
**依赖**: Task T.1
**产出文件**: `tests/test_module.py`

**描述**:
Write tests for the module.

**测试命令**:
```bash
uv run pytest tests/test_module.py -v
```

---

### Task T.3: Documentation

**状态**: [ ] 未开始
**依赖**: Task T.1
**产出文件**: `docs/module.md`

**描述**:
Write documentation.
"""
    path = tmp_path / "test-phase.md"
    path.write_text(content)
    return path


@pytest.fixture
def sample_subtasks():
    """Standard SubTask list for testing."""
    from core.task_planner import SubTask

    return [
        SubTask(task_id="T.1", title="Create module", description="Create the main module."),
        SubTask(
            task_id="T.2",
            title="Add tests",
            description="Write tests.",
            depends_on=["T.1"],
        ),
        SubTask(
            task_id="T.3",
            title="Documentation",
            description="Write docs.",
            depends_on=["T.1"],
        ),
    ]


@pytest.fixture
def sample_task_plan(sample_subtasks):
    """Standard TaskPlan for testing."""
    from core.task_planner import TaskPlan

    return TaskPlan(
        plan_id="test-plan-001",
        phase_file="docs/phases/test-phase.md",
        source="cui",
        repo_path="/tmp/test-repo",
        branch="feat/test",
        tasks=sample_subtasks,
    )


@pytest.fixture
def mock_task_executor():
    """Mock TaskExecutor with CLI execution mocked."""
    from tools.base import ToolResult

    executor = AsyncMock()
    executor.execute_plan = AsyncMock()
    executor.execute_subtask = AsyncMock()
    return executor


# --- Phase 1D fixtures ---


@pytest.fixture
def mock_plan_event_broker():
    """Mock PlanEventBroker for tests."""
    broker = AsyncMock()
    broker.publish = AsyncMock()
    broker.subscribe = MagicMock(return_value=MagicMock())
    broker.unsubscribe = MagicMock()
    broker.subscriber_count = MagicMock(return_value=0)
    broker.has_subscribers = MagicMock(return_value=False)
    return broker


@pytest.fixture
def sample_sse_events():
    """Standard SSE event sequence for testing."""
    return [
        {"event": "plan_started", "plan_id": "test-plan", "total_tasks": 3, "timestamp": 1.0},
        {"event": "task_started", "plan_id": "test-plan", "task_id": "T.1", "title": "Create module", "timestamp": 2.0},
        {"event": "task_completed", "plan_id": "test-plan", "task_id": "T.1", "duration_ms": 5000, "timestamp": 3.0},
        {"event": "task_started", "plan_id": "test-plan", "task_id": "T.2", "title": "Add tests", "timestamp": 4.0},
        {"event": "task_completed", "plan_id": "test-plan", "task_id": "T.2", "duration_ms": 3000, "timestamp": 5.0},
        {"event": "plan_completed", "plan_id": "test-plan", "total_tasks": 3, "completed": 2, "total_duration_ms": 8000, "timestamp": 6.0},
    ]


@pytest.fixture
def mock_project_init(tmp_path):
    """Provide a temporary base path for project initialization tests."""
    base = tmp_path / "projects"
    base.mkdir()
    return base
