from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from harbor.domain.catalog import ModelRef, WeightsDtype
from harbor.domain.deployment import Deployment, DeploymentState
from harbor.domain.endpoint import BearerToken, Endpoint
from harbor.domain.errors import InvalidStateTransition
from harbor.domain.events import (
    DeploymentCompiled,
    DeploymentFailed,
    DeploymentHealthy,
    DeploymentPlaced,
    DeploymentProgress,
    DeploymentProvisioning,
    DeploymentRequested,
    DeploymentStarting,
    DeploymentTerminated,
    DeploymentTerminating,
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
    Placement,
    ProviderKind,
    ProviderTarget,
)
from harbor.domain.provider_plan import ProviderPlan, ProvisionHandle
from harbor.domain.recipe import (
    HuggingFaceHub,
    Quantization,
    Recipe,
    Runtime,
    ServingPolicy,
)
from harbor.domain.resources import AcceleratorClass, AcceleratorOption
from harbor.domain.workflow import (
    Priority,
    Tuning,
    WorkflowRequest,
    WorkflowType,
)

T0 = datetime(2026, 5, 22, 12, 0, 0, tzinfo=UTC)


def _tick(seconds: int) -> datetime:
    return T0 + timedelta(seconds=seconds)


def _request() -> WorkflowRequest:
    return WorkflowRequest(
        model_ref=ModelRef(identifier="qwen/qwen2.5-coder-32b-instruct"),
        workflow_type=WorkflowType.CHAT,
        tuning=Tuning(priority=Priority.QUALITY),
    )


def _recipe() -> Recipe:
    return Recipe(
        model=ModelRef(identifier="qwen/qwen2.5-coder-32b-instruct"),
        runtime=Runtime.VLLM,
        weights_dtype=WeightsDtype.BF16,
        quantization=Quantization.NONE,
        context_len=32_768,
        artifact_source=HuggingFaceHub(repo="qwen/qwen2.5-coder-32b-instruct"),
        serving=ServingPolicy(tensor_parallel=2),
        tuning=Tuning(priority=Priority.QUALITY),
    )


def _target() -> ProviderTarget:
    return ProviderTarget(
        kind=ProviderKind.MODAL,
        account_id=ProviderAccountId("acc_1"),
        region=Region("us-east"),
    )


def _placement() -> Placement:
    target = _target()
    accel = AcceleratorOption(
        accelerators=(AcceleratorClass(name="H100", memory_gb=80),)
    )
    return Placement(
        target=target,
        accelerator_choice=accel,
        region=target.region,
        cost_estimate=Cost(amount=Decimal("3.50")),
    )


def _plan() -> ProviderPlan:
    return ProviderPlan(target=_target(), payload={"app": "harbor-modal-1"})


def _handle() -> ProvisionHandle:
    return ProvisionHandle(target=_target(), reference="modal-call-xyz")


def _endpoint() -> Endpoint:
    return Endpoint(
        url="https://harbor-1.modal.run/v1",
        auth=BearerToken(value="tok"),
        openai_compatible=True,
    )


def _new_deployment() -> Deployment:
    return Deployment.start(
        deployment_id=DeploymentId("dep_1"),
        owner=OwnerId("user_1"),
        team=TeamId("team_1"),
        request=_request(),
        now=T0,
    )


def test_start_creates_requested_with_event() -> None:
    dep = _new_deployment()
    assert dep.state == DeploymentState.REQUESTED
    assert dep.created_at == T0
    assert dep.updated_at == T0
    events = dep.pull_events()
    assert len(events) == 1
    assert isinstance(events[0], DeploymentRequested)


def test_pull_events_drains_buffer() -> None:
    dep = _new_deployment()
    assert len(dep.pull_events()) == 1
    assert dep.pull_events() == []


def test_happy_path_walks_full_state_machine() -> None:
    dep = _new_deployment()
    dep.pull_events()

    dep.compile_to(_recipe(), now=_tick(1))
    dep.place(_placement(), now=_tick(2))
    dep.start_provisioning(plan=_plan(), handle=_handle(), now=_tick(3))
    dep.report_progress(percent=40, message="downloading weights", now=_tick(4))
    dep.mark_starting(now=_tick(5))
    dep.report_progress(percent=90, message="loading model", now=_tick(6))
    dep.mark_healthy(_endpoint(), now=_tick(7))

    assert dep.state == DeploymentState.HEALTHY
    assert dep.endpoint == _endpoint()
    assert dep.recipe == _recipe()
    assert dep.placement == _placement()
    assert dep.plan == _plan()
    assert dep.updated_at == _tick(7)

    events = dep.pull_events()
    assert [type(e) for e in events] == [
        DeploymentCompiled,
        DeploymentPlaced,
        DeploymentProvisioning,
        DeploymentProgress,
        DeploymentStarting,
        DeploymentProgress,
        DeploymentHealthy,
    ]


