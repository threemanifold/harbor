"""Tests for :class:`ModalConnectedProviderRegistry` and the composition
fallback that selects between the Modal-backed registry and the empty stub.
"""

from __future__ import annotations

from harbor.composition.providers import (
    EmptyProviderRegistry,
    build_default_provider_registry,
)
from harbor.domain.identifiers import ProviderAccountId, Region, TeamId
from harbor.domain.placement import ProviderKind, ProviderTarget
from harbor.infrastructure.providers.modal.adapter import ModalProviderAdapter
from harbor.infrastructure.providers.modal.client import (
    ModalFunctionRef,
    ModalLookupError,
)
from harbor.infrastructure.providers.modal.registry import (
    ModalConnectedProviderRegistry,
)


class _StaticClient:
    """ModalClient stand-in used to construct an adapter without network."""

    async def lookup_function(
        self, *, app_name: str, function_name: str
    ) -> ModalFunctionRef:
        raise ModalLookupError("static client")

    async def health_check(self, *, web_url: str) -> bool:
        return False

    async def stop_function(self, *, app_name: str, function_name: str) -> None:
        return None


def _adapter() -> ModalProviderAdapter:
    return ModalProviderAdapter(client=_StaticClient(), region=Region("modal-default"))


# ---- ModalConnectedProviderRegistry ---------------------------------------


async def test_registry_returns_single_modal_target() -> None:
    registry = ModalConnectedProviderRegistry(
        adapter=_adapter(),
        account_id=ProviderAccountId("harbor-team"),
        region=Region("modal-default"),
    )
    targets = await registry.list_targets(TeamId("team-1"))
    assert len(targets) == 1
    (target, adapter) = targets[0]
    assert isinstance(target, ProviderTarget)
    assert target.kind is ProviderKind.MODAL
    assert target.account_id == "harbor-team"
    assert target.region == "modal-default"
    assert isinstance(adapter, ModalProviderAdapter)


async def test_registry_is_team_agnostic_in_this_slice() -> None:
    # SYM-211 returns the same target for every team; documents the
    # invariant so a future split (per-team credentials) breaks loudly.
    registry = ModalConnectedProviderRegistry(
        adapter=_adapter(),
        account_id=ProviderAccountId("harbor-team"),
        region=Region("modal-default"),
    )
    a = await registry.list_targets(TeamId("team-a"))
    b = await registry.list_targets(TeamId("team-b"))
    assert a == b


# ---- build_default_provider_registry --------------------------------------


def test_default_registry_is_empty_without_modal_env() -> None:
    registry = build_default_provider_registry(env={})
    assert isinstance(registry, EmptyProviderRegistry)


def test_default_registry_is_modal_when_env_is_set() -> None:
    env = {
        "MODAL_TOKEN_ID": "tok-id",
        "MODAL_TOKEN_SECRET": "tok-secret",
        "MODAL_WORKSPACE": "harbor-team",
        "MODAL_WEB_URL_3B": "https://harbor--qwen-3b.modal.run",
        "MODAL_WEB_URL_7B": "https://harbor--qwen-7b.modal.run",
    }
    registry = build_default_provider_registry(env=env, client=_StaticClient())
    assert isinstance(registry, ModalConnectedProviderRegistry)
    assert registry.target.kind is ProviderKind.MODAL
    assert registry.target.account_id == "harbor-team"


async def test_modal_registry_from_env_yields_single_target() -> None:
    env = {
        "MODAL_TOKEN_ID": "tok-id",
        "MODAL_TOKEN_SECRET": "tok-secret",
        "MODAL_WORKSPACE": "harbor-team",
    }
    registry = build_default_provider_registry(env=env, client=_StaticClient())
    targets = await registry.list_targets(TeamId("team-1"))
    assert len(targets) == 1
    (target, _adapter_obj) = targets[0]
    assert target.kind is ProviderKind.MODAL
