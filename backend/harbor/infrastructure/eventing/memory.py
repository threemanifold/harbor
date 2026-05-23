"""In-memory :class:`~harbor.domain.ports.event_bus.EventBus`.

Each subscription is backed by an :class:`asyncio.Queue` keyed by
:class:`DeploymentId`. Publishing fans out to every active queue for that id;
slow consumers therefore back-pressure the publisher (queues are unbounded by
default, which is fine for the in-memory single-process slice).

Subscriptions are open-ended: the async iterator yields forever. Consumers are
expected to break out of the loop on a terminal event (e.g.
:class:`DeploymentHealthy` / :class:`DeploymentFailed`). When a consumer
exits, the queue becomes orphaned — acceptable for a development-time bus, and
intentionally avoids hiding bugs by silently dropping events.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator

from harbor.domain.events import DeploymentEvent
from harbor.domain.identifiers import DeploymentId


class InMemoryEventBus:
    """Process-local pub/sub keyed by :class:`DeploymentId`."""

    def __init__(self) -> None:
        self._queues: dict[DeploymentId, list[asyncio.Queue[DeploymentEvent]]] = {}
        self._lock = asyncio.Lock()

    async def publish(self, event: DeploymentEvent) -> None:
        async with self._lock:
            # Snapshot under the lock so we don't race with subscribe().
            queues = list(self._queues.get(event.deployment_id, ()))
        for queue in queues:
            await queue.put(event)

    def subscribe(self, deployment_id: DeploymentId) -> AsyncIterator[DeploymentEvent]:
        queue: asyncio.Queue[DeploymentEvent] = asyncio.Queue()
        self._queues.setdefault(deployment_id, []).append(queue)
        return _stream(queue)


async def _stream(
    queue: asyncio.Queue[DeploymentEvent],
) -> AsyncIterator[DeploymentEvent]:
    while True:
        event = await queue.get()
        yield event
