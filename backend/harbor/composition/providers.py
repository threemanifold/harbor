"""Composition-only :class:`ConnectedProviderRegistry` stubs.

The default Harbor backend has no provider adapters until SYM-211 plugs in
Modal. :class:`EmptyProviderRegistry` lets :func:`build_container` produce a
useful object anyway — :class:`CreateDeployment` will simply mark deployments
as failed with "No providers connected" until a real registry is supplied.

Tests inject their own :class:`ConnectedProviderRegistry` implementations
rather than relying on this stub.
"""

from __future__ import annotations

from harbor.domain.identifiers import TeamId
from harbor.domain.placement import ProviderTarget
from harbor.domain.ports.provider_adapter import ProviderAdapter


class EmptyProviderRegistry:
    """Registry that always reports zero connected providers."""

    async def list_targets(
        self, team: TeamId
    ) -> tuple[tuple[ProviderTarget, ProviderAdapter], ...]:
        return ()
