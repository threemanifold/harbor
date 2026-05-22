from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Protocol

from harbor.domain.endpoint import Endpoint
from harbor.domain.placement import Feasibility, Placement, ProviderKind
from harbor.domain.provider_plan import ProviderPlan, ProvisionHandle
from harbor.domain.recipe import Recipe
from harbor.domain.resources import ResourceSpec


@dataclass(frozen=True, slots=True)
class ProvisioningStarted:
    handle: ProvisionHandle


@dataclass(frozen=True, slots=True)
class ProvisioningProgress:
    percent: int
    message: str


@dataclass(frozen=True, slots=True)
class InfrastructureReady:
    """Infra exists; container is booting / model is loading."""


@dataclass(frozen=True, slots=True)
class EndpointReady:
    endpoint: Endpoint


@dataclass(frozen=True, slots=True)
class ProvisionFailed:
    reason: str


ProvisionEvent = (
    ProvisioningStarted
    | ProvisioningProgress
    | InfrastructureReady
    | EndpointReady
    | ProvisionFailed
)


class ProviderAdapter(Protocol):
    kind: ProviderKind

    async def feasibility(self, recipe: Recipe, spec: ResourceSpec) -> Feasibility: ...

    async def plan(self, recipe: Recipe, placement: Placement) -> ProviderPlan: ...

    def provision(self, plan: ProviderPlan) -> AsyncIterator[ProvisionEvent]: ...

    async def teardown(self, handle: ProvisionHandle) -> None: ...
