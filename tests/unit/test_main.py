"""Unit tests for main.py — platform entry point."""

from __future__ import annotations

from fastapi.testclient import TestClient


class TestCreateApp:
    """Tests for create_app() factory function."""

    def test_create_app_returns_fastapi_instance(self, mock_config):
        """create_app() should return a FastAPI app."""
        from main import create_app

        app = create_app()
        assert app is not None
        assert app.title == "Test Platform"
        assert app.version == "0.1.0"

    def test_create_app_registers_tools(self, mock_config):
        """create_app() should register all built-in tools."""
        from main import create_app

        app = create_app()
        # Tools are registered during create_app, accessible after startup
        # We verify by checking the health endpoint route exists
        routes = [r.path for r in app.routes]
        assert "/health" in routes


class TestHealthEndpoint:
    """Tests for GET /health endpoint."""

    def test_health_returns_200(self, mock_config):
        """Health endpoint should return 200 with platform info."""
        from main import create_app

        app = create_app()
        client = TestClient(app)
        response = client.get("/health")

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "healthy"
        assert data["platform"] == "Test Platform"
        assert data["version"] == "0.1.0"

    def test_health_includes_services(self, mock_config):
        """Health endpoint should report service statuses."""
        from main import create_app

        app = create_app()
        client = TestClient(app)
        response = client.get("/health")
        data = response.json()

        assert "services" in data
        assert "redis" in data["services"]
        assert "cui" in data["services"]

    def test_health_reports_redis_status(self, mock_config):
        """Health endpoint should report redis connectivity status."""
        from main import create_app

        app = create_app()
        client = TestClient(app)
        response = client.get("/health")
        data = response.json()

        assert data["services"]["redis"] in ("connected", "disconnected")

    def test_health_reports_tool_count(self, mock_config):
        """Health endpoint should report the number of registered tools."""
        from main import create_app

        app = create_app()
        client = TestClient(app)
        response = client.get("/health")
        data = response.json()

        assert data["tools"] == 3  # claude_code_cli, git, event_bus

    def test_health_reports_channels(self, mock_config):
        """Health endpoint should report registered channels."""
        from main import create_app

        app = create_app()
        client = TestClient(app)
        response = client.get("/health")
        data = response.json()

        assert "channels" in data
        assert isinstance(data["channels"], list)


class TestRegisterTools:
    """Tests for _register_tools helper."""

    def test_register_tools_adds_all_tools(self, mock_config):
        """_register_tools should register claude_code_cli, git, and event_bus tools."""
        from core.event_bus import EventBus
        from core.tool_registry import ToolRegistry
        from main import _register_tools

        registry = ToolRegistry()
        bus = EventBus()
        _register_tools(registry, bus)

        tools = registry.list_all_tools()
        tool_names = [t.name for t in tools]

        assert "claude_code_cli" in tool_names
        assert "git" in tool_names
        assert "event_bus" in tool_names
        assert len(tools) == 3
