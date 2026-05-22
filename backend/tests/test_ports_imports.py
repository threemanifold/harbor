from harbor.domain.ports.clock import Clock
from harbor.domain.ports.deployment_repository import DeploymentRepository
from harbor.domain.ports.event_bus import EventBus
from harbor.domain.ports.model_catalog import ModelCatalog
from harbor.domain.ports.provider_adapter import (
    EndpointReady,
    InfrastructureReady,
    ProviderAdapter,
    ProvisionEvent,
    ProvisionFailed,
    ProvisioningProgress,
    ProvisioningStarted,
)
from harbor.domain.ports.provider_registry import ConnectedProviderRegistry
from harbor.domain.services.placement_policy import PlacementPolicy
from harbor.domain.services.recipe_compiler import RecipeCompiler
from harbor.domain.services.resource_resolver import ResourceResolver


def test_ports_and_services_are_importable() -> None:
    # Touch each symbol so an accidental rename breaks the test rather than
    # silently leaving a dangling import elsewhere.
    assert Clock.__name__ == "Clock"
    assert DeploymentRepository.__name__ == "DeploymentRepository"
    assert EventBus.__name__ == "EventBus"
    assert ModelCatalog.__name__ == "ModelCatalog"
    assert ProviderAdapter.__name__ == "ProviderAdapter"
    assert ConnectedProviderRegistry.__name__ == "ConnectedProviderRegistry"
    assert PlacementPolicy.__name__ == "PlacementPolicy"
    assert RecipeCompiler.__name__ == "RecipeCompiler"
    assert ResourceResolver.__name__ == "ResourceResolver"


def test_provision_event_variants_match_union() -> None:
    variants = (
        ProvisioningStarted,
        ProvisioningProgress,
        InfrastructureReady,
        EndpointReady,
        ProvisionFailed,
    )
    # Union members exist as classes; sanity check.
    for variant in variants:
        assert isinstance(variant, type)
    # ProvisionEvent itself is a typing union, not a class.
    assert ProvisionEvent is not None
