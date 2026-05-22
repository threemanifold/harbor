from __future__ import annotations

from typing import Protocol

from harbor.domain.identifiers import TeamId
from harbor.domain.placement import ProviderTarget
from harbor.domain.ports.provider_adapter import ProviderAdapter


class ConnectedProviderRegistry(Protocol):
    """Returns the (target, credentialed adapter) pairs the team has connected.
    Each adapter is already bound to the team's stored credentials by the
    infrastructure implementation; the use case is never exposed to secrets."""

    async def list_targets(
        self, team: TeamId
    ) -> tuple[tuple[ProviderTarget, ProviderAdapter], ...]: ...
