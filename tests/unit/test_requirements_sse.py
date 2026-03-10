"""Tests for SSE requirements endpoint (Phase 1D Task 1D.2)."""

from __future__ import annotations

import asyncio
import json
from unittest.mock import MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from core.plan_event_broker import PlanEventBroker
from routes.requirements_sse import router, _format_sse


@pytest.fixture
def broker():
    return PlanEventBroker()


@pytest.fixture
def mock_plan():
    """Create a mock TaskPlan."""
    plan = MagicMock()
    plan.plan_id = "test-plan-001"
    plan.status = "executing"
    plan.total_count = 3
    plan.completed_count = 0
    plan.tasks = []
    return plan


@pytest.fixture
def app_with_broker(broker, mock_plan):
    """Create a FastAPI app with PlanEventBroker."""
    app = FastAPI()
    app.include_router(router)
    app.state.plan_event_broker = broker
    app.state.config = {"sse": {"heartbeat_interval_seconds": 1}}

    # Patch TaskPlanStore to return mock plan
    with patch("routes.requirements_sse.TaskPlanStore") as mock_store_cls:
        store_instance = MagicMock()
        store_instance.load.return_value = mock_plan
        mock_store_cls.return_value = store_instance
        yield app
        # cleanup after


@pytest.fixture
def client(app_with_broker):
    return TestClient(app_with_broker)


class TestFormatSSE:
    """Test SSE message formatting."""

    def test_format_basic_event(self):
        result = _format_sse("task_started", {"task_id": "T.1"})
        assert result.startswith("event: task_started\n")
        assert "data: " in result
        assert result.endswith("\n\n")

    def test_format_data_is_json(self):
        data = {"plan_id": "xxx", "task_id": "T.1"}
        result = _format_sse("test", data)
        data_line = result.split("\n")[1]
        parsed = json.loads(data_line.replace("data: ", ""))
        assert parsed == data


