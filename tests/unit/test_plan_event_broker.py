"""Tests for PlanEventBroker (Phase 1D Task 1D.2)."""

from __future__ import annotations

import asyncio

import pytest

from core.plan_event_broker import PlanEventBroker


@pytest.fixture
def broker():
    return PlanEventBroker()


class TestSubscribe:
    """Test subscriber registration."""

    def test_subscribe_returns_queue(self, broker):
        queue = broker.subscribe("plan-1")
        assert isinstance(queue, asyncio.Queue)

    def test_subscribe_increments_count(self, broker):
        assert broker.subscriber_count("plan-1") == 0
        broker.subscribe("plan-1")
        assert broker.subscriber_count("plan-1") == 1
        broker.subscribe("plan-1")
        assert broker.subscriber_count("plan-1") == 2

    def test_multiple_plans_independent(self, broker):
        broker.subscribe("plan-1")
        broker.subscribe("plan-2")
        assert broker.subscriber_count("plan-1") == 1
        assert broker.subscriber_count("plan-2") == 1


class TestUnsubscribe:
    """Test subscriber removal."""

    def test_unsubscribe_removes_queue(self, broker):
        q = broker.subscribe("plan-1")
        broker.unsubscribe("plan-1", q)
        assert broker.subscriber_count("plan-1") == 0

    def test_unsubscribe_only_target_queue(self, broker):
        q1 = broker.subscribe("plan-1")
        broker.subscribe("plan-1")
        broker.unsubscribe("plan-1", q1)
        assert broker.subscriber_count("plan-1") == 1

    def test_unsubscribe_nonexistent_queue(self, broker):
        broker.subscribe("plan-1")
        other_queue = asyncio.Queue()
        broker.unsubscribe("plan-1", other_queue)
        assert broker.subscriber_count("plan-1") == 1

    def test_unsubscribe_cleans_empty_plan(self, broker):
        q = broker.subscribe("plan-1")
        broker.unsubscribe("plan-1", q)
        assert "plan-1" not in broker.active_plans


class TestPublish:
    """Test event broadcasting."""

    @pytest.mark.asyncio
    async def test_publish_to_single_subscriber(self, broker):
        q = broker.subscribe("plan-1")
        event = {"event": "task_started", "task_id": "T.1"}
        await broker.publish("plan-1", event)
        received = await asyncio.wait_for(q.get(), timeout=1.0)
        assert received == event

    @pytest.mark.asyncio
    async def test_publish_to_multiple_subscribers(self, broker):
        q1 = broker.subscribe("plan-1")
        q2 = broker.subscribe("plan-1")
        event = {"event": "task_completed", "task_id": "T.1"}
        await broker.publish("plan-1", event)
        r1 = await asyncio.wait_for(q1.get(), timeout=1.0)
        r2 = await asyncio.wait_for(q2.get(), timeout=1.0)
        assert r1 == event
        assert r2 == event

    @pytest.mark.asyncio
    async def test_publish_no_subscribers(self, broker):
        # Should not raise
        await broker.publish("plan-none", {"event": "test"})

    @pytest.mark.asyncio
    async def test_publish_different_plans_isolated(self, broker):
        q1 = broker.subscribe("plan-1")
        q2 = broker.subscribe("plan-2")
        await broker.publish("plan-1", {"event": "for-plan-1"})
        r1 = await asyncio.wait_for(q1.get(), timeout=1.0)
        assert r1["event"] == "for-plan-1"
        assert q2.empty()

    @pytest.mark.asyncio
    async def test_unsubscribed_queue_no_events(self, broker):
        q = broker.subscribe("plan-1")
        broker.unsubscribe("plan-1", q)
        await broker.publish("plan-1", {"event": "after-unsub"})
        assert q.empty()

    @pytest.mark.asyncio
    async def test_publish_multiple_events_ordered(self, broker):
        q = broker.subscribe("plan-1")
        events = [
            {"event": "plan_started", "n": 1},
            {"event": "task_started", "n": 2},
            {"event": "task_completed", "n": 3},
        ]
        for e in events:
            await broker.publish("plan-1", e)
        received = []
        for _ in range(3):
            received.append(await asyncio.wait_for(q.get(), timeout=1.0))
        assert received == events


class TestProperties:
    """Test helper properties."""

    def test_has_subscribers(self, broker):
        assert not broker.has_subscribers("plan-1")
        q = broker.subscribe("plan-1")
        assert broker.has_subscribers("plan-1")
        broker.unsubscribe("plan-1", q)
        assert not broker.has_subscribers("plan-1")

    def test_active_plans(self, broker):
        assert broker.active_plans == []
        broker.subscribe("plan-1")
        broker.subscribe("plan-2")
        assert sorted(broker.active_plans) == ["plan-1", "plan-2"]
