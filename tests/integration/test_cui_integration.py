"""L2 integration tests for Phase 1D — project init + SSE + event bus (Phase 1D Task 1D.10).

Tests end-to-end flow with real API + EventBroker, mocked CLI execution.
"""

from __future__ import annotations

import asyncio
import json
import threading
import time
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from core.plan_event_broker import PlanEventBroker
from routes.projects import router as projects_router
from routes.requirements import router as requirements_router
from routes.requirements_sse import router as sse_router


@pytest.fixture
def broker():
    return PlanEventBroker()


@pytest.fixture
def integration_app(tmp_path, broker):
    """Create a full integration app with all routers."""
    app = FastAPI()
    app.include_router(projects_router)
    app.include_router(requirements_router)
    app.include_router(sse_router)

    allowed_base = tmp_path / "projects"
    allowed_base.mkdir()

    app.state.config = {
        "project_initialization": {
            "allowed_base_paths": [str(allowed_base)],
            "git_user": {
                "name": "Test Bot",
                "email": "test@bot.local",
            },
        },
        "sse": {"heartbeat_interval_seconds": 1},
        "task_planning": {
            "max_subtasks": 10,
            "max_attempts_per_task": 2,
            "subtask_timeout_seconds": 900,
            "consecutive_failure_limit": 2,
            "summary_max_tokens": 1500,
            "sensitive_patterns": [".env*"],
        },
    }
    app.state.plan_event_broker = broker
    app.state.tool_registry = MagicMock()

    return app, allowed_base


@pytest.fixture
def client(integration_app):
    app, _ = integration_app
    return TestClient(app)


@pytest.fixture
def base_path(integration_app):
    _, bp = integration_app
    return bp


class TestInitProjectAndSubmit:
    """Test project init → submit phase flow."""

    def test_init_creates_project(self, client, base_path):
        """Initialize project and verify directory structure."""
        resp = client.post(
            "/api/projects/init",
            json={"name": "test-project", "base_path": str(base_path)},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["git_initialized"] is True

        # Verify project structure
        project_dir = base_path / "test-project"
        assert project_dir.exists()
        assert (project_dir / ".git").exists()
        assert (project_dir / "docs" / "phases" / "phase-1.md").exists()
        assert (project_dir / ".gitignore").exists()

    def test_init_then_submit_phase(self, client, base_path):
        """Init project, write proper phase file, then submit for execution."""
        # 1. Init project
        resp = client.post(
            "/api/projects/init",
            json={"name": "submit-test", "base_path": str(base_path)},
        )
        assert resp.status_code == 200
        project_dir = base_path / "submit-test"

        # 2. Write a valid phase file
        phase_content = """\
# Phase 1: Test

**分支**: `feat/test`
**目标**: Test project

---

### Task 1.1: Setup

**状态**: [ ] 未开始
**依赖**: 无
**产出文件**: `setup.py`

**描述**:
Create project setup.

**测试命令**:
```bash
echo ok
```
"""
        phase_file = project_dir / "docs" / "phases" / "phase-1.md"
        phase_file.write_text(phase_content)

        # 3. Submit for execution (mock the agent)
        mock_plan = MagicMock()
        mock_plan.plan_id = "integration-plan-001"
        mock_plan.status = "executing"
        mock_plan.total_count = 1
        mock_plan.completed_count = 0
        mock_plan.tasks = []

        mock_agent = AsyncMock()
        mock_agent.execute_from_phase = AsyncMock(return_value=mock_plan)

        with patch("routes.requirements._get_dev_agent", return_value=mock_agent):
            resp = client.post(
                "/api/requirements/from-phase",
                json={
                    "phase_file": str(phase_file),
                    "repo_path": str(project_dir),
                },
            )
            assert resp.status_code == 200
            data = resp.json()
            assert data["plan_id"] == "integration-plan-001"


class TestSSEEventsFlow:
    """Test SSE event streaming through PlanEventBroker."""

    def test_sse_receives_published_events(self, client, broker, base_path):
        """Mock TaskExecutor publishes events → SSE endpoint receives them."""
        # Create a mock plan in the store
        from core.task_planner import TaskPlan, TaskPlanStore

        plan = TaskPlan(
            plan_id="sse-test-plan",
            phase_file="test.md",
            repo_path=str(base_path),
        )

        with patch("routes.requirements_sse.TaskPlanStore") as mock_store_cls:
            store_instance = MagicMock()
            store_instance.load.return_value = plan
            mock_store_cls.return_value = store_instance

            events_to_send = [
                {"event": "plan_started", "plan_id": "sse-test-plan", "total_tasks": 2},
                {"event": "task_started", "plan_id": "sse-test-plan", "task_id": "1.1"},
                {"event": "task_completed", "plan_id": "sse-test-plan", "task_id": "1.1", "duration_ms": 1000},
                {"event": "plan_completed", "plan_id": "sse-test-plan", "total_tasks": 2, "completed": 2},
            ]

            def publish_thread():
                time.sleep(0.2)
                loop = asyncio.new_event_loop()
                async def send():
                    for e in events_to_send:
                        await broker.publish("sse-test-plan", e)
                loop.run_until_complete(send())
                loop.close()

            t = threading.Thread(target=publish_thread)
            t.start()

            received = []
            with client.stream("GET", "/api/requirements/sse-test-plan/events") as resp:
                assert resp.status_code == 200
                for line in resp.iter_lines():
                    if line.startswith("event: "):
                        event_type = line.replace("event: ", "")
                        received.append(event_type)
                        if event_type == "plan_completed":
                            break

            t.join(timeout=5)
            assert "plan_started" in received
            assert "task_started" in received
            assert "task_completed" in received
            assert "plan_completed" in received


class TestProjectInitValidation:
    """Test boundary cases for project initialization."""

    def test_invalid_name_rejected(self, client, base_path):
        """Invalid project names should be rejected with 400."""
        invalid_names = ["../escape", "my app", "/root", ".hidden"]
        for name in invalid_names:
            resp = client.post(
                "/api/projects/init",
                json={"name": name, "base_path": str(base_path)},
            )
            assert resp.status_code == 400, f"Expected 400 for name: {name}"

    def test_duplicate_project_rejected(self, client, base_path):
        """Creating same project twice should return 409."""
        client.post(
            "/api/projects/init",
            json={"name": "dup-test", "base_path": str(base_path)},
        )
        resp = client.post(
            "/api/projects/init",
            json={"name": "dup-test", "base_path": str(base_path)},
        )
        assert resp.status_code == 409

    def test_unauthorized_base_path_rejected(self, client, tmp_path):
        """Base path outside whitelist should be rejected."""
        other = tmp_path / "unauthorized"
        other.mkdir()
        resp = client.post(
            "/api/projects/init",
            json={"name": "test", "base_path": str(other)},
        )
        assert resp.status_code == 400


class TestEventBusIntegration:
    """Test EventBus events reach SSE endpoint through PlanEventBroker."""

    @pytest.mark.asyncio
    async def test_broker_fan_out_to_multiple_clients(self, broker):
        """PlanEventBroker should deliver events to all subscribers."""
        q1 = broker.subscribe("plan-x")
        q2 = broker.subscribe("plan-x")

        await broker.publish("plan-x", {"event": "test", "data": "hello"})
        r1 = await asyncio.wait_for(q1.get(), timeout=1.0)
        r2 = await asyncio.wait_for(q2.get(), timeout=1.0)
        assert r1 == r2
        assert r1["event"] == "test"
