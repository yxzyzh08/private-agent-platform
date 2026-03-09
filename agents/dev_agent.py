"""Development bot agent — handles GitHub Issue automation.

Receives Issue events from the GitHub Webhook channel, analyzes them via LLM,
notifies the Owner through ntfy, and orchestrates code fixes via Claude Code.
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

from agents.base_agent import BaseAgent
from channels.base import Message
from core.agent_runtime import AgentResponse
from core.logging import get_logger
from core.notifier import Notifier

logger = get_logger(__name__)

# Issue classification prompt used by the LLM
ISSUE_ANALYSIS_PROMPT = """You are a development bot that analyzes GitHub Issues.

Given the following GitHub Issue, analyze it and respond with a JSON object containing:
- "type": one of "bug", "feature", "refactor", "optimization", "other"
- "summary": a brief 1-2 sentence summary of the issue
- "complexity": one of "simple", "medium", "complex"
- "suggested_approach": a brief description of how to address this issue

Issue Title: {title}
Issue Body:
{body}

Respond ONLY with a valid JSON object, no markdown fencing."""

# Issue status constants
STATUS_PENDING = "pending_confirmation"
STATUS_APPROVED = "approved"
STATUS_REJECTED = "rejected"
STATUS_TIMEOUT = "timeout"
STATUS_EXECUTING = "executing"
STATUS_COMPLETED = "completed"
STATUS_FAILED = "failed"

# Default confirmation timeout: 24 hours
CONFIRMATION_TIMEOUT_SECONDS = 24 * 60 * 60


class PendingIssueStore:
    """Persists pending issue state to a JSON file.

    Stores issues awaiting Owner confirmation with their analysis results.
    """

    def __init__(self, store_path: str | None = None) -> None:
        self._path = Path(store_path or "data/agents/dev_bot/workspace/pending_issues.json")

    def _ensure_dir(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)

    def load(self) -> dict[str, dict]:
        """Load all pending issues from disk."""
        if not self._path.exists():
            return {}
        try:
            return json.loads(self._path.read_text())
        except (json.JSONDecodeError, OSError):
            logger.warning("Failed to load pending issues from %s", self._path)
            return {}

    def save(self, data: dict[str, dict]) -> None:
        """Save all pending issues to disk."""
        self._ensure_dir()
        self._path.write_text(json.dumps(data, indent=2, default=str))

    def add(self, issue_key: str, issue_data: dict) -> None:
        """Add or update a pending issue."""
        data = self.load()
        data[issue_key] = issue_data
        self.save(data)

    def get(self, issue_key: str) -> dict | None:
        """Get a pending issue by key."""
        return self.load().get(issue_key)

    def remove(self, issue_key: str) -> None:
        """Remove a pending issue."""
        data = self.load()
        data.pop(issue_key, None)
        self.save(data)

    def update_status(self, issue_key: str, status: str) -> None:
        """Update the status of a pending issue."""
        data = self.load()
        if issue_key in data:
            data[issue_key]["status"] = status
            self.save(data)

    def get_timed_out(self, timeout_seconds: int = CONFIRMATION_TIMEOUT_SECONDS) -> list[str]:
        """Get keys of issues that have exceeded the confirmation timeout."""
        data = self.load()
        now = time.time()
        timed_out = []
        for key, info in data.items():
            if info.get("status") == STATUS_PENDING:
                created = info.get("created_at", 0)
                if now - created > timeout_seconds:
                    timed_out.append(key)
        return timed_out


class DevAgent(BaseAgent):
    """Development bot — GitHub Issue analysis and automation.

    Workflow:
      1. Receive Issue event from GitHub Webhook channel
      2. Analyze Issue type (Bug/Feature/Refactor) via LLM
      3. Notify Owner via ntfy with analysis results
      4. Wait for Owner confirmation (via cui Web UI)
      5. Execute fix via Claude Code CLI/SDK
      6. Create PR and comment on Issue
    """

    def __init__(
        self,
        config_path: str | None = None,
        tool_registry: Any = None,
        notifier: Notifier | None = None,
        pending_store: PendingIssueStore | None = None,
    ) -> None:
        super().__init__(
            agent_id="dev_bot",
            config_path=config_path,
            tool_registry=tool_registry,
        )
        self._notifier = notifier or Notifier()
        self._pending_store = pending_store or PendingIssueStore()

    @property
    def repos(self) -> list[dict]:
        """Configured GitHub repositories."""
        return self.config.get("github", {}).get("repos", [])

    async def process_message(self, message: Message) -> AgentResponse:
        """Process a GitHub Issue event.

        Dispatches to the appropriate handler based on event type.
        """
        event_type = message.metadata.get("event_type", "")
        logger.info(
            "DevAgent processing message: event_type=%s, issue=#%s",
            event_type,
            message.metadata.get("issue_number", "?"),
        )

        if event_type == "issues.opened":
            return await self.handle_issue(message)

        logger.debug("DevAgent ignoring event_type=%s", event_type)
        return AgentResponse(
            agent_id=self.agent_id,
            content=f"Unhandled event type: {event_type}",
            finish_reason="stop",
        )

    async def handle_issue(self, message: Message) -> AgentResponse:
        """Analyze a newly opened GitHub Issue and notify Owner.

        Steps:
          1. Analyze via LLM
          2. Send ntfy notification
          3. Persist pending state for Owner confirmation

        Args:
            message: Message containing issue details in metadata.

        Returns:
            AgentResponse with the analysis result.
        """
        title = message.metadata.get("issue_title", "")
        body = message.metadata.get("issue_body", "")
        issue_number = message.metadata.get("issue_number", "?")
        repo = message.metadata.get("repo_full_name", "")
        issue_url = message.metadata.get("issue_url", "")

        logger.info("Analyzing issue #%s: %s (repo=%s)", issue_number, title, repo)

        prompt = ISSUE_ANALYSIS_PROMPT.format(title=title, body=body)
        runtime = self.get_runtime()
        response = await runtime.run(user_input=prompt)

        logger.info(
            "Issue #%s analysis complete: finish_reason=%s",
            issue_number,
            response.finish_reason,
        )

        # Persist pending confirmation state
        issue_key = f"{repo}#{issue_number}"
        self._pending_store.add(issue_key, {
            "status": STATUS_PENDING,
            "issue_number": issue_number,
            "title": title,
            "body": body,
            "repo": repo,
            "issue_url": issue_url,
            "analysis": response.content,
            "created_at": time.time(),
        })

        # Send ntfy notification
        await self._notify_owner(issue_number, title, repo, response.content, issue_url)

        return response

    async def confirm_issue(self, issue_key: str) -> bool:
        """Owner confirms execution for a pending issue.

        Args:
            issue_key: Issue identifier (e.g., "owner/repo#42").

        Returns:
            True if confirmation was accepted, False if issue not found.
        """
        issue = self._pending_store.get(issue_key)
        if not issue or issue.get("status") != STATUS_PENDING:
            logger.warning("Cannot confirm issue %s: not found or not pending", issue_key)
            return False

        self._pending_store.update_status(issue_key, STATUS_APPROVED)
        logger.info("Issue %s confirmed by Owner", issue_key)
        return True

    async def reject_issue(self, issue_key: str) -> bool:
        """Owner rejects execution for a pending issue.

        Args:
            issue_key: Issue identifier (e.g., "owner/repo#42").

        Returns:
            True if rejection was accepted, False if issue not found.
        """
        issue = self._pending_store.get(issue_key)
        if not issue or issue.get("status") != STATUS_PENDING:
            logger.warning("Cannot reject issue %s: not found or not pending", issue_key)
            return False

        self._pending_store.update_status(issue_key, STATUS_REJECTED)
        logger.info("Issue %s rejected by Owner", issue_key)
        return True

    async def check_timeouts(self) -> list[str]:
        """Check for and handle timed-out pending issues.

        Returns:
            List of issue keys that were timed out.
        """
        timed_out = self._pending_store.get_timed_out()
        for key in timed_out:
            self._pending_store.update_status(key, STATUS_TIMEOUT)
            logger.info("Issue %s timed out (24h no response)", key)
        return timed_out

    async def _notify_owner(
        self,
        issue_number: Any,
        title: str,
        repo: str,
        analysis: str,
        issue_url: str,
    ) -> None:
        """Send ntfy notification to Owner with Issue analysis."""
        ntfy_msg = (
            f"Issue #{issue_number}: {title}\n"
            f"Repo: {repo}\n\n"
            f"Analysis:\n{analysis}\n\n"
            f"Please confirm or reject in the Web UI."
        )
        await self._notifier.send(
            message=ntfy_msg,
            title=f"[DevBot] Issue #{issue_number} needs review",
            priority="high",
            tags=["robot", "github"],
            click_url=issue_url,
        )

    async def on_event(self, event: Any) -> None:
        """Handle platform events (e.g., bug_report from customer service bot)."""
        event_type = getattr(event, "type", "")
        if event_type == "bug_report":
            logger.info("DevAgent received bug_report event: %s", getattr(event, "event_id", ""))
