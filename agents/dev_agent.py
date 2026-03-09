"""Development bot agent — handles GitHub Issue automation.

Receives Issue events from the GitHub Webhook channel, analyzes them via LLM,
notifies the Owner through ntfy, and orchestrates code fixes via Claude Code.
"""

from __future__ import annotations

from typing import Any

from agents.base_agent import BaseAgent
from channels.base import Message
from core.agent_runtime import AgentResponse
from core.logging import get_logger

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
    ) -> None:
        super().__init__(
            agent_id="dev_bot",
            config_path=config_path,
            tool_registry=tool_registry,
        )

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
        """Analyze a newly opened GitHub Issue.

        Uses the LLM to classify the issue and generate an analysis summary.

        Args:
            message: Message containing issue details in metadata.

        Returns:
            AgentResponse with the analysis result.
        """
        title = message.metadata.get("issue_title", "")
        body = message.metadata.get("issue_body", "")
        issue_number = message.metadata.get("issue_number", "?")
        repo = message.metadata.get("repo_full_name", "")

        logger.info("Analyzing issue #%s: %s (repo=%s)", issue_number, title, repo)

        prompt = ISSUE_ANALYSIS_PROMPT.format(title=title, body=body)

        runtime = self.get_runtime()
        response = await runtime.run(user_input=prompt)

        logger.info(
            "Issue #%s analysis complete: finish_reason=%s",
            issue_number,
            response.finish_reason,
        )

        return response

    async def on_event(self, event: Any) -> None:
        """Handle platform events (e.g., bug_report from customer service bot)."""
        event_type = getattr(event, "type", "")
        if event_type == "bug_report":
            logger.info("DevAgent received bug_report event: %s", getattr(event, "event_id", ""))
