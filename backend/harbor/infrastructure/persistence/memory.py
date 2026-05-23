"""In-memory :class:`~harbor.domain.ports.deployment_repository.DeploymentRepository`.

Backed by a dict keyed on :class:`DeploymentId`. ``save`` overwrites — the
aggregate is the source of truth, so consumers always see the most recent
snapshot. Wrapped in an :class:`asyncio.Lock` to keep concurrent
:class:`CreateDeployment` runs safe in the same event loop.
"""

from __future__ import annotations

import asyncio

from harbor.domain.deployment import Deployment
from harbor.domain.identifiers import DeploymentId, TeamId


class InMemoryDeploymentRepository:
    """Dict-backed repository; suitable for tests and the dev-time backend."""

    def __init__(self) -> None:
        self._store: dict[DeploymentId, Deployment] = {}
        self._lock = asyncio.Lock()

    async def save(self, deployment: Deployment) -> None:
        async with self._lock:
            self._store[deployment.id] = deployment

    async def get(self, deployment_id: DeploymentId) -> Deployment | None:
        async with self._lock:
            return self._store.get(deployment_id)

    async def list_for_team(self, team: TeamId) -> tuple[Deployment, ...]:
        async with self._lock:
            return tuple(d for d in self._store.values() if d.team == team)
