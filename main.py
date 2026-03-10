"""Platform entry point — FastAPI application with lifecycle management.

Loads configuration, registers tools, starts event bus and channels,
provides health endpoint, and handles graceful shutdown.
"""

from __future__ import annotations

import os
from contextlib import asynccontextmanager

import redis.asyncio as aioredis
from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.responses import JSONResponse

from core.channel_manager import ChannelManager
from core.config import get_config
from core.event_bus import EventBus
from core.logging import get_logger, setup_logging
from core.tool_registry import ToolRegistry
from channels.github_webhook.channel import GitHubWebhookChannel
from routes.requirements import router as requirements_router
from tools.claude_code_cli import ClaudeCodeCliTool
from tools.event_bus_tool import EventBusTool
from tools.git_tool import GitTool

logger = get_logger(__name__)


def _register_tools(registry: ToolRegistry, event_bus: EventBus) -> None:
    """Register all available tools in the registry."""
    registry.register(ClaudeCodeCliTool())
    registry.register(GitTool())
    registry.register(EventBusTool(event_bus))
    logger.info("Registered %d tools", len(registry.list_all_tools()))


def create_app() -> FastAPI:
    """Create and configure the FastAPI application.

    Loads environment variables, config, sets up logging,
    and wires up lifecycle events (startup/shutdown).

    Returns:
        Configured FastAPI application instance.
    """
    # Load .env before anything else
    load_dotenv()

    # Load platform config (uses already-loaded config if available)
    config = get_config()

    # Setup logging from config
    log_cfg = config.get("logging", {})
    setup_logging(
        level=log_cfg.get("level"),
        fmt=log_cfg.get("format"),
        log_file=log_cfg.get("file"),
    )

    # Core components
    redis_url = (
        os.environ.get("REDIS_URL")
        or config.get("storage", {}).get("redis_url", "redis://localhost:6379/0")
    )
    event_bus = EventBus(redis_url=redis_url)
    tool_registry = ToolRegistry()
    channel_manager = ChannelManager()

    _register_tools(tool_registry, event_bus)

    # Register GitHub Webhook channel
    github_channel = GitHubWebhookChannel()
    channel_manager.register(github_channel)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        """Manage startup and shutdown of platform services."""
        logger.info("Starting platform: %s", config.get("platform", {}).get("name", "Unknown"))

        # Start event bus
        try:
            await event_bus.start()
            logger.info("Event bus started")
        except Exception:
            logger.warning("Event bus failed to start (Redis may be unavailable)", exc_info=True)

        # Start channels
        await channel_manager.start_all()

        yield

        # Shutdown: channels first, then event bus
        logger.info("Shutting down platform...")
        await channel_manager.stop_all()
        await event_bus.stop()
        logger.info("Platform shutdown complete")

    app = FastAPI(
        title=config.get("platform", {}).get("name", "Agent Platform"),
        version="0.2.0",
        lifespan=lifespan,
    )

    # Store references on app state immediately (available before lifespan)
    app.state.event_bus = event_bus
    app.state.tool_registry = tool_registry
    app.state.channel_manager = channel_manager
    app.state.config = config

    # Register channel routes on the app
    github_channel.register_routes(app)

    # Register Phase 1C requirement API routes
    app.include_router(requirements_router)

    @app.get("/health")
    async def health_check():
        """Platform health check endpoint.

        Reports status of Redis connection, registered tools,
        active channels, and cui configuration.
        """
        # Check Redis connectivity
        redis_status = "unknown"
        try:
            redis_client = aioredis.from_url(redis_url, decode_responses=True)
            await redis_client.ping()
            redis_status = "connected"
            await redis_client.aclose()
        except Exception:
            redis_status = "disconnected"

        # cui config status
        cui_cfg = config.get("cui", {})
        cui_status = "configured" if cui_cfg.get("port") else "not_configured"

        # GitHub Webhook config status
        github_webhook_configured = bool(os.environ.get("GITHUB_WEBHOOK_SECRET"))

        return JSONResponse({
            "status": "healthy",
            "platform": config.get("platform", {}).get("name", "Unknown"),
            "version": "0.2.0",
            "services": {
                "redis": redis_status,
                "cui": {
                    "status": cui_status,
                    "host": cui_cfg.get("host", "localhost"),
                    "port": cui_cfg.get("port", 3001),
                },
                "github_webhook": {
                    "status": "configured" if github_webhook_configured else "not_configured",
                    "route": "POST /webhooks/github",
                },
            },
            "tools": len(tool_registry.list_all_tools()),
            "channels": channel_manager.list_channels(),
        })

    return app


def main() -> None:
    """Run the platform with uvicorn."""
    import uvicorn

    app = create_app()
    config = get_config()

    host = config.get("platform", {}).get("host", "0.0.0.0")
    port = config.get("platform", {}).get("port", 8000)

    uvicorn.run(app, host=host, port=port, log_level="info")


if __name__ == "__main__":
    main()
