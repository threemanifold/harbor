"""Modal-backed :class:`~harbor.domain.ports.provider_registry.ConnectedProviderRegistry`.

Exposes exactly one ``(ProviderTarget, ModalProviderAdapter)`` pair: the
single Modal workspace the backend is configured against.

Per the :mod:`harbor.composition` onion contract, this module is the
infrastructure-side counterpart to the empty registry stub in
:mod:`harbor.composition.providers`. Composition picks one or the other
based on whether ``MODAL_TOKEN_ID`` etc. are present in the env.
"""

from __future__ import annotations

from harbor.domain.identifiers import ProviderAccountId, Region, TeamId
from harbor.domain.placement import ProviderKind, ProviderTarget
from harbor.domain.ports.provider_adapter import ProviderAdapter
from harbor.infrastructure.providers.modal.adapter import ModalProviderAdapter


class ModalConnectedProviderRegistry:
    """Returns the configured Modal workspace as the team's only target.

    The same (target, adapter) pair is returned for every team — workspace
    multi-tenancy is out of scope for SYM-211; the Modal workspace is treated
    as a single shared deployment plane. A future ticket will swap this for a
    per-team lookup against a credentials store.
    """

    def __init__(
        self,
        *,
        adapter: ModalProviderAdapter,
        account_id: ProviderAccountId,
        region: Region,
    ) -> None:
        self._adapter: ProviderAdapter = adapter
        self._target = ProviderTarget(
            kind=ProviderKind.MODAL,
            account_id=account_id,
            region=region,
        )

    @property
    def target(self) -> ProviderTarget:
        return self._target

    async def list_targets(
        self, team: TeamId
    ) -> tuple[tuple[ProviderTarget, ProviderAdapter], ...]:
        return ((self._target, self._adapter),)


__all__ = ["ModalConnectedProviderRegistry"]
