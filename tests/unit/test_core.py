"""Unit tests for core modules."""

from __future__ import annotations

import json
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import yaml

from core.config import ConfigError, get_config, load_config, reset_config
from core.constants import (
    CONTEXT_ROUND_DEFINITION,
    DEFAULT_MODEL,
    MAX_CONTEXT_TOKENS,
    MAX_INPUT_LENGTH,
    MAX_MESSAGE_LENGTH,
    MAX_TOOL_USE_ROUNDS,
    RATE_LIMIT_PER_MINUTE,
)
from core.errors import (
    ChannelError,
    PermissionDeniedError,
    PlatformError,
    RateLimitError,
    ToolError,
    ValidationError,
)


# --- core/config.py tests ---


class TestConfig:
    def setup_method(self):
        reset_config()

    def teardown_method(self):
        reset_config()

    def test_config_load_default(self):
        config = load_config()
        assert config["platform"]["name"] == "My Agent Platform"

    def test_config_load_custom_path(self, tmp_path):
        custom = tmp_path / "test.yaml"
        custom.write_text(yaml.dump({"platform": {"name": "Test"}}))
        config = load_config(custom)
        assert config["platform"]["name"] == "Test"

    def test_config_file_not_found(self):
        with pytest.raises(ConfigError, match="not found"):
            load_config("/nonexistent/path.yaml")

    def test_config_invalid_yaml(self, tmp_path):
        bad = tmp_path / "bad.yaml"
        bad.write_text("{{invalid yaml")
        with pytest.raises(ConfigError, match="Invalid YAML"):
            load_config(bad)

    def test_config_not_mapping(self, tmp_path):
        bad = tmp_path / "list.yaml"
        bad.write_text("- item1\n- item2")
        with pytest.raises(ConfigError, match="must be a YAML mapping"):
            load_config(bad)

    def test_config_singleton(self):
        c1 = get_config()
        c2 = get_config()
        assert c1 is c2

    def test_config_reset(self):
        c1 = get_config()
        reset_config()
        c2 = get_config()
        assert c1 is not c2

    def test_config_has_required_sections(self):
        config = load_config()
        for section in ["platform", "models", "security", "storage", "channels"]:
            assert section in config, f"Missing section: {section}"

    def test_config_models_default(self):
        config = load_config()
        assert config["models"]["default"] == "claude-sonnet-4-6"
        assert isinstance(config["models"]["fallback"], list)

    def test_config_dispatch_routes(self):
        config = load_config()
        assert "dispatch" in config
        assert "routes" in config["dispatch"]
        assert len(config["dispatch"]["routes"]) > 0

    def test_config_cui_section(self):
        config = load_config()
        assert "cui" in config
        assert "host" in config["cui"]
        assert "port" in config["cui"]


# --- core/errors.py tests ---


class TestErrors:
    def test_platform_error_is_exception(self):
        assert issubclass(PlatformError, Exception)

    def test_tool_error_inherits_platform(self):
        assert issubclass(ToolError, PlatformError)

    def test_channel_error_inherits_platform(self):
        assert issubclass(ChannelError, PlatformError)

    def test_permission_denied_inherits_platform(self):
        assert issubclass(PermissionDeniedError, PlatformError)

    def test_rate_limit_inherits_platform(self):
        assert issubclass(RateLimitError, PlatformError)

    def test_validation_error_inherits_platform(self):
        assert issubclass(ValidationError, PlatformError)

    def test_error_message(self):
        err = ToolError("something broke")
        assert str(err) == "something broke"


# --- core/constants.py tests ---


