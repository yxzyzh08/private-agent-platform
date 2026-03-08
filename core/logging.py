"""Platform logging infrastructure.

Provides unified logger, structured output (text/JSON), trace_id tracking,
and performance logging decorator.
"""

from __future__ import annotations

import functools
import json
import logging
import os
import time
from contextvars import ContextVar
from datetime import datetime, timezone
from logging.handlers import RotatingFileHandler
from typing import Any
from uuid import uuid4

# --- Trace ID ContextVar ---

_trace_id: ContextVar[str] = ContextVar("trace_id", default="")


def set_trace_id(trace_id: str | None = None) -> str:
    """Set the current trace ID (called at channel entry points).

    Args:
        trace_id: Optional trace ID. If None, generates a new UUID.

    Returns:
        The trace ID that was set.
    """
    tid = trace_id or str(uuid4())
    _trace_id.set(tid)
    return tid


def get_trace_id() -> str:
    """Get the current trace ID."""
    return _trace_id.get()


# --- Trace ID Filter ---


class TraceIdFilter(logging.Filter):
    """Adds trace_id to all log records."""

    def filter(self, record: logging.LogRecord) -> bool:
        record.trace_id = _trace_id.get() or "-"
        return True


# --- Formatters ---


class TextFormatter(logging.Formatter):
    """Human-readable log format for development."""

    def format(self, record: logging.LogRecord) -> str:
        trace_id = getattr(record, "trace_id", "-")
        ts = datetime.fromtimestamp(record.created, tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
        return f"{ts} [{record.levelname:>8}] {record.name} [trace={trace_id}] {record.getMessage()}"


class JsonFormatter(logging.Formatter):
    """JSON structured log format for production."""

    def format(self, record: logging.LogRecord) -> str:
        log_data: dict[str, Any] = {
            "ts": datetime.fromtimestamp(record.created, tz=timezone.utc).isoformat(),
            "level": record.levelname,
            "module": record.name,
            "trace_id": getattr(record, "trace_id", "-"),
            "msg": record.getMessage(),
        }

        # Include extra fields (e.g., duration_ms from @log_duration)
        for key in ("duration_ms", "success", "function"):
            val = getattr(record, key, None)
            if val is not None:
                log_data[key] = val

        if record.exc_info and record.exc_info[0] is not None:
            log_data["exception"] = self.formatException(record.exc_info)

        return json.dumps(log_data)


# --- Setup ---


def setup_logging(level: str | None = None, fmt: str | None = None, log_file: str | None = None) -> None:
    """Configure the root logger for the platform.

    Args:
        level: Log level (DEBUG/INFO/WARNING/ERROR). Env var LOG_LEVEL takes priority.
        fmt: Output format ('text' or 'json'). Env var LOG_FORMAT takes priority.
        log_file: Optional file path for RotatingFileHandler output.
    """
    # Resolve level: env var > argument > default
    level_str = os.environ.get("LOG_LEVEL", level or "INFO").upper()
    log_level = getattr(logging, level_str, logging.INFO)

    # Resolve format: env var > argument > default
    fmt_str = os.environ.get("LOG_FORMAT", fmt or "text").lower()

    # Create formatter
    formatter: logging.Formatter
    if fmt_str == "json":
        formatter = JsonFormatter()
    else:
        formatter = TextFormatter()

    # Configure root logger
    root = logging.getLogger()
    root.setLevel(log_level)

    # Clear existing handlers to avoid duplicates
    root.handlers.clear()

    # Add trace_id filter
    trace_filter = TraceIdFilter()
    root.addFilter(trace_filter)

    # Console handler (stdout)
    console = logging.StreamHandler()
    console.setFormatter(formatter)
    console.setLevel(log_level)
    root.addHandler(console)

    # Optional file handler
    if log_file:
        file_handler = RotatingFileHandler(
            log_file,
            maxBytes=10 * 1024 * 1024,  # 10MB
            backupCount=5,
        )
        file_handler.setFormatter(formatter)
        file_handler.setLevel(log_level)
        root.addHandler(file_handler)

    # Suppress noisy third-party loggers
    for noisy in ("httpx", "httpcore", "litellm", "chromadb", "urllib3"):
        logging.getLogger(noisy).setLevel(logging.WARNING)


def get_logger(name: str) -> logging.Logger:
    """Get a logger instance for a module.

    Usage:
        from core.logging import get_logger
        logger = get_logger(__name__)

    Args:
        name: Module name (typically __name__).

    Returns:
        A configured Logger instance.
    """
    return logging.getLogger(name)


# --- Performance Logging Decorator ---


def log_duration(func):
    """Decorator to log function execution duration.

    Supports both sync and async functions.
    Logs at INFO level with function name, duration_ms, and success/failure.
    """
    if _is_coroutine_function(func):

        @functools.wraps(func)
        async def async_wrapper(*args, **kwargs):
            logger = logging.getLogger(func.__module__)
            start = time.monotonic()
            success = True
            try:
                result = await func(*args, **kwargs)
                return result
            except Exception:
                success = False
                raise
            finally:
                duration_ms = int((time.monotonic() - start) * 1000)
                logger.info(
                    "%s completed in %dms (success=%s)",
                    func.__qualname__,
                    duration_ms,
                    success,
                    extra={"duration_ms": duration_ms, "success": success, "function": func.__qualname__},
                )

        return async_wrapper
    else:

        @functools.wraps(func)
        def sync_wrapper(*args, **kwargs):
            logger = logging.getLogger(func.__module__)
            start = time.monotonic()
            success = True
            try:
                result = func(*args, **kwargs)
                return result
            except Exception:
                success = False
                raise
            finally:
                duration_ms = int((time.monotonic() - start) * 1000)
                logger.info(
                    "%s completed in %dms (success=%s)",
                    func.__qualname__,
                    duration_ms,
                    success,
                    extra={"duration_ms": duration_ms, "success": success, "function": func.__qualname__},
                )

        return sync_wrapper


def _is_coroutine_function(func) -> bool:
    """Check if a function is a coroutine function."""
    import asyncio
    import inspect

    return asyncio.iscoroutinefunction(func) or inspect.iscoroutinefunction(func)
