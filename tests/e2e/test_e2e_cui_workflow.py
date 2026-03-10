"""E2E smoke test for Phase 1D — cui workflow integration.

This script validates the backend API chain:
  project init → phase submit → SSE events → task control

Run manually: uv run python tests/e2e/test_e2e_cui_workflow.py

For full L3 validation (browser-based), follow the manual steps in
docs/phases/phase-1d.md Task 1D.12.
"""

from __future__ import annotations

import asyncio
import json
import shutil
import sys
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))


async def test_project_init_api():
    """Test POST /api/projects/init creates a project correctly."""
    from fastapi.testclient import TestClient
    from routes.projects import router
    from fastapi import FastAPI

    app = FastAPI()
    app.include_router(router)

    with tempfile.TemporaryDirectory() as tmpdir:
        base = Path(tmpdir) / "projects"
        base.mkdir()

        app.state.config = {
            "project_initialization": {
                "allowed_base_paths": [str(base)],
                "git_user": {"name": "E2E Bot", "email": "e2e@test.local"},
            }
        }

        client = TestClient(app)
        resp = client.post(
            "/api/projects/init",
            json={"name": "e2e-test-app", "base_path": str(base)},
        )
        assert resp.status_code == 200, f"Init failed: {resp.text}"
        data = resp.json()
        assert data["git_initialized"] is True
        assert (Path(data["repo_path"]) / ".git").exists()
        assert Path(data["phase_file"]).exists()
        print("  [PASS] project init API")


async def test_sse_event_flow():
    """Test SSE endpoint receives events from PlanEventBroker."""
    import threading
    import time
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from core.plan_event_broker import PlanEventBroker
    from core.task_planner import TaskPlan
    from routes.requirements_sse import router

    broker = PlanEventBroker()
    app = FastAPI()
    app.include_router(router)
    app.state.plan_event_broker = broker
    app.state.config = {"sse": {"heartbeat_interval_seconds": 2}}

    plan = TaskPlan(plan_id="e2e-plan", phase_file="test.md", repo_path="/tmp")

    with patch("routes.requirements_sse.TaskPlanStore") as mock_cls:
        mock_cls.return_value.load.return_value = plan
        client = TestClient(app)

        events_to_send = [
            {"event": "plan_started", "plan_id": "e2e-plan", "total_tasks": 2},
            {"event": "task_started", "plan_id": "e2e-plan", "task_id": "1.1"},
            {"event": "task_completed", "plan_id": "e2e-plan", "task_id": "1.1", "duration_ms": 5000},
            {"event": "plan_completed", "plan_id": "e2e-plan", "total_tasks": 2, "completed": 2},
        ]

        def publish_thread():
            time.sleep(0.2)
            loop = asyncio.new_event_loop()
            async def send():
                for e in events_to_send:
                    await broker.publish("e2e-plan", e)
            loop.run_until_complete(send())
            loop.close()

        t = threading.Thread(target=publish_thread)
        t.start()

        received = []
        with client.stream("GET", "/api/requirements/e2e-plan/events") as resp:
            assert resp.status_code == 200
            for line in resp.iter_lines():
                if line.startswith("event: "):
                    event_type = line.replace("event: ", "")
                    received.append(event_type)
                    if event_type == "plan_completed":
                        break

        t.join(timeout=5)
        assert "plan_started" in received
        assert "task_completed" in received
        assert "plan_completed" in received
        print("  [PASS] SSE event flow")


async def test_task_executor_events():
    """Test TaskExecutor emits events through PlanEventBroker."""
    from core.plan_event_broker import PlanEventBroker
    from core.task_executor import TaskExecutor
    from core.task_planner import SubTask, TaskPlan, TaskPlanStore
    from tools.base import ToolResult

    broker = PlanEventBroker()
    queue = broker.subscribe("exec-plan")

    registry = MagicMock()
    cli_tool = AsyncMock()
    cli_tool.execute = AsyncMock(
        return_value=ToolResult(success=True, data={"result": "ok"})
    )
    registry.get_tool = MagicMock(return_value=cli_tool)

    with tempfile.TemporaryDirectory() as tmpdir:
        store = TaskPlanStore(base_dir=str(Path(tmpdir) / "plans"))
        executor = TaskExecutor(
            tool_registry=registry,
            notifier=AsyncMock(send=AsyncMock(return_value=True)),
            config={"consecutive_failure_limit": 2, "summary_max_tokens": 100},
            store=store,
            event_broker=broker,
        )

        plan = TaskPlan(
            plan_id="exec-plan",
            phase_file="",
            repo_path=tmpdir,
            tasks=[SubTask(task_id="E.1", title="E2E Task", description="Test")],
        )

        with patch("core.task_executor._run_git", new_callable=AsyncMock) as mock_git:
            mock_git.return_value = (0, "")
            await executor.execute_plan(plan)

        events = []
        while not queue.empty():
            events.append(await queue.get())

        event_types = [e["event"] for e in events]
        assert "plan_started" in event_types, f"Missing plan_started in {event_types}"
        assert "task_started" in event_types
        assert "task_completed" in event_types
        assert "plan_completed" in event_types
        print("  [PASS] TaskExecutor event emission")


async def test_phase_1c_regression():
    """Verify Phase 1C APIs still work (regression)."""
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from routes.requirements import router

    app = FastAPI()
    app.include_router(router)
    app.state.config = {}
    app.state.tool_registry = MagicMock()

    client = TestClient(app)

    # Non-existent plan should 404
    resp = client.get("/api/requirements/nonexistent")
    assert resp.status_code == 404
    print("  [PASS] Phase 1C regression (GET plan 404)")


async def main():
    print("=" * 60)
    print("Phase 1D E2E Smoke Tests")
    print("=" * 60)

    tests = [
        ("Project Init API", test_project_init_api),
        ("SSE Event Flow", test_sse_event_flow),
        ("TaskExecutor Events", test_task_executor_events),
        ("Phase 1C Regression", test_phase_1c_regression),
    ]

    passed = 0
    failed = 0
    for name, test_fn in tests:
        print(f"\n--- {name} ---")
        try:
            await test_fn()
            passed += 1
        except Exception as e:
            print(f"  [FAIL] {e}")
            failed += 1

    print(f"\n{'=' * 60}")
    print(f"Results: {passed} passed, {failed} failed")
    print("=" * 60)

    if failed > 0:
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