class TestConstants:
    def setup_method(self):
        reset_config()

    def teardown_method(self):
        reset_config()

    def test_rate_limit_default(self):
        assert RATE_LIMIT_PER_MINUTE() == 10

    def test_default_model(self):
        assert DEFAULT_MODEL() == "claude-sonnet-4-6"

    def test_max_message_length(self):
        assert MAX_MESSAGE_LENGTH() > 0

    def test_max_context_tokens(self):
        assert MAX_CONTEXT_TOKENS() == 180_000

    def test_max_tool_use_rounds(self):
        assert MAX_TOOL_USE_ROUNDS() == 10

    def test_max_input_length(self):
        assert MAX_INPUT_LENGTH() == 16_000

    def test_context_round_definition(self):
        assert CONTEXT_ROUND_DEFINITION == "user+assistant pair"

    def test_constants_respect_config_override(self, tmp_path):
        custom = tmp_path / "override.yaml"
        custom.write_text(
            yaml.dump(
                {
                    "platform": {"name": "Test"},
                    "security": {"rate_limit_per_minute": 20},
                    "models": {"default": "gpt-4o"},
                }
            )
        )
        reset_config()
        load_config(custom)
        assert RATE_LIMIT_PER_MINUTE() == 20
        assert DEFAULT_MODEL() == "gpt-4o"


# --- core/event_bus.py tests ---


from core.event_bus import EventBus, PlatformEvent


class TestPlatformEvent:
    def test_event_creation(self):
        event = PlatformEvent(type="test", source_agent="agent1", payload={"key": "value"})
        assert event.type == "test"
        assert event.source_agent == "agent1"
        assert event.event_id  # UUID generated
        assert event.timestamp  # timestamp generated

    def test_event_serialization(self):
        event = PlatformEvent(type="test", source_agent="agent1", payload={"key": "value"})
        json_str = event.to_json()
        data = json.loads(json_str)
        assert data["type"] == "test"
        assert data["source_agent"] == "agent1"

    def test_event_deserialization(self):
        event = PlatformEvent(type="test", source_agent="agent1", payload={"x": 1})
        json_str = event.to_json()
        restored = PlatformEvent.from_json(json_str)
        assert restored.type == event.type
        assert restored.event_id == event.event_id
        assert restored.payload == event.payload

    def test_event_correlation_id(self):
        event = PlatformEvent(type="test", source_agent="a", payload={}, correlation_id="trace-123")
        assert event.correlation_id == "trace-123"


class TestEventBus:
    async def test_event_bus_publish_without_start(self):
        bus = EventBus()
        event = PlatformEvent(type="test", source_agent="a", payload={})
        with pytest.raises(RuntimeError, match="not started"):
            await bus.publish(event)

    async def test_event_bus_subscribe(self):
        bus = EventBus()
        handler = AsyncMock()
        await bus.subscribe("test_event", handler)
        assert "test_event" in bus._handlers
        assert handler in bus._handlers["test_event"]


# --- core/tool_registry.py tests ---


from core.tool_registry import ToolRegistry


class TestToolRegistry:
    def setup_method(self):
        self.registry = ToolRegistry()
        self.mock_tool = MagicMock()
        self.mock_tool.name = "test_tool"
        self.mock_tool.description = "A test tool"
        self.mock_tool.input_schema = {}

    def test_register_tool(self):
        self.registry.register(self.mock_tool)
        assert "test_tool" in [t.name for t in self.registry.list_all_tools()]

    def test_get_tool_with_permission(self):
        self.registry.register(self.mock_tool)
        self.registry.set_agent_permissions("agent1", ["test_tool"])
        tool = self.registry.get_tool("test_tool", "agent1")
        assert tool.name == "test_tool"

    def test_get_tool_without_permission(self):
        self.registry.register(self.mock_tool)
        self.registry.set_agent_permissions("agent1", [])
        with pytest.raises(PermissionDeniedError, match="not authorized"):
            self.registry.get_tool("test_tool", "agent1")

    def test_get_tool_not_found(self):
        with pytest.raises(KeyError, match="not found"):
            self.registry.get_tool("nonexistent", "agent1")

    def test_list_tools_for_agent(self):
        self.registry.register(self.mock_tool)
        other_tool = MagicMock()
        other_tool.name = "other_tool"
        self.registry.register(other_tool)
        self.registry.set_agent_permissions("agent1", ["test_tool"])
        tools = self.registry.list_tools("agent1")
        assert len(tools) == 1
        assert tools[0].name == "test_tool"

    def test_list_tools_no_permissions(self):
        self.registry.register(self.mock_tool)
        tools = self.registry.list_tools("unknown_agent")
        assert len(tools) == 0

    def test_register_overwrites(self):
        self.registry.register(self.mock_tool)
        new_tool = MagicMock()
        new_tool.name = "test_tool"
        new_tool.description = "Updated"
        self.registry.register(new_tool)
        all_tools = self.registry.list_all_tools()
        assert len(all_tools) == 1
        assert all_tools[0].description == "Updated"