class TestSSEEndpoint:
    """Test SSE streaming endpoint."""

    def test_content_type(self, client, broker):
        """SSE endpoint should return text/event-stream."""
        # Publish a terminal event so the stream ends
        async def publish_and_close():
            await asyncio.sleep(0.1)
            await broker.publish("test-plan-001", {
                "event": "plan_completed",
                "plan_id": "test-plan-001",
                "total_tasks": 3,
            })

        loop = asyncio.new_event_loop()
        try:
            loop.run_in_executor(None, lambda: None)  # warm up

            # Use a thread to publish events
            import threading

            def publish_thread():
                new_loop = asyncio.new_event_loop()
                new_loop.run_until_complete(publish_and_close())
                new_loop.close()

            t = threading.Thread(target=publish_thread)
            t.start()

            with client.stream("GET", "/api/requirements/test-plan-001/events") as resp:
                assert resp.headers["content-type"].startswith("text/event-stream")
                # Read at least one event
                lines = []
                for line in resp.iter_lines():
                    lines.append(line)
                    if "plan_completed" in line:
                        break

            t.join(timeout=5)
        finally:
            loop.close()

    def test_nonexistent_plan_returns_404(self):
        """Non-existent plan should return 404."""
        app = FastAPI()
        app.include_router(router)
        app.state.plan_event_broker = PlanEventBroker()
        app.state.config = {}

        with patch("routes.requirements_sse.TaskPlanStore") as mock_store_cls:
            store_instance = MagicMock()
            store_instance.load.return_value = None
            mock_store_cls.return_value = store_instance
            test_client = TestClient(app)
            resp = test_client.get("/api/requirements/nonexistent/events")
            assert resp.status_code == 404

    def test_no_broker_returns_500(self):
        """Missing PlanEventBroker should return 500."""
        app = FastAPI()
        app.include_router(router)
        app.state.config = {}
        # No plan_event_broker on app.state

        with patch("routes.requirements_sse.TaskPlanStore") as mock_store_cls:
            store_instance = MagicMock()
            store_instance.load.return_value = MagicMock()
            mock_store_cls.return_value = store_instance
            test_client = TestClient(app)
            resp = test_client.get("/api/requirements/test-plan/events")
            assert resp.status_code == 500

    def test_events_received_in_order(self, client, broker):
        """Events should be received in publish order."""
        import threading

        events_to_send = [
            {"event": "plan_started", "plan_id": "test-plan-001", "total_tasks": 3},
            {"event": "task_started", "plan_id": "test-plan-001", "task_id": "T.1"},
            {"event": "plan_completed", "plan_id": "test-plan-001", "total_tasks": 3},
        ]

        def publish_thread():
            import time
            time.sleep(0.1)
            new_loop = asyncio.new_event_loop()
            async def send_all():
                for e in events_to_send:
                    await broker.publish("test-plan-001", e)
            new_loop.run_until_complete(send_all())
            new_loop.close()

        t = threading.Thread(target=publish_thread)
        t.start()

        received_events = []
        with client.stream("GET", "/api/requirements/test-plan-001/events") as resp:
            for line in resp.iter_lines():
                if line.startswith("event: "):
                    event_type = line.replace("event: ", "")
                    received_events.append(event_type)
                    if event_type == "plan_completed":
                        break

        t.join(timeout=5)
        assert received_events == ["plan_started", "task_started", "plan_completed"]

    def test_headers(self, client, broker):
        """SSE response should have correct headers."""
        import threading

        def publish_thread():
            import time
            time.sleep(0.1)
            new_loop = asyncio.new_event_loop()
            new_loop.run_until_complete(
                broker.publish("test-plan-001", {
                    "event": "plan_completed",
                    "plan_id": "test-plan-001",
                })
            )
            new_loop.close()

        t = threading.Thread(target=publish_thread)
        t.start()

        with client.stream("GET", "/api/requirements/test-plan-001/events") as resp:
            assert resp.headers.get("cache-control") == "no-cache"
            # Read until done
            for line in resp.iter_lines():
                if "plan_completed" in line:
                    break

        t.join(timeout=5)


class TestHeartbeat:
    """Test heartbeat mechanism."""

    def test_heartbeat_on_timeout(self, broker, mock_plan):
        """Should send heartbeat when no events arrive within interval."""
        app = FastAPI()
        app.include_router(router)
        app.state.plan_event_broker = broker
        app.state.config = {"sse": {"heartbeat_interval_seconds": 1}}

        with patch("routes.requirements_sse.TaskPlanStore") as mock_store_cls:
            store_instance = MagicMock()
            store_instance.load.return_value = mock_plan
            mock_store_cls.return_value = store_instance
            test_client = TestClient(app)

            import threading

            def publish_delayed():
                import time
                time.sleep(1.5)  # Wait for heartbeat
                new_loop = asyncio.new_event_loop()
                new_loop.run_until_complete(
                    broker.publish("test-plan-001", {
                        "event": "plan_completed",
                        "plan_id": "test-plan-001",
                    })
                )
                new_loop.close()

            t = threading.Thread(target=publish_delayed)
            t.start()

            received_events = []
            with test_client.stream("GET", "/api/requirements/test-plan-001/events") as resp:
                for line in resp.iter_lines():
                    if line.startswith("event: "):
                        received_events.append(line.replace("event: ", ""))
                        if "plan_completed" in line:
                            break

            t.join(timeout=5)
            assert "heartbeat" in received_events


class TestRouteRegistration:
    """Test route registration."""

    def test_registered_in_main_app(self):
        """SSE route should be registered in main.py."""
        from main import create_app

        with patch.dict("os.environ", {"GITHUB_WEBHOOK_SECRET": "test"}):
            app = create_app()
            routes = [r.path for r in app.routes]
            assert "/api/requirements/{plan_id}/events" in routes