def test_place_before_compile_rejected() -> None:
    dep = _new_deployment()
    with pytest.raises(InvalidStateTransition):
        dep.place(_placement(), now=_tick(1))


def test_mark_healthy_from_requested_rejected() -> None:
    dep = _new_deployment()
    with pytest.raises(InvalidStateTransition):
        dep.mark_healthy(_endpoint(), now=_tick(1))


def test_degraded_then_healthy_again() -> None:
    dep = _new_deployment()
    dep.compile_to(_recipe(), now=_tick(1))
    dep.place(_placement(), now=_tick(2))
    dep.start_provisioning(plan=_plan(), handle=_handle(), now=_tick(3))
    dep.mark_starting(now=_tick(4))
    dep.mark_healthy(_endpoint(), now=_tick(5))
    dep.mark_degraded(reason="probe failed", now=_tick(6))
    after_degraded = dep.state
    dep.mark_healthy(_endpoint(), now=_tick(7))
    after_recovery = dep.state
    assert after_degraded == DeploymentState.DEGRADED
    assert after_recovery == DeploymentState.HEALTHY


def test_failure_during_provisioning_records_reason() -> None:
    dep = _new_deployment()
    dep.compile_to(_recipe(), now=_tick(1))
    dep.place(_placement(), now=_tick(2))
    dep.start_provisioning(plan=_plan(), handle=_handle(), now=_tick(3))
    dep.mark_failed(reason="quota exceeded", now=_tick(4))
    assert dep.state == DeploymentState.FAILED
    assert dep.failure_reason == "quota exceeded"
    events = dep.pull_events()
    assert any(isinstance(e, DeploymentFailed) for e in events)


def test_terminal_states_reject_all_transitions() -> None:
    dep = _new_deployment()
    dep.mark_failed(reason="boom", now=_tick(1))
    assert dep.is_terminal
    with pytest.raises(InvalidStateTransition):
        dep.compile_to(_recipe(), now=_tick(2))
    with pytest.raises(InvalidStateTransition):
        dep.request_termination(now=_tick(3))
    with pytest.raises(InvalidStateTransition):
        dep.mark_failed(reason="again", now=_tick(4))


def test_termination_from_healthy_then_terminated() -> None:
    dep = _new_deployment()
    dep.compile_to(_recipe(), now=_tick(1))
    dep.place(_placement(), now=_tick(2))
    dep.start_provisioning(plan=_plan(), handle=_handle(), now=_tick(3))
    dep.mark_starting(now=_tick(4))
    dep.mark_healthy(_endpoint(), now=_tick(5))
    dep.request_termination(now=_tick(6))
    after_request = dep.state
    dep.mark_terminated(now=_tick(7))
    after_terminated = dep.state
    assert after_request == DeploymentState.TERMINATING
    assert after_terminated == DeploymentState.TERMINATED
    events = dep.pull_events()
    types = [type(e) for e in events]
    assert DeploymentTerminating in types
    assert DeploymentTerminated in types


def test_termination_is_idempotent_when_already_terminating() -> None:
    dep = _new_deployment()
    dep.compile_to(_recipe(), now=_tick(1))
    dep.request_termination(now=_tick(2))
    assert dep.state == DeploymentState.TERMINATING
    dep.request_termination(now=_tick(3))
    assert dep.state == DeploymentState.TERMINATING


def test_progress_outside_provisioning_or_starting_rejected() -> None:
    dep = _new_deployment()
    with pytest.raises(InvalidStateTransition):
        dep.report_progress(percent=10, message="x", now=_tick(1))


def test_progress_validates_percent_range() -> None:
    dep = _new_deployment()
    dep.compile_to(_recipe(), now=_tick(1))
    dep.place(_placement(), now=_tick(2))
    dep.start_provisioning(plan=_plan(), handle=_handle(), now=_tick(3))
    with pytest.raises(ValueError):
        dep.report_progress(percent=120, message="x", now=_tick(4))
    with pytest.raises(ValueError):
        dep.report_progress(percent=-1, message="x", now=_tick(4))
