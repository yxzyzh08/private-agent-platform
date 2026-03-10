"""Unit tests for GitHub Webhook channel (Task 1B.1)."""

from __future__ import annotations

import hashlib
import hmac
import json
from unittest.mock import AsyncMock

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from channels.github_webhook.channel import GitHubWebhookChannel


WEBHOOK_SECRET = "test-secret-123"


def _sign(payload: bytes, secret: str = WEBHOOK_SECRET) -> str:
    """Generate a valid X-Hub-Signature-256 header value."""
    sig = hmac.new(secret.encode(), payload, hashlib.sha256).hexdigest()
    return f"sha256={sig}"


def _issue_payload(
    number: int = 42,
    title: str = "Fix login bug",
    body: str = "Login fails on mobile",
    action: str = "opened",
) -> dict:
    return {
        "action": action,
        "issue": {
            "id": 1001,
            "number": number,
            "title": title,
            "body": body,
            "html_url": f"https://github.com/owner/repo/issues/{number}",
            "user": {"login": "reporter"},
        },
        "repository": {
            "full_name": "owner/repo",
            "name": "repo",
            "owner": {"login": "owner"},
        },
        "sender": {"login": "reporter"},
    }


@pytest.fixture
def webhook_app():
    """Create a FastAPI app with the GitHub Webhook channel registered."""
    app = FastAPI()
    channel = GitHubWebhookChannel(webhook_secret=WEBHOOK_SECRET)
    channel.on_message = AsyncMock()
    channel.register_routes(app)
    return app, channel


@pytest.fixture
async def client(webhook_app):
    app, _ = webhook_app
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


class TestGitHubWebhookSignature:
    async def test_valid_signature(self, client, webhook_app):
        _, channel = webhook_app
        payload = json.dumps(_issue_payload()).encode()

        resp = await client.post(
            "/webhooks/github",
            content=payload,
            headers={
                "X-Hub-Signature-256": _sign(payload),
                "X-GitHub-Event": "issues",
                "Content-Type": "application/json",
            },
        )
        assert resp.status_code == 200
        channel.on_message.assert_called_once()

    async def test_invalid_signature(self, client, webhook_app):
        _, channel = webhook_app
        payload = json.dumps(_issue_payload()).encode()

        resp = await client.post(
            "/webhooks/github",
            content=payload,
            headers={
                "X-Hub-Signature-256": "sha256=invalid",
                "X-GitHub-Event": "issues",
                "Content-Type": "application/json",
            },
        )
        assert resp.status_code == 403
        channel.on_message.assert_not_called()

    async def test_missing_signature(self, client, webhook_app):
        _, channel = webhook_app
        payload = json.dumps(_issue_payload()).encode()

        resp = await client.post(
            "/webhooks/github",
            content=payload,
            headers={
                "X-GitHub-Event": "issues",
                "Content-Type": "application/json",
            },
        )
        assert resp.status_code == 403
        channel.on_message.assert_not_called()

    async def test_no_secret_configured(self):
        """Channel without secret rejects all requests."""
        app = FastAPI()
        channel = GitHubWebhookChannel(webhook_secret="")
        channel.register_routes(app)

        payload = json.dumps(_issue_payload()).encode()
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as c:
            resp = await c.post(
                "/webhooks/github",
                content=payload,
                headers={
                    "X-Hub-Signature-256": _sign(payload),
                    "X-GitHub-Event": "issues",
                },
            )
        assert resp.status_code == 403


class TestGitHubWebhookIssueOpened:
    async def test_issue_opened_parsed(self, client, webhook_app):
        _, channel = webhook_app
        data = _issue_payload(number=99, title="Add dark mode", body="Please add dark mode")
        payload = json.dumps(data).encode()

        resp = await client.post(
            "/webhooks/github",
            content=payload,
            headers={
                "X-Hub-Signature-256": _sign(payload),
                "X-GitHub-Event": "issues",
                "Content-Type": "application/json",
            },
        )
        assert resp.status_code == 200
        msg = channel.on_message.call_args[0][0]
        assert "#99" in msg.text
        assert "Add dark mode" in msg.text
        assert msg.channel_id == "github_webhook"
        assert msg.metadata["event_type"] == "issues.opened"
        assert msg.metadata["issue_number"] == 99
        assert msg.metadata["repo_full_name"] == "owner/repo"

    async def test_ignore_other_events(self, client, webhook_app):
        """Non-issues events should return 200 but not dispatch."""
        _, channel = webhook_app
        payload = json.dumps({"action": "created"}).encode()

        resp = await client.post(
            "/webhooks/github",
            content=payload,
            headers={
                "X-Hub-Signature-256": _sign(payload),
                "X-GitHub-Event": "push",
                "Content-Type": "application/json",
            },
        )
        assert resp.status_code == 200
        channel.on_message.assert_not_called()

    async def test_ignore_issue_closed(self, client, webhook_app):
        """issues.closed should be ignored."""
        _, channel = webhook_app
        data = _issue_payload(action="closed")
        payload = json.dumps(data).encode()

        resp = await client.post(
            "/webhooks/github",
            content=payload,
            headers={
                "X-Hub-Signature-256": _sign(payload),
                "X-GitHub-Event": "issues",
                "Content-Type": "application/json",
            },
        )
        assert resp.status_code == 200
        channel.on_message.assert_not_called()


class TestGitHubWebhookChannel:
    async def test_start_stop(self):
        channel = GitHubWebhookChannel(webhook_secret=WEBHOOK_SECRET)
        await channel.start()
        await channel.stop()

    async def test_send_is_noop(self):
        from channels.base import Message

        channel = GitHubWebhookChannel(webhook_secret=WEBHOOK_SECRET)
        await channel.send("someone", Message(text="hi"))

    async def test_on_message_error_returns_500(self, webhook_app):
        app, channel = webhook_app
        channel.on_message = AsyncMock(side_effect=RuntimeError("dispatch failed"))

        data = _issue_payload()
        payload = json.dumps(data).encode()

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as c:
            resp = await c.post(
                "/webhooks/github",
                content=payload,
                headers={
                    "X-Hub-Signature-256": _sign(payload),
                    "X-GitHub-Event": "issues",
                    "Content-Type": "application/json",
                },
            )
        assert resp.status_code == 500