# --- core/memory.py tests ---


from core.memory import ChatMessage, ContextPruner, MemoryStore


class TestMemoryStore:
    def test_add_message(self, tmp_path):
        store = MemoryStore("test_agent", "session1", base_dir=str(tmp_path))
        msg = store.add_message("user", "hello")
        assert msg.role == "user"
        assert msg.content == "hello"
        assert msg.seq == 1

    def test_messages_persist_to_disk(self, tmp_path):
        store = MemoryStore("test_agent", "session1", base_dir=str(tmp_path))
        store.add_message("user", "hello")
        store.add_message("assistant", "hi there")

        # Create new store instance and load from disk
        store2 = MemoryStore("test_agent", "session1", base_dir=str(tmp_path))
        loaded = store2.load_from_disk()
        assert len(loaded) == 2
        assert loaded[0].content == "hello"
        assert loaded[1].content == "hi there"

    def test_load_empty_session(self, tmp_path):
        store = MemoryStore("test_agent", "new_session", base_dir=str(tmp_path))
        loaded = store.load_from_disk()
        assert len(loaded) == 0

    def test_seq_counter_increments(self, tmp_path):
        store = MemoryStore("test_agent", "s1", base_dir=str(tmp_path))
        m1 = store.add_message("user", "first")
        m2 = store.add_message("assistant", "second")
        assert m1.seq == 1
        assert m2.seq == 2


class TestContextPruner:
    def _make_messages(self, n_rounds: int, tokens_per_msg: int = 100) -> list[ChatMessage]:
        msgs = [ChatMessage(role="system", content="system prompt", seq=0, tokens=50)]
        seq = 1
        for _ in range(n_rounds):
            msgs.append(ChatMessage(role="user", content="question", seq=seq, tokens=tokens_per_msg))
            seq += 1
            msgs.append(ChatMessage(role="assistant", content="answer", seq=seq, tokens=tokens_per_msg))
            seq += 1
        return msgs

    def test_no_pruning_needed(self):
        msgs = self._make_messages(5, tokens_per_msg=100)
        result = ContextPruner.prune(msgs, max_tokens=100000)
        assert len(result) == len(msgs)

    def test_truncate_oversized_message(self):
        msgs = [
            ChatMessage(role="user", content="x" * 50000, seq=1, tokens=9000),
        ]
        result = ContextPruner.prune(msgs, max_tokens=100000)
        assert result[0].tokens == 8000
        assert "[内容已截断]" in result[0].content

    def test_prune_old_rounds(self):
        msgs = self._make_messages(20, tokens_per_msg=5000)
        result = ContextPruner.prune(msgs, max_tokens=100000)
        # Should keep system + 15 most recent rounds
        system_msgs = [m for m in result if m.role == "system"]
        conv_msgs = [m for m in result if m.role != "system"]
        assert len(system_msgs) == 1
        assert len(conv_msgs) == 30  # 15 rounds * 2 messages

    def test_preserves_system_prompt(self):
        msgs = self._make_messages(20, tokens_per_msg=5000)
        result = ContextPruner.prune(msgs, max_tokens=100000)
        assert result[0].role == "system"


