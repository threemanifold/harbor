"""Composition root: build the dependency bag for the Harbor backend.

This is the only module allowed to know about every layer; the
:mod:`import-linter` ``Onion layers`` contract enforces that. ``build_container``
wires the default application services, the in-memory infrastructure adapters,
and a :class:`CreateDeployment` use-case instance into a single immutable
``Container`` for the HTTP layer / tests to consume.

The provider registry is the one externally-injectable seam: when omitted,
:func:`build_default_provider_registry` consults the process env and either
wires the Modal-backed registry (if ``MODAL_TOKEN_ID`` etc. are set) or falls
back to :class:`EmptyProviderRegistry`. Tests supply their own registry
directly.
"""

from __future__ import annotations

from dataclasses import dataclass

from harbor.application.services.placement_policy import DefaultPlacementPolicy
from harbor.application.services.recipe_compiler import DefaultRecipeCompiler
from harbor.application.services.resource_resolver import DefaultResourceResolver
from harbor.application.use_cases.create_deployment import CreateDeployment
from harbor.composition.ids import UuidIdFactory
from harbor.composition.providers import (
    EmptyProviderRegistry,
    build_default_provider_registry,
)
from harbor.domain.ports.clock import Clock
from harbor.domain.ports.deployment_repository import DeploymentRepository
from harbor.domain.ports.event_bus import EventBus
from harbor.domain.ports.id_factory import IdFactory
from harbor.domain.ports.model_catalog import ModelCatalog
from harbor.domain.ports.provider_registry import ConnectedProviderRegistry
from harbor.domain.services.placement_policy import PlacementPolicy
from harbor.domain.services.recipe_compiler import RecipeCompiler
from harbor.domain.services.resource_resolver import ResourceResolver
from harbor.infrastructure.catalog.static import StaticModelCatalog
from harbor.infrastructure.clock.system import SystemClock
from harbor.infrastructure.eventing.memory import InMemoryEventBus
from harbor.infrastructure.persistence.memory import InMemoryDeploymentRepository

__all__ = [
    "Container",
    "EmptyProviderRegistry",
    "build_container",
]


@dataclass(frozen=True, slots=True)
class Container:
    """Immutable bag of singletons produced by :func:`build_container`.

    The HTTP layer (SYM-212) reaches for ``create_deployment``; other ports
    are exposed for tests and future use cases. All fields are typed by the
    domain port / strategy protocol — never by the concrete implementation —
    so swapping implementations is a one-line change in this module.
    """

    clock: Clock
    catalog: ModelCatalog
    id_factory: IdFactory
    compiler: RecipeCompiler
    resolver: ResourceResolver
    policy: PlacementPolicy
    providers: ConnectedProviderRegistry
    repo: DeploymentRepository
    bus: EventBus
    create_deployment: CreateDeployment


def build_container(
    *,
    providers: ConnectedProviderRegistry | None = None,
) -> Container:
    """Wire the default Harbor backend.

    Parameters
    ----------
    providers:
        Optional connected-provider registry. When ``None``,
        :func:`build_default_provider_registry` inspects the process env: if
        Modal credentials are configured it returns
        :class:`ModalConnectedProviderRegistry`, otherwise it falls back to
        :class:`EmptyProviderRegistry` (handy for the ``/health`` smoke test
        and integration tests that don't need real provisioning).
    """

    clock: Clock = SystemClock()
    catalog: ModelCatalog = StaticModelCatalog.qwen_default()
    id_factory: IdFactory = UuidIdFactory()
    compiler: RecipeCompiler = DefaultRecipeCompiler()
    resolver: ResourceResolver = DefaultResourceResolver()
    policy: PlacementPolicy = DefaultPlacementPolicy()
    repo: DeploymentRepository = InMemoryDeploymentRepository()
    bus: EventBus = InMemoryEventBus()
    registry: ConnectedProviderRegistry = (
        providers if providers is not None else build_default_provider_registry()
    )

    create_deployment = CreateDeployment(
        catalog=catalog,
        compiler=compiler,
        resolver=resolver,
        policy=policy,
        providers=registry,
        repo=repo,
        bus=bus,
        clock=clock,
        id_factory=id_factory,
    )

    return Container(
        clock=clock,
        catalog=catalog,
        id_factory=id_factory,
        compiler=compiler,
        resolver=resolver,
        policy=policy,
        providers=registry,
        repo=repo,
        bus=bus,
        create_deployment=create_deployment,
    )
