"""Composition-only :class:`ConnectedProviderRegistry` selection.

The Harbor backend has two registry implementations the composition root
might wire:

* :class:`EmptyProviderRegistry` — always reports zero connected providers.
  Useful for tests and the ``/health`` smoke check; the only path that lets
  :func:`build_container` succeed without env config.
* :class:`~harbor.infrastructure.providers.modal.registry.ModalConnectedProviderRegistry`
  — exposes the configured Modal workspace as the team's only provider.

:func:`build_default_provider_registry` inspects the process env (via
:mod:`harbor.config.modal_config`) and returns whichever is appropriate. Tests
inject their own :class:`ConnectedProviderRegistry` directly into
:func:`build_container` and never go through this helper.
"""

from __future__ import annotations

import os

from harbor.config.modal_config import ModalConfig, try_load_modal_config
from harbor.domain.identifiers import ProviderAccountId, Region, TeamId
from harbor.domain.placement import ProviderTarget
from harbor.domain.ports.provider_adapter import ProviderAdapter
from harbor.domain.ports.provider_registry import ConnectedProviderRegistry
from harbor.infrastructure.providers.modal.adapter import ModalProviderAdapter
from harbor.infrastructure.providers.modal.client import ModalClient
from harbor.infrastructure.providers.modal.default_client import DefaultModalClient
from harbor.infrastructure.providers.modal.registry import (
    ModalConnectedProviderRegistry,
)

# Modal advertises a global control plane; "modal-default" is the Harbor-side
# convention for "the Modal default plane" until per-region pricing matters.
_DEFAULT_MODAL_REGION = "modal-default"


class EmptyProviderRegistry:
    """Registry that always reports zero connected providers."""

    async def list_targets(
        self, team: TeamId
    ) -> tuple[tuple[ProviderTarget, ProviderAdapter], ...]:
        return ()


def build_default_provider_registry(
    *,
    env: "os._Environ[str] | dict[str, str] | None" = None,
    client: ModalClient | None = None,
) -> ConnectedProviderRegistry:
    """Return the Modal registry when Modal env is set, else
    :class:`EmptyProviderRegistry`.

    Parameters
    ----------
    env:
        Override the environment source. Defaults to ``os.environ``.
    client:
        Override the :class:`ModalClient` used by the Modal adapter. Useful
        for tests that want to verify the wiring without mocking env.
    """
    config = try_load_modal_config(env)
    if config is None:
        return EmptyProviderRegistry()
    return _build_modal_registry(config, client=client)


def _build_modal_registry(
    config: ModalConfig,
    *,
    client: ModalClient | None,
) -> ModalConnectedProviderRegistry:
    resolved_client: ModalClient = (
        client if client is not None else DefaultModalClient()
    )
    environment: dict[str, str] = {}
    if config.hf_token is not None:
        environment["HF_TOKEN"] = config.hf_token
    adapter = ModalProviderAdapter(
        client=resolved_client,
        region=Region(_DEFAULT_MODAL_REGION),
        web_url_3b=config.web_url_3b,
        web_url_7b=config.web_url_7b,
        environment=environment,
    )
    return ModalConnectedProviderRegistry(
        adapter=adapter,
        account_id=ProviderAccountId(config.workspace),
        region=Region(_DEFAULT_MODAL_REGION),
    )


__all__ = [
    "EmptyProviderRegistry",
    "build_default_provider_registry",
]
