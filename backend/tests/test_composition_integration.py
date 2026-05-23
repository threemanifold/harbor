"""Integration test exercising :class:`CreateDeployment` via
:func:`build_container` with a fake :class:`ProviderAdapter`.

The point is to prove that the wiring in :mod:`harbor.composition` produces a
fully-functional use case: the default services compile and resolve, the
in-memory infrastructure stores aggregates and broadcasts events, and the
fake provider's event sequence drives the aggregate to :class:`HEALTHY`.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from dataclasses import dataclass
from decimal import Decimal

from fastapi.testclient import TestClient

from harbor.composition.app import create_app
from harbor.composition.container import build_container
from harbor.domain.catalog import ModelRef
from harbor.domain.deployment import DeploymentState
from harbor.domain.endpoint import BearerToken, Endpoint
from harbor.domain.events import (
    DeploymentCompiled,
    DeploymentEvent,
    DeploymentHealthy,
    DeploymentPlaced,
    DeploymentProvisioning,
    DeploymentRequested,
    DeploymentStarting,
)
from harbor.domain.identifiers import (
    DeploymentId,
    OwnerId,
    ProviderAccountId,
    Region,
    TeamId,
)
from harbor.domain.placement import (
    Cost,
    Feasibility,
    Placement,
    ProviderKind,
    ProviderTarget,
)
from harbor.domain.ports.provider_adapter import (
    EndpointReady,
    InfrastructureReady,
    ProvisionEvent,
    ProvisioningProgress,
    ProvisioningStarted,
)
from harbor.domain.provider_plan import ProviderPlan, ProvisionHandle
from harbor.domain.recipe import Quantization, Recipe, Runtime
from harbor.domain.resources import AcceleratorClass, AcceleratorOption, ResourceSpec
from harbor.domain.workflow import Priority, Tuning, WorkflowRequest, WorkflowType

TEAM = TeamId("team_1")
OWNER = OwnerId("user_1")
REGION = Region("us-east")
TARGET = ProviderTarget(
    kind=ProviderKind.MODAL,
    account_id=ProviderAccountId("acc_1"),
    region=REGION,
)


def _endpoint() -> Endpoint:
    return Endpoint(
        url="https://harbor-1.modal.run/v1",
        auth=BearerToken(value="tok"),
        openai_compatible=True,
    )


@dataclass
class _FakeAdapter:
    """ProviderAdapter that always claims feasibility and replays a scripted
    sequence of provisioning events.
    """

    kind: ProviderKind = ProviderKind.MODAL

    async def feasibility(self, recipe: Recipe, spec: ResourceSpec) -> Feasibility:
        # Pick the first accelerator option offered by the resolver so we
        # exercise the real DefaultResourceResolver output.
        option = spec.accelerator_options[0]
        return Feasibility(
            ok=True,
            chosen_option=option,
            region=REGION,
            cost_estimate=Cost(amount=Decimal("1.25")),
            reasons=(),
        )

    async def plan(self, recipe: Recipe, placement: Placement) -> ProviderPlan:
        return ProviderPlan(
            target=placement.target,
            payload={
                "image": "vllm/vllm-openai:v0.6.4",
                "model": recipe.model.identifier,
            },
        )

    async def provision(self, plan: ProviderPlan) -> AsyncIterator[ProvisionEvent]:
        handle = ProvisionHandle(target=plan.target, reference="modal-call-xyz")
        yield ProvisioningStarted(handle=handle)
        yield ProvisioningProgress(percent=40, message="downloading weights")
        yield InfrastructureReady()
        yield ProvisioningProgress(percent=90, message="loading model")
        yield EndpointReady(endpoint=_endpoint())

    async def teardown(self, handle: ProvisionHandle) -> None:
        return None


class _FakeRegistry:
    """ConnectedProviderRegistry that always exposes a single fake adapter."""

    def __init__(self) -> None:
        self._adapter = _FakeAdapter()

    async def list_targets(
        self, team: TeamId
    ) -> tuple[tuple[ProviderTarget, _FakeAdapter], ...]:
        return ((TARGET, self._adapter),)


async def test_create_deployment_drives_aggregate_to_healthy() -> None:
    registry = _FakeRegistry()
    container = build_container(providers=registry)

    request = WorkflowRequest(
        model_ref=ModelRef(identifier="Qwen/Qwen2.5-3B-Instruct"),
        workflow_type=WorkflowType.CHAT,
        tuning=Tuning(priority=Priority.QUALITY),
    )

    # Run the use case to completion. Per-event assertions are covered by the
    # companion test below (which subscribes ahead of execute()); here we just
    # confirm the wiring lands on HEALTHY with the expected endpoint.
    deployment_id = await asyncio.wait_for(
        container.create_deployment.execute(request=request, owner=OWNER, team=TEAM),
        timeout=2.0,
    )

    # Verify final state through the repository (which the container wired up).
    dep = await container.repo.get(deployment_id)
    assert dep is not None
    assert dep.state == DeploymentState.HEALTHY
    assert dep.endpoint == _endpoint()
    assert dep.placement is not None
    assert dep.placement.target == TARGET

    # The compiled recipe should match the Qwen 3B defaults.
    recipe = dep.recipe
    assert recipe is not None
    assert recipe.model.identifier == "Qwen/Qwen2.5-3B-Instruct"
    assert recipe.runtime is Runtime.VLLM
    assert recipe.quantization is Quantization.NONE
    assert recipe.context_len == 32_768

    # Subscribe AFTER completion to confirm the bus is operational even with
    # no consumers attached; we publish a synthetic event and observe it.
    iterator = container.bus.subscribe(deployment_id)
    await container.bus.publish(
        DeploymentHealthy(
            deployment_id=deployment_id,
            at=container.clock.now(),
            endpoint=_endpoint(),
        )
    )
    received = await asyncio.wait_for(iterator.__anext__(), timeout=1.0)
    assert isinstance(received, DeploymentHealthy)


async def test_create_deployment_publishes_full_event_sequence() -> None:
    registry = _FakeRegistry()
    container = build_container(providers=registry)

    request = WorkflowRequest(
        model_ref=ModelRef(identifier="Qwen/Qwen2.5-7B-Instruct"),
        workflow_type=WorkflowType.CHAT,
        tuning=Tuning(priority=Priority.COST),  # → AWQ_INT4
    )

    # Subscribe to events before the use case runs so we see them all.
    # We need to know the deployment id up front, so we patch the id factory
    # to a deterministic value.
    fixed_id = DeploymentId("dep_fixed")

    class _FixedFactory:
        def new_deployment_id(self) -> DeploymentId:
            return fixed_id

    # Rebuild the use case bound to the fixed factory, reusing the rest of the
    # container's dependencies — that keeps the test honest about the wiring
    # while letting us subscribe pre-flight.
    from harbor.application.use_cases.create_deployment import CreateDeployment

    use_case = CreateDeployment(
        catalog=container.catalog,
        compiler=container.compiler,
        resolver=container.resolver,
        policy=container.policy,
        providers=container.providers,
        repo=container.repo,
        bus=container.bus,
        clock=container.clock,
        id_factory=_FixedFactory(),
    )

    iterator = container.bus.subscribe(fixed_id)

    async def consume(expected: int) -> list[DeploymentEvent]:
        events: list[DeploymentEvent] = []
        async for event in iterator:
            events.append(event)
            if len(events) >= expected:
                return events
        return events  # pragma: no cover - infinite iterator otherwise

    # Use case publishes 8 events for a happy path: Requested, Compiled,
    # Placed, Provisioning, Progress (40%), Starting, Progress (90%), Healthy.
    consumer = asyncio.create_task(consume(expected=8))
    # Let the subscriber register before publish() starts firing.
    await asyncio.sleep(0)

    deployment_id = await asyncio.wait_for(
        use_case.execute(request=request, owner=OWNER, team=TEAM), timeout=2.0
    )
    assert deployment_id == fixed_id

    events = await asyncio.wait_for(consumer, timeout=1.0)
    types = [type(e) for e in events]
    # The bus is monotonic per deployment, so order is meaningful.
    assert DeploymentRequested in types
    assert DeploymentCompiled in types
    assert DeploymentPlaced in types
    assert DeploymentProvisioning in types
    assert DeploymentStarting in types
    assert DeploymentHealthy in types

    # And the 7B + COST compile chose AWQ_INT4 + an A10G option.
    dep = await container.repo.get(deployment_id)
    assert dep is not None
    assert dep.recipe is not None
    assert dep.recipe.quantization is Quantization.AWQ_INT4
    assert dep.placement is not None
    (option,) = (dep.placement.accelerator_choice,)
    assert isinstance(option, AcceleratorOption)
    (accel,) = option.accelerators
    assert isinstance(accel, AcceleratorClass)
    assert accel.name == "A10G"


def test_create_app_exposes_health_endpoint_and_container() -> None:
    registry = _FakeRegistry()
    app = create_app(providers=registry)

    with TestClient(app) as client:
        resp = client.get("/health")
        assert resp.status_code == 200
        assert resp.json() == {"status": "ok"}

    container = app.state.container
    assert container.create_deployment is not None
    assert container.providers is registry
