"""Conversation memory management and context window pruning.

Persists messages as JSONL and prunes context to fit model limits.
"""

from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from core.constants import MAX_CONTEXT_TOKENS

logger = logging.getLogger(__name__)

_TRUNCATION_NOTICE = "[内容已截断]"
_MAX_SINGLE_MESSAGE_TOKENS = 8000
_KEEP_RECENT_ROUNDS = 15
_TOKEN_THRESHOLD_RATIO = 0.8


@dataclass
class ChatMessage:
    """A single message in a conversation."""

    role: str  # user | assistant | system | tool_result
    content: str
    seq: int = 0
    ts: float = field(default_factory=lambda: datetime.now(timezone.utc).timestamp())
    tokens: int = 0
    tool: str = ""


class MemoryStore:
    """Persistent conversation memory backed by JSONL files.

    Messages are appended to data/agents/<agent_id>/sessions/<session_id>/messages.jsonl
    """

    def __init__(self, agent_id: str, session_id: str, base_dir: str = "data/agents") -> None:
        self._agent_id = agent_id
        self._session_id = session_id
        self._base_dir = Path(base_dir)
        self._messages: list[ChatMessage] = []
        self._seq_counter = 0

        self._session_dir = self._base_dir / agent_id / "sessions" / session_id
        self._session_dir.mkdir(parents=True, exist_ok=True)
        self._messages_file = self._session_dir / "messages.jsonl"

    def add_message(self, role: str, content: str, tokens: int = 0, tool: str = "") -> ChatMessage:
        """Add a message and persist to JSONL.

        Args:
            role: Message role (user/assistant/system/tool_result).
            content: Message content text.
            tokens: Token count for this message.
            tool: Tool name (for tool_result messages).

        Returns:
            The created ChatMessage.
        """
        self._seq_counter += 1
        msg = ChatMessage(
            role=role,
            content=content,
            seq=self._seq_counter,
            tokens=tokens,
            tool=tool,
        )
        self._messages.append(msg)
        self._flush_message(msg)
        return msg

    def get_messages(self) -> list[ChatMessage]:
        """Get all messages in this session."""
        return list(self._messages)

    def load_from_disk(self) -> list[ChatMessage]:
        """Load messages from JSONL file on disk.

        Returns:
            List of loaded messages.
        """
        self._messages.clear()
        if not self._messages_file.exists():
            return []

        with open(self._messages_file) as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                data = json.loads(line)
                msg = ChatMessage(**data)
                self._messages.append(msg)
                self._seq_counter = max(self._seq_counter, msg.seq)

        logger.debug("Loaded %d messages from %s", len(self._messages), self._messages_file)
        return list(self._messages)

    def _flush_message(self, msg: ChatMessage) -> None:
        """Append a single message to the JSONL file."""
        with open(self._messages_file, "a") as f:
            f.write(json.dumps(asdict(msg)) + "\n")


class ContextPruner:
    """Prunes conversation context to fit within model token limits.

    Two-level pruning:
    1. Truncate individual messages exceeding 8000 tokens
    2. Remove oldest rounds when total exceeds 80% of model limit
    """

    @staticmethod
    def prune(messages: list[ChatMessage], max_tokens: int | None = None) -> list[ChatMessage]:
        """Prune messages to fit within token budget.

        Args:
            messages: The full message list.
            max_tokens: Override for max context tokens.

        Returns:
            Pruned list of messages.
        """
        limit = max_tokens or MAX_CONTEXT_TOKENS()
        threshold = int(limit * _TOKEN_THRESHOLD_RATIO)

        result = []
        for msg in messages:
            if msg.tokens > _MAX_SINGLE_MESSAGE_TOKENS:
                # Truncate single oversized message
                char_limit = _MAX_SINGLE_MESSAGE_TOKENS * 4  # rough chars-per-token estimate
                truncated = ChatMessage(
                    role=msg.role,
                    content=msg.content[:char_limit] + f"\n{_TRUNCATION_NOTICE}",
                    seq=msg.seq,
                    ts=msg.ts,
                    tokens=_MAX_SINGLE_MESSAGE_TOKENS,
                    tool=msg.tool,
                )
                result.append(truncated)
            else:
                result.append(msg)

        # Calculate total tokens
        total_tokens = sum(m.tokens for m in result)
        if total_tokens <= threshold:
            return result

        # Separate system messages and conversation
        system_msgs = [m for m in result if m.role == "system"]
        conv_msgs = [m for m in result if m.role != "system"]

        # Group into rounds (user+assistant pairs, with tool_results attached)
        rounds: list[list[ChatMessage]] = []
        current_round: list[ChatMessage] = []

        for msg in conv_msgs:
            if msg.role == "user" and current_round:
                rounds.append(current_round)
                current_round = []
            current_round.append(msg)
        if current_round:
            rounds.append(current_round)

        # Keep only the most recent N rounds
        keep_rounds = rounds[-_KEEP_RECENT_ROUNDS:] if len(rounds) > _KEEP_RECENT_ROUNDS else rounds

        pruned_conv = [msg for r in keep_rounds for msg in r]
        pruned = system_msgs + pruned_conv

        logger.debug(
            "Pruned context: %d -> %d messages, %d -> %d rounds",
            len(result),
            len(pruned),
            len(rounds),
            len(keep_rounds),
        )
        return pruned
