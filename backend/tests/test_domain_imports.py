from dataclasses import FrozenInstanceError

import pytest

from harbor.domain.catalog import ModelEntry, ModelRef, WeightsDtype
from harbor.domain.endpoint import BearerToken, Endpoint
from harbor.domain.events import DeploymentRequested
from harbor.domain.identifiers import DeploymentId
from harbor.domain.placement import (
    Cost,
    CostGranularity,
    ProviderKind,
    ProviderTarget,
)
from harbor.domain.provider_plan import ProviderPlan
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
from harbor.domain.workflow import Priority, Tuning, WorkflowRequest, WorkflowType


def test_value_objects_are_frozen() -> None:
    ref = ModelRef(identifier="qwen/qwen2.5-coder-32b-instruct")
    with pytest.raises(FrozenInstanceError):
        ref.identifier = "other"  # type: ignore[misc]


def test_value_objects_compare_by_value() -> None:
    a = ModelRef(identifier="x")
    b = ModelRef(identifier="x")
    assert a == b


def test_recipe_composes_value_objects() -> None:
    model = ModelRef(identifier="qwen/qwen2.5-coder-32b-instruct")
    tuning = Tuning(priority=Priority.QUALITY)
    recipe = Recipe(
        model=model,
        runtime=Runtime.VLLM,
        weights_dtype=WeightsDtype.BF16,
        quantization=Quantization.NONE,
        context_len=32_768,
        artifact_source=HuggingFaceHub(repo=model.identifier),
        serving=ServingPolicy(tensor_parallel=2, replicas=1),
        tuning=tuning,
    )
    assert recipe.tuning.priority is Priority.QUALITY
    assert recipe.serving.tensor_parallel == 2


def test_event_carries_deployment_id() -> None:
    from datetime import UTC, datetime

    evt = DeploymentRequested(
        deployment_id=DeploymentId("dep_123"),
        at=datetime.now(UTC),
    )
    assert evt.deployment_id == "dep_123"


def test_supporting_types_import() -> None:
    # Touch a few remaining types so the import-only smoke covers them.
    entry = ModelEntry(
        ref=ModelRef(identifier="m"),
        parameters_billion=32.0,
        native_dtype=WeightsDtype.BF16,
        max_context=32_768,
        weights_size_gb=64.0,
    )
    target = ProviderTarget(
        kind=ProviderKind.MODAL,
        account_id="acc_1",  # type: ignore[arg-type]
        region="us-east",  # type: ignore[arg-type]
    )
    plan = ProviderPlan(target=target, payload={"k": "v"})
    cost = Cost(amount=__import__("decimal").Decimal("3.50"))
    endpoint = Endpoint(
        url="https://x.example/v1",
        auth=BearerToken(value="t"),
        openai_compatible=True,
    )
    spec = ResourceSpec(
        accelerator_options=(
            AcceleratorOption(
                accelerators=(AcceleratorClass(name="H100", memory_gb=80),)
            ),
        ),
        cpu_min=8,
        ram_min_gb=64,
        disk_min_gb=200,
        image=RuntimeImage(reference="vllm/vllm-openai:latest"),
    )
    req = WorkflowRequest(
        model_ref=ModelRef(identifier="m"),
        workflow_type=WorkflowType.CHAT,
        tuning=Tuning(priority=Priority.QUALITY),
    )
    assert entry.parameters_billion == 32.0
    assert plan.target.kind is ProviderKind.MODAL
    assert cost.granularity is CostGranularity.HOURLY
    assert endpoint.openai_compatible is True
    assert spec.cpu_min == 8
    assert req.workflow_type is WorkflowType.CHAT