# --- core/agent_runtime.py tests ---


from core.agent_runtime import AgentResponse, TokenUsage, ToolCallInfo, sanitize_input


class TestSanitizeInput:
    def test_normal_text(self):
        assert sanitize_input("hello world") == "hello world"

    def test_preserves_newlines(self):
        assert sanitize_input("line1\nline2") == "line1\nline2"

    def test_filters_control_chars(self):
        result = sanitize_input("hello\x00\x01\x02world")
        assert result == "helloworld"

    def test_truncates_long_input(self):
        long_text = "a" * 20000
        result = sanitize_input(long_text)
        assert len(result) < 20000
        assert "[输入已截断]" in result

    def test_short_input_not_truncated(self):
        text = "short text"
        assert sanitize_input(text) == "short text"


class TestAgentResponse:
    def test_defaults(self):
        resp = AgentResponse()
        assert resp.content == ""
        assert resp.tool_calls == []
        assert resp.usage.input_tokens == 0

    def test_with_values(self):
        resp = AgentResponse(
            agent_id="test",
            content="hello",
            finish_reason="stop",
            usage=TokenUsage(input_tokens=100, output_tokens=50),
        )
        assert resp.agent_id == "test"
        assert resp.usage.output_tokens == 50


# --- core/dispatch.py tests ---


from core.dispatch import Dispatcher


class TestDispatcher:
    def setup_method(self):
        reset_config()
        load_config()

    def teardown_method(self):
        reset_config()

    def test_routes_loaded_from_config(self):
        d = Dispatcher()
        assert d.get_route("cui") == "dev_bot"
        assert d.get_route("telegram") == "cs_bot"

    def test_unknown_route(self):
        d = Dispatcher()
        assert d.get_route("nonexistent") is None

    async def test_dispatch_no_route(self):
        d = Dispatcher()
        result = await d.dispatch("unknown_channel", {"text": "hello"})
        assert result is None

    async def test_dispatch_no_handler(self):
        d = Dispatcher()
        result = await d.dispatch("cui", {"text": "hello"})
        assert result is None

    async def test_dispatch_with_handler(self):
        d = Dispatcher()
        handler = AsyncMock(return_value="handled")
        d.register_agent_handler("dev_bot", handler)
        result = await d.dispatch("cui", {"text": "hello"})
        assert result == "handled"
        handler.assert_called_once_with({"text": "hello"})


# --- core/channel_manager.py tests ---


from core.channel_manager import ChannelManager


class TestChannelManager:
    def setup_method(self):
        self.manager = ChannelManager()

    def _make_channel(self, channel_id: str) -> MagicMock:
        ch = MagicMock()
        ch.id = channel_id
        ch.start = AsyncMock()
        ch.stop = AsyncMock()
        return ch

    def test_register(self):
        ch = self._make_channel("test")
        self.manager.register(ch)
        assert "test" in self.manager.list_channels()

    def test_get_channel(self):
        ch = self._make_channel("test")
        self.manager.register(ch)
        assert self.manager.get_channel("test") is ch
        assert self.manager.get_channel("nonexistent") is None

    async def test_start_all(self):
        ch1 = self._make_channel("ch1")
        ch2 = self._make_channel("ch2")
        self.manager.register(ch1)
        self.manager.register(ch2)
        await self.manager.start_all()
        ch1.start.assert_called_once()
        ch2.start.assert_called_once()

    async def test_stop_all(self):
        ch1 = self._make_channel("ch1")
        self.manager.register(ch1)
        await self.manager.stop_all()
        ch1.stop.assert_called_once()

    async def test_start_failure_doesnt_block_others(self):
        ch1 = self._make_channel("ch1")
        ch1.start = AsyncMock(side_effect=Exception("boom"))
        ch2 = self._make_channel("ch2")
        self.manager.register(ch1)
        self.manager.register(ch2)
        await self.manager.start_all()
        ch2.start.assert_called_once()  # ch2 still started
