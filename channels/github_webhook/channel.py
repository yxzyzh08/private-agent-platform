"""GitHub Webhook channel adapter.

Receives GitHub Webhook events (issue creation), verifies signatures,
and forwards parsed events to the dispatch layer.
"""

from __future__ import annotations

import hashlib
import hmac
import os

from fastapi import FastAPI, Request, Response

from channels.base import BaseChannel, Message
from core.errors import ChannelError
from core.logging import get_logger, set_trace_id

logger = get_logger(__name__)


class WebhookVerificationError(ChannelError):
    """Raised when GitHub Webhook signature verification fails."""


class GitHubWebhookChannel(BaseChannel):
    """GitHub Webhook channel — listens for issue events via HTTP POST.

    Verifies X-Hub-Signature-256 on every request. Only processes
    ``issues.opened`` events; other events are acknowledged but ignored.
    """

    def __init__(
        self,
        webhook_secret: str | None = None,
        on_message=None,
    ):
        self.id = "github_webhook"
        self.on_message = on_message
        self.allowed_users: list[str] = []
        self._webhook_secret = webhook_secret or os.environ.get("GITHUB_WEBHOOK_SECRET", "")
        self._app: FastAPI | None = None

    # --- BaseChannel interface ---

    async def start(self) -> None:
        logger.info("GitHub Webhook channel started (route: POST /webhooks/github)")

    async def stop(self) -> None:
        logger.info("GitHub Webhook channel stopped")

    async def send(self, recipient: str, message: Message) -> None:
        logger.warning("GitHubWebhookChannel.send() is not applicable — GitHub Webhooks are inbound only")

    # --- Signature verification ---

    def verify_signature(self, payload: bytes, signature_header: str) -> bool:
        """Verify the X-Hub-Signature-256 header against the payload.

        Args:
            payload: Raw request body bytes.
            signature_header: Value of the X-Hub-Signature-256 header
                              (e.g. "sha256=abc123...").

        Returns:
            True if the signature is valid.
        """
        if not self._webhook_secret:
            logger.warning("GITHUB_WEBHOOK_SECRET not configured — rejecting all webhooks")
            return False

        if not signature_header or not signature_header.startswith("sha256="):
            return False

        expected = hmac.new(
            self._webhook_secret.encode(),
            payload,
            hashlib.sha256,
        ).hexdigest()

        received = signature_header[len("sha256="):]
        return hmac.compare_digest(expected, received)

    # --- FastAPI route registration ---

    def register_routes(self, app: FastAPI) -> None:
        """Register the ``POST /webhooks/github`` route on the given FastAPI app."""
        self._app = app

        @app.post("/webhooks/github")
        async def handle_webhook(request: Request) -> Response:
            return await self._handle_request(request)

    async def _handle_request(self, request: Request) -> Response:
        """Process an incoming GitHub Webhook request."""
        trace_id = set_trace_id()
        body = await request.body()
        signature = request.headers.get("X-Hub-Signature-256", "")

        if not self.verify_signature(body, signature):
            logger.warning(
                "GitHub Webhook signature verification failed (trace=%s)",
                trace_id,
            )
            return Response(content="Forbidden", status_code=403)

        event_type = request.headers.get("X-GitHub-Event", "")
        logger.info(
            "Received GitHub event: %s (trace=%s)",
            event_type,
            trace_id,
        )

        if event_type != "issues":
            return Response(content="OK", status_code=200)

        import json

        try:
            payload = json.loads(body)
        except json.JSONDecodeError:
            logger.error("Failed to parse webhook JSON body (trace=%s)", trace_id)
            return Response(content="Bad Request", status_code=400)

        action = payload.get("action", "")
        if action != "opened":
            logger.debug("Ignoring issues.%s event (trace=%s)", action, trace_id)
            return Response(content="OK", status_code=200)

        issue = payload.get("issue", {})
        repo = payload.get("repository", {})

        message = Message(
            text=f"[Issue #{issue.get('number', '?')}] {issue.get('title', 'Untitled')}\n\n{issue.get('body', '')}",
            channel_id=self.id,
            user_id=issue.get("user", {}).get("login", "unknown"),
            message_id=str(issue.get("id", "")),
            metadata={
                "event_type": "issues.opened",
                "issue_number": issue.get("number"),
                "issue_title": issue.get("title", ""),
                "issue_body": issue.get("body", ""),
                "issue_url": issue.get("html_url", ""),
                "repo_full_name": repo.get("full_name", ""),
                "repo_owner": repo.get("owner", {}).get("login", ""),
                "repo_name": repo.get("name", ""),
                "sender": payload.get("sender", {}).get("login", ""),
                "trace_id": trace_id,
            },
        )

        if self.on_message:
            try:
                await self.on_message(message)
            except Exception:
                logger.error("Error dispatching GitHub webhook message (trace=%s)", trace_id, exc_info=True)
                return Response(content="Internal Server Error", status_code=500)

        logger.info(
            "Processed issues.opened: #%s %s (repo=%s, trace=%s)",
            issue.get("number"),
            issue.get("title"),
            repo.get("full_name"),
            trace_id,
        )
        return Response(content="OK", status_code=200)
