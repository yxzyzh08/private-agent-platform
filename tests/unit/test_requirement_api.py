"""Tests for routes/requirements.py — requirement development API endpoints."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from core.task_planner import SubTask, TaskPlan


def _make_test_app():
    """Create a minimal FastAPI app with requirement routes."""
    from fastapi import FastAPI

    from routes.requirements import router

    app = FastAPI()
    app.include_router(router)
    # Mock app state
    app.state.config = {}
    app.state.tool_registry = MagicMock()
    app.state.dev_agent = None
    return app


def _make_plan(plan_id="test-plan", status="completed"):
    """Create a mock TaskPlan."""
    return TaskPlan(
        plan_id=plan_id,
        status=status,
        tasks=[
            SubTask(task_id="T.1", title="First", description="Do first", status="completed"),
            SubTask(task_id="T.2", title="Second", description="Do second", status="pending"),
        ],
    )


class TestFromPhaseEndpoint:
    def test_submit_from_phase_file_not_found(self):
        """POST with nonexistent file returns 404."""
        app = _make_test_app()
        client = TestClient(app)
        resp = client.post(
            "/api/requirements/from-phase",
            json={"phase_file": "/nonexistent/phase.md", "repo_path": "/tmp"},
        )
        assert resp.status_code == 404
        assert "not found" in resp.json()["detail"]

    def test_submit_from_phase_success(self, tmp_path):
        """POST with valid file calls DevAgent.execute_from_phase."""
        pf = tmp_path / "phase.md"
        pf.write_text("### Task T.1: Test\n\n**状态**: [ ] 未开始\n**依赖**: 无\n")

        app = _make_test_app()
        mock_agent = AsyncMock()
        mock_agent.execute_from_phase = AsyncMock(return_value=_make_plan())
        app.state.dev_agent = mock_agent

        client = TestClient(app)
        resp = client.post(
            "/api/requirements/from-phase",
            json={"phase_file": str(pf), "repo_path": str(tmp_path)},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["plan_id"] == "test-plan"
        assert data["status"] == "completed"
        mock_agent.execute_from_phase.assert_called_once()

    def test_submit_from_phase_no_pending_tasks(self, tmp_path):
        """POST returns message when no pending tasks."""
        pf = tmp_path / "phase.md"
        pf.write_text("### Task T.1: Done\n\n**状态**: [x] 完成\n**依赖**: 无\n")

        app = _make_test_app()
        mock_agent = AsyncMock()
        mock_agent.execute_from_phase = AsyncMock(return_value=None)
        app.state.dev_agent = mock_agent

        client = TestClient(app)
        resp = client.post(
            "/api/requirements/from-phase",
            json={"phase_file": str(pf), "repo_path": str(tmp_path)},
        )
        assert resp.status_code == 200
        assert "No pending tasks" in resp.json()["message"]

    def test_submit_from_phase_validation_error(self):
        """POST without required fields returns 422."""
        app = _make_test_app()
        client = TestClient(app)
        resp = client.post("/api/requirements/from-phase", json={})
        assert resp.status_code == 422


class TestGetPlanStatus:
    def test_get_plan_found(self):
        """GET returns plan status."""
        app = _make_test_app()
        mock_agent = AsyncMock()
        mock_agent.get_plan_status = AsyncMock(return_value=_make_plan())
        app.state.dev_agent = mock_agent

        client = TestClient(app)
        resp = client.get("/api/requirements/test-plan")
        assert resp.status_code == 200
        assert resp.json()["plan_id"] == "test-plan"

    def test_get_plan_not_found(self):
        """GET for nonexistent plan returns 404."""
        app = _make_test_app()
        mock_agent = AsyncMock()
        mock_agent.get_plan_status = AsyncMock(return_value=None)
        app.state.dev_agent = mock_agent

        client = TestClient(app)
        resp = client.get("/api/requirements/nonexistent")
        assert resp.status_code == 404


class TestAbortPlan:
    def test_abort_plan_success(self):
        """POST abort transitions plan."""
        app = _make_test_app()
        mock_agent = AsyncMock()
        mock_agent.abort_plan = AsyncMock(return_value=_make_plan(status="aborted"))
        app.state.dev_agent = mock_agent

        client = TestClient(app)
        resp = client.post("/api/requirements/test-plan/abort")
        assert resp.status_code == 200
        assert resp.json()["status"] == "aborted"

    def test_abort_plan_not_found(self):
        """POST abort for nonexistent plan returns 404."""
        app = _make_test_app()
        mock_agent = AsyncMock()
        mock_agent.abort_plan = AsyncMock(return_value=None)
        app.state.dev_agent = mock_agent

        client = TestClient(app)
        resp = client.post("/api/requirements/nonexistent/abort")
        assert resp.status_code == 404


class TestRetryTask:
    def test_retry_success(self):
        """POST retry calls agent retry_task."""
        app = _make_test_app()
        mock_agent = AsyncMock()
        mock_agent.retry_task = AsyncMock(return_value=_make_plan())
        app.state.dev_agent = mock_agent

        client = TestClient(app)
        resp = client.post(
            "/api/requirements/test-plan/tasks/T.1/retry",
            json={"feedback": "try async"},
        )
        assert resp.status_code == 200
        mock_agent.retry_task.assert_called_once_with("test-plan", "T.1", feedback="try async")

    def test_retry_not_found(self):
        """POST retry for nonexistent plan returns 404."""
        app = _make_test_app()
        mock_agent = AsyncMock()
        mock_agent.retry_task = AsyncMock(return_value=None)
        app.state.dev_agent = mock_agent

        client = TestClient(app)
        resp = client.post(
            "/api/requirements/xxx/tasks/T.1/retry",
            json={},
        )
        assert resp.status_code == 404


class TestSkipTask:
    def test_skip_success(self):
        """POST skip calls agent skip_task."""
        app = _make_test_app()
        mock_agent = AsyncMock()
        mock_agent.skip_task = AsyncMock(
            return_value={"plan": _make_plan(), "warnings": ["T.2"]}
        )
        app.state.dev_agent = mock_agent

        client = TestClient(app)
        resp = client.post("/api/requirements/test-plan/tasks/T.1/skip")
        assert resp.status_code == 200
        data = resp.json()
        assert data["warnings"] == ["T.2"]


class TestDeletePlan:
    def test_delete_success(self):
        """DELETE removes plan."""
        app = _make_test_app()
        mock_store = MagicMock()
        mock_store.load.return_value = _make_plan()
        mock_store.delete = MagicMock()

        client = TestClient(app)
        with patch("core.task_planner.TaskPlanStore", return_value=mock_store):
            resp = client.delete("/api/requirements/test-plan")

        assert resp.status_code == 200
        mock_store.delete.assert_called_once_with("test-plan")

    def test_delete_not_found(self):
        """DELETE for nonexistent plan returns 404."""
        app = _make_test_app()
        mock_store = MagicMock()
        mock_store.load.return_value = None

        client = TestClient(app)
        with patch("core.task_planner.TaskPlanStore", return_value=mock_store):
            resp = client.delete("/api/requirements/nonexistent")

        assert resp.status_code == 404


class TestRouteRegistration:
    def test_all_routes_registered(self):
        """All requirement routes are registered."""
        app = _make_test_app()
        routes = [r.path for r in app.routes]
        assert "/api/requirements/from-phase" in routes
        assert "/api/requirements/{plan_id}" in routes
        assert "/api/requirements/{plan_id}/abort" in routes
        assert "/api/requirements/{plan_id}/tasks/{task_id}/retry" in routes
        assert "/api/requirements/{plan_id}/tasks/{task_id}/skip" in routes
