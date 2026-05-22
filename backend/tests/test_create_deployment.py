from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal

from harbor.application.use_cases.create_deployment import CreateDeployment
from harbor.domain.catalog import ModelEntry, ModelRef, WeightsDtype
from harbor.domain.deployment import Deployment, DeploymentState
from harbor.domain.endpoint import BearerToken, Endpoint
from harbor.domain.errors import NoFeasibleProvider
from harbor.domain.events import (
    DeploymentCompiled,
    DeploymentEvent,
    DeploymentFailed,
    DeploymentHealthy,
    DeploymentPlaced,
    DeploymentProvisioning,
    DeploymentRequested,
    DeploymentStarting,
    DeploymentTerminated,
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
from harbor.domain.provider_plan import ProviderPlan, ProvisionHandle
from harbor.domain.ports.provider_adapter import (
    EndpointReady,
    InfrastructureReady,
    ProvisionEvent,
    ProvisionFailed,
    ProvisioningProgress,
    ProvisioningStarted,
)
from harbor.domain.recipe import (
    HuggingFaceHub,
    Quantization,
    Recipe,
    Runtime,
    ServingPolicy,
)
from harbor.domain.resources import (
    AcceleratorClass,
    AcceleratorOption,
    ResourceSpec,
    RuntimeImage,
)
from harbor.domain.workflow import (
    Priority,
    Tuning,
    WorkflowRequest,
    WorkflowType,
)

# ---------- Builders for canonical domain values ----------

T0 = datetime(2026, 5, 22, 12, 0, 0, tzinfo=UTC)
TEAM = TeamId("team_1")
OWNER = OwnerId("user_1")
MODEL = ModelRef(identifier="qwen/qwen2.5-coder-32b-instruct")


def _request() -> WorkflowRequest:
    return WorkflowRequest(
        model_ref=MODEL,
        workflow_type=WorkflowType.CHAT,
        tuning=Tuning(priority=Priority.QUALITY),
    )


def _entry() -> ModelEntry:
    return ModelEntry(
        ref=MODEL,
        parameters_billion=32.0,
        native_dtype=WeightsDtype.BF16,
        max_context=32_768,
        weights_size_gb=64.0,
    )


def _recipe() -> Recipe:
    return Recipe(
        model=MODEL,
        runtime=Runtime.VLLM,
        weights_dtype=WeightsDtype.BF16,
        quantization=Quantization.NONE,
        context_len=32_768,
        artifact_source=HuggingFaceHub(repo=MODEL.identifier),
        serving=ServingPolicy(tensor_parallel=2),
        tuning=Tuning(priority=Priority.QUALITY),
    )


def _spec() -> ResourceSpec:
    return ResourceSpec(
        accelerator_options=(
            AcceleratorOption(
                accelerators=(AcceleratorClass(name="H100", memory_gb=80),)
            ),
        ),
        cpu_min=16,
        ram_min_gb=64,
        disk_min_gb=200,
        image=RuntimeImage(reference="vllm/vllm-openai:latest"),
    )


def _target(account: str = "acc_1") -> ProviderTarget:
    return ProviderTarget(
        kind=ProviderKind.MODAL,
        account_id=ProviderAccountId(account),
        region=Region("us-east"),
    )


def _accel_choice() -> AcceleratorOption:
    return AcceleratorOption(
        accelerators=(AcceleratorClass(name="H100", memory_gb=80),)
    )


def _placement(target: ProviderTarget) -> Placement:
    return Placement(
        target=target,
        accelerator_choice=_accel_choice(),
        region=target.region,
        cost_estimate=Cost(amount=Decimal("3.50")),
    )


def _feasibility_ok() -> Feasibility:
    return Feasibility(
        ok=True,
        chosen_option=_accel_choice(),
        region=Region("us-east"),
        cost_estimate=Cost(amount=Decimal("3.50")),
        reasons=(),
    )


def _feasibility_no(reason: str) -> Feasibility:
    return Feasibility(
        ok=False,
        chosen_option=None,
        region=None,
        cost_estimate=None,
        reasons=(reason,),
    )


def _endpoint() -> Endpoint:
    return Endpoint(
        url="https://harbor-1.modal.run/v1",
        auth=BearerToken(value="tok"),
        openai_compatible=True,
    )


# ---------- Fakes ----------


class FakeClock:
    def __init__(self, t: datetime = T0) -> None:
        self._t = t

    def now(self) -> datetime:
        return self._t


class FakeIdFactory:
    def __init__(self) -> None:
        self._counter = 0

    def new_deployment_id(self) -> DeploymentId:
        self._counter += 1
        return DeploymentId(f"dep_{self._counter}")


class FakeCatalog:
    def __init__(self, entries: dict[ModelRef, ModelEntry]) -> None:
        self._entries = entries

    async def get(self, ref: ModelRef) -> ModelEntry | None:
        return self._entries.get(ref)


class FakeCompiler:
    def __init__(self, recipe: Recipe) -> None:
        self._recipe = recipe

    def compile(self, request: WorkflowRequest, entry: ModelEntry) -> Recipe:
        return self._recipe


class FakeResolver:
    def __init__(self, spec: ResourceSpec) -> None:
        self._spec = spec

    def resolve(self, recipe: Recipe) -> ResourceSpec:
        return self._spec


class FirstFeasiblePolicy:
    """Picks the first candidate whose Feasibility.ok is True."""

    def select(
        self,
        *,
        recipe: Recipe,
        spec: ResourceSpec,
        candidates: tuple[tuple[ProviderTarget, Feasibility], ...],
    ) -> Placement:
        for target, feas in candidates:
            if feas.ok:
                assert feas.chosen_option is not None
                assert feas.region is not None
                assert feas.cost_estimate is not None
                return Placement(
                    target=target,
                    accelerator_choice=feas.chosen_option,
                    region=feas.region,
                    cost_estimate=feas.cost_estimate,
                )
        raise NoFeasibleProvider(
            reasons=tuple(r for _, f in candidates for r in f.reasons)
        )


@dataclass
class _AdapterScript:
    feasibility: Feasibility
    provision_events: tuple[ProvisionEvent, ...] = ()


class FakeProviderAdapter:
    kind: ProviderKind = ProviderKind.MODAL

    def __init__(self, script: _AdapterScript) -> None:
        self._script = script
        self.plan_calls = 0
        self.teardown_calls = 0

    async def feasibility(self, recipe: Recipe, spec: ResourceSpec) -> Feasibility:
        return self._script.feasibility

    async def plan(self, recipe: Recipe, placement: Placement) -> ProviderPlan:
        self.plan_calls += 1
        return ProviderPlan(target=placement.target, payload={"fake": True})

    async def provision(self, plan: ProviderPlan) -> AsyncIterator[ProvisionEvent]:
        for event in self._script.provision_events:
            yield event

    async def teardown(self, handle: ProvisionHandle) -> None:
        self.teardown_calls += 1


class FakeRegistry:
    def __init__(
        self, targets: list[tuple[ProviderTarget, FakeProviderAdapter]]
    ) -> None:
        self._targets = targets

    async def list_targets(
        self, team: TeamId
    ) -> tuple[tuple[ProviderTarget, FakeProviderAdapter], ...]:
        return tuple(self._targets)


class FakeRepo:
    def __init__(self) -> None:
        self.saved_states: list[DeploymentState] = []
        self._latest: dict[DeploymentId, Deployment] = {}

    async def save(self, deployment: Deployment) -> None:
        self.saved_states.append(deployment.state)
        self._latest[deployment.id] = deployment

    async def get(self, deployment_id: DeploymentId) -> Deployment | None:
        return self._latest.get(deployment_id)

    async def list_for_team(self, team: TeamId) -> tuple[Deployment, ...]:
        return tuple(d for d in self._latest.values() if d.team == team)


@dataclass
class FakeBus:
    published: list[DeploymentEvent] = field(default_factory=list)

    async def publish(self, event: DeploymentEvent) -> None:
        self.published.append(event)

    def subscribe(self, deployment_id: DeploymentId) -> AsyncIterator[DeploymentEvent]:
        raise NotImplementedError("subscribe not used in these tests")


# ---------- Wiring helper ----------


def _wire(
    *,
    catalog_entries: dict[ModelRef, ModelEntry] | None = None,
    targets: list[tuple[ProviderTarget, FakeProviderAdapter]] | None = None,
    recipe: Recipe | None = None,
    spec: ResourceSpec | None = None,
) -> tuple[CreateDeployment, FakeRepo, FakeBus]:
    repo = FakeRepo()
    bus = FakeBus()
    # Explicit None checks — empty dict / list are falsy and would silently
    # fall through to the default.
    entries = catalog_entries if catalog_entries is not None else {MODEL: _entry()}
    target_list = targets if targets is not None else []
    use_case = CreateDeployment(
        catalog=FakeCatalog(entries),
        compiler=FakeCompiler(recipe or _recipe()),
        resolver=FakeResolver(spec or _spec()),
        policy=FirstFeasiblePolicy(),
        providers=FakeRegistry(target_list),
        repo=repo,
        bus=bus,
        clock=FakeClock(),
        id_factory=FakeIdFactory(),
    )
    return use_case, repo, bus


# ---------- Tests ----------


async def test_happy_path_ends_healthy_with_endpoint() -> None:
    target = _target()
    adapter = FakeProviderAdapter(
        _AdapterScript(
            feasibility=_feasibility_ok(),
            provision_events=(
                ProvisioningStarted(
                    handle=ProvisionHandle(target=target, reference="r1")
                ),
                ProvisioningProgress(percent=40, message="downloading"),
                InfrastructureReady(),
                ProvisioningProgress(percent=90, message="loading"),
                EndpointReady(endpoint=_endpoint()),
            ),
        )
    )
    use_case, repo, bus = _wire(targets=[(target, adapter)])

    deployment_id = await use_case.execute(request=_request(), owner=OWNER, team=TEAM)

    dep = await repo.get(deployment_id)
    assert dep is not None
    assert dep.state == DeploymentState.HEALTHY
    assert dep.endpoint == _endpoint()
    assert dep.recipe == _recipe()
    assert dep.placement is not None and dep.placement.target == target
    assert adapter.plan_calls == 1

    published_types = [type(e) for e in bus.published]
    assert DeploymentRequested in published_types
    assert DeploymentCompiled in published_types
    assert DeploymentPlaced in published_types
    assert DeploymentProvisioning in published_types
    assert DeploymentStarting in published_types
    assert DeploymentHealthy in published_types

    # Each transition triggers a save; final saved state is HEALTHY.
    assert repo.saved_states[0] == DeploymentState.REQUESTED
    assert repo.saved_states[-1] == DeploymentState.HEALTHY


async def test_model_not_found_marks_failed() -> None:
    use_case, repo, bus = _wire(catalog_entries={})  # empty catalog

    deployment_id = await use_case.execute(request=_request(), owner=OWNER, team=TEAM)

    dep = await repo.get(deployment_id)
    assert dep is not None
    assert dep.state == DeploymentState.FAILED
    assert dep.failure_reason is not None
    assert "Model not found" in dep.failure_reason

    final_event = bus.published[-1]
    assert isinstance(final_event, DeploymentFailed)


async def test_no_providers_connected_marks_failed() -> None:
    use_case, repo, bus = _wire(targets=[])  # no providers

    deployment_id = await use_case.execute(request=_request(), owner=OWNER, team=TEAM)

    dep = await repo.get(deployment_id)
    assert dep is not None
    assert dep.state == DeploymentState.FAILED
    assert dep.failure_reason is not None
    assert "No providers" in dep.failure_reason


async def test_no_feasible_provider_marks_failed() -> None:
    target = _target()
    adapter = FakeProviderAdapter(
        _AdapterScript(feasibility=_feasibility_no("quota exceeded"))
    )
    use_case, repo, bus = _wire(targets=[(target, adapter)])

    deployment_id = await use_case.execute(request=_request(), owner=OWNER, team=TEAM)

    dep = await repo.get(deployment_id)
    assert dep is not None
    assert dep.state == DeploymentState.FAILED
    # Policy was called (since at least one candidate existed) and raised.
    assert dep.failure_reason is not None


async def test_provision_failed_event_marks_failed_after_placed() -> None:
    target = _target()
    adapter = FakeProviderAdapter(
        _AdapterScript(
            feasibility=_feasibility_ok(),
            provision_events=(
                ProvisioningStarted(
                    handle=ProvisionHandle(target=target, reference="r2")
                ),
                ProvisionFailed(reason="image pull failed"),
            ),
        )
    )
    use_case, repo, bus = _wire(targets=[(target, adapter)])

    deployment_id = await use_case.execute(request=_request(), owner=OWNER, team=TEAM)

    dep = await repo.get(deployment_id)
    assert dep is not None
    assert dep.state == DeploymentState.FAILED
    assert dep.failure_reason == "image pull failed"
    # We did reach the Provisioning state before failing.
    states = repo.saved_states
    assert DeploymentState.PROVISIONING in states


async def test_first_feasible_target_is_chosen_when_one_is_infeasible() -> None:
    bad_target = _target("acc_bad")
    good_target = ProviderTarget(
        kind=ProviderKind.MODAL,
        account_id=ProviderAccountId("acc_good"),
        region=Region("us-east"),
    )
    bad_adapter = FakeProviderAdapter(
        _AdapterScript(feasibility=_feasibility_no("no quota"))
    )
    good_adapter = FakeProviderAdapter(
        _AdapterScript(
            feasibility=_feasibility_ok(),
            provision_events=(
                ProvisioningStarted(
                    handle=ProvisionHandle(target=good_target, reference="r3")
                ),
                InfrastructureReady(),
                EndpointReady(endpoint=_endpoint()),
            ),
        )
    )
    use_case, repo, _ = _wire(
        targets=[(bad_target, bad_adapter), (good_target, good_adapter)]
    )

    deployment_id = await use_case.execute(request=_request(), owner=OWNER, team=TEAM)

    dep = await repo.get(deployment_id)
    assert dep is not None
    assert dep.state == DeploymentState.HEALTHY
    assert dep.placement is not None
    assert dep.placement.target == good_target
    assert good_adapter.plan_calls == 1
    assert bad_adapter.plan_calls == 0


# Silence "unused" warnings on imports kept for type clarity in fakes.
_KEEP = (DeploymentTerminated,)
