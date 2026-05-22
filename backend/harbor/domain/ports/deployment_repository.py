from __future__ import annotations

from typing import Protocol

from harbor.domain.deployment import Deployment
from harbor.domain.identifiers import DeploymentId, TeamId


class DeploymentRepository(Protocol):
    async def save(self, deployment: Deployment) -> None: ...

    async def get(self, deployment_id: DeploymentId) -> Deployment | None: ...

    async def list_for_team(self, team: TeamId) -> tuple[Deployment, ...]: ...
