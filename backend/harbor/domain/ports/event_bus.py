from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Protocol

from harbor.domain.events import DeploymentEvent
from harbor.domain.identifiers import DeploymentId


class EventBus(Protocol):
    async def publish(self, event: DeploymentEvent) -> None: ...

    def subscribe(
        self, deployment_id: DeploymentId
    ) -> AsyncIterator[DeploymentEvent]: ...
