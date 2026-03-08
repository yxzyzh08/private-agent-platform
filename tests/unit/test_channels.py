"""Unit tests for channel layer."""

from __future__ import annotations

import pytest

from channels.base import BaseChannel, Message


class ConcreteChannel(BaseChannel):
    """Test channel implementation."""

    def __init__(self, channel_id: str = "test", allowed_users: list[str] | None = None):
        self.id = channel_id
        self.allowed_users = allowed_users or []
        self._started = False
        self._stopped = False
        self._sent_messages: list[tuple[str, Message]] = []

    async def start(self):
        self._started = True

    async def stop(self):
        self._stopped = True

    async def send(self, recipient: str, message: Message):
        self._sent_messages.append((recipient, message))


class TestBaseChannel:
    async def test_channel_is_abstract(self):
        with pytest.raises(TypeError):
            BaseChannel()

    async def test_concrete_channel(self):
        ch = ConcreteChannel("my_channel")
        assert ch.id == "my_channel"

    async def test_start_stop(self):
        ch = ConcreteChannel()
        await ch.start()
        assert ch._started
        await ch.stop()
        assert ch._stopped

    async def test_send_message(self):
        ch = ConcreteChannel()
        msg = Message(text="hello", channel_id="test")
        await ch.send("user1", msg)
        assert len(ch._sent_messages) == 1
        assert ch._sent_messages[0][0] == "user1"
        assert ch._sent_messages[0][1].text == "hello"

    async def test_verify_user_open_policy(self):
        ch = ConcreteChannel(allowed_users=[])
        assert await ch.verify_user("anyone") is True

    async def test_verify_user_whitelist_allowed(self):
        ch = ConcreteChannel(allowed_users=["user1", "user2"])
        assert await ch.verify_user("user1") is True

    async def test_verify_user_whitelist_denied(self):
        ch = ConcreteChannel(allowed_users=["user1"])
        assert await ch.verify_user("stranger") is False


class TestMessage:
    def test_message_creation(self):
        msg = Message(text="hello")
        assert msg.text == "hello"
        assert msg.channel_id == ""
        assert msg.timestamp is not None

    def test_message_with_metadata(self):
        msg = Message(text="hi", channel_id="tg", user_id="u1", metadata={"key": "val"})
        assert msg.channel_id == "tg"
        assert msg.metadata["key"] == "val"
