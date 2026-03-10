"""Unit tests for core/notifier.py (Task 1B.4)."""

from __future__ import annotations

import os
from unittest.mock import AsyncMock, patch

import pytest

from core.notifier import Notifier


class TestNotifier:
    def test_configured_with_topic(self):
        n = Notifier(topic="my-topic")
        assert n.configured is True

    @patch.dict("os.environ", {"NTFY_TOPIC": ""}, clear=False)
    def test_not_configured_without_topic(self):
        n = Notifier(topic="")
        assert n.configured is False

    @patch.dict("os.environ", {"NTFY_TOPIC": ""}, clear=False)
    async def test_send_without_topic(self):
        """Send returns False when no topic configured."""
        n = Notifier(topic="")
        result = await n.send("hello")
        assert result is False

    @patch("core.notifier.httpx.AsyncClient")
    async def test_send_success(self, mock_client_cls):
        mock_resp = AsyncMock()
        mock_resp.raise_for_status = lambda: None

        mock_client = AsyncMock()
        mock_client.post.return_value = mock_resp
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client_cls.return_value = mock_client

        n = Notifier(topic="test-topic", base_url="https://ntfy.example.com")
        result = await n.send(
            message="Test notification",
            title="Test Title",
            priority="high",
            tags=["robot"],
            click_url="https://example.com",
        )
        assert result is True
        mock_client.post.assert_called_once()

        # Check URL is correct
        call_args = mock_client.post.call_args
        assert call_args.args[0] == "https://ntfy.example.com/test-topic"

        # Check headers
        headers = call_args.kwargs.get("headers", {})
        assert headers["Title"] == "Test Title"
        assert headers["Priority"] == "high"
        assert headers["Tags"] == "robot"
        assert headers["Click"] == "https://example.com"

    @patch("core.notifier.httpx.AsyncClient")
    async def test_send_failure(self, mock_client_cls):
        import httpx

        mock_client = AsyncMock()
        mock_client.post.side_effect = httpx.HTTPError("Connection failed")
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client_cls.return_value = mock_client

        n = Notifier(topic="test-topic")
        result = await n.send("Test notification")
        assert result is False

    @patch("core.notifier.httpx.AsyncClient")
    async def test_send_minimal(self, mock_client_cls):
        """Send with only message, no optional headers."""
        mock_resp = AsyncMock()
        mock_resp.raise_for_status = lambda: None

        mock_client = AsyncMock()
        mock_client.post.return_value = mock_resp
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client_cls.return_value = mock_client

        n = Notifier(topic="test-topic")
        result = await n.send("Simple message")
        assert result is True

        # No optional headers should be set
        call_args = mock_client.post.call_args
        headers = call_args.kwargs.get("headers", {})
        assert "Title" not in headers
        assert "Priority" not in headers
