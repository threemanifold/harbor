import asyncio
from datetime import UTC, datetime

import pytest

from harbor.domain.events import (
    DeploymentEvent,
    DeploymentHealthy,
    DeploymentRequested,
)
from harbor.domain.endpoint import BearerToken, Endpoint
from harbor.domain.identifiers import DeploymentId
from harbor.infrastructure.eventing.memory import InMemoryEventBus


T0 = datetime(2026, 5, 22, 12, 0, 0, tzinfo=UTC)
DEP_A = DeploymentId("dep_a")
DEP_B = DeploymentId("dep_b")


def _requested(dep: DeploymentId) -> DeploymentRequested:
    return DeploymentRequested(deployment_id=dep, at=T0)


def _healthy(dep: DeploymentId) -> DeploymentHealthy:
    return DeploymentHealthy(
        deployment_id=dep,
        at=T0,
        endpoint=Endpoint(
            url="https://x.example/v1",
            auth=BearerToken(value="tok"),
            openai_compatible=True,
        ),
    )


async def _drain(
    bus: InMemoryEventBus, dep: DeploymentId, count: int
) -> list[DeploymentEvent]:
    received: list[DeploymentEvent] = []
    iterator = bus.subscribe(dep)
    async for event in iterator:
        received.append(event)
        if len(received) >= count:
            break
    return received


async def test_subscribe_receives_events_for_its_deployment() -> None:
    bus = InMemoryEventBus()
    consumer = asyncio.create_task(_drain(bus, DEP_A, count=2))
    # Yield once so the subscriber registers its queue before we publish.
    await asyncio.sleep(0)
    await bus.publish(_requested(DEP_A))
    await bus.publish(_healthy(DEP_A))
    events = await asyncio.wait_for(consumer, timeout=1.0)
    assert [type(e) for e in events] == [DeploymentRequested, DeploymentHealthy]


async def test_subscribe_ignores_other_deployments() -> None:
    bus = InMemoryEventBus()
    consumer = asyncio.create_task(_drain(bus, DEP_A, count=1))
    await asyncio.sleep(0)
    # Publish a noisy event on a different deployment first; our consumer
    # should not see it.
    await bus.publish(_requested(DEP_B))
    await bus.publish(_requested(DEP_A))
    events = await asyncio.wait_for(consumer, timeout=1.0)
    assert len(events) == 1
    assert events[0].deployment_id == DEP_A


async def test_multiple_subscribers_each_get_a_copy() -> None:
    bus = InMemoryEventBus()
    one = asyncio.create_task(_drain(bus, DEP_A, count=1))
    two = asyncio.create_task(_drain(bus, DEP_A, count=1))
    await asyncio.sleep(0)
    await bus.publish(_requested(DEP_A))
    a, b = await asyncio.wait_for(asyncio.gather(one, two), timeout=1.0)
    assert len(a) == 1 and len(b) == 1
    assert isinstance(a[0], DeploymentRequested)
    assert isinstance(b[0], DeploymentRequested)


async def test_subscribe_waits_when_no_events_available() -> None:
    bus = InMemoryEventBus()
    iterator = bus.subscribe(DEP_A)

    async def _next() -> DeploymentEvent:
        return await iterator.__anext__()

    pending: asyncio.Task[DeploymentEvent] = asyncio.create_task(_next())
    # Confirm it is genuinely waiting rather than racing through.
    with pytest.raises(asyncio.TimeoutError):
        await asyncio.wait_for(asyncio.shield(pending), timeout=0.05)
    await bus.publish(_requested(DEP_A))
    event = await asyncio.wait_for(pending, timeout=1.0)
    assert isinstance(event, DeploymentRequested)
