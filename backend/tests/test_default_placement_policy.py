from decimal import Decimal

import pytest

from harbor.application.services.placement_policy import DefaultPlacementPolicy
from harbor.domain.catalog import ModelRef, WeightsDtype
from harbor.domain.errors import NoFeasibleProvider
from harbor.domain.identifiers import ProviderAccountId, Region
from harbor.domain.placement import (
    Cost,
    Feasibility,
    ProviderKind,
    ProviderTarget,
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
from harbor.domain.workflow import Priority, Tuning


def _recipe() -> Recipe:
    model = ModelRef(identifier="Qwen/Qwen2.5-3B-Instruct")
    return Recipe(
        model=model,
        runtime=Runtime.VLLM,
        weights_dtype=WeightsDtype.BF16,
        quantization=Quantization.NONE,
        context_len=32_768,
        artifact_source=HuggingFaceHub(repo=model.identifier),
        serving=ServingPolicy(tensor_parallel=1, replicas=1),
        tuning=Tuning(priority=Priority.QUALITY),
    )


def _spec() -> ResourceSpec:
    return ResourceSpec(
        accelerator_options=(
            AcceleratorOption(
                accelerators=(AcceleratorClass(name="L4", memory_gb=24),)
            ),
        ),
        cpu_min=8,
        ram_min_gb=32,
        disk_min_gb=100,
        image=RuntimeImage(reference="vllm/vllm-openai:v0.6.4"),
    )


def _target(account: str) -> ProviderTarget:
    return ProviderTarget(
        kind=ProviderKind.MODAL,
        account_id=ProviderAccountId(account),
        region=Region("us-east"),
    )


def _ok(amount: str) -> Feasibility:
    return Feasibility(
        ok=True,
        chosen_option=AcceleratorOption(
            accelerators=(AcceleratorClass(name="L4", memory_gb=24),)
        ),
        region=Region("us-east"),
        cost_estimate=Cost(amount=Decimal(amount)),
        reasons=(),
    )


def _bad(reason: str) -> Feasibility:
    return Feasibility(
        ok=False,
        chosen_option=None,
        region=None,
        cost_estimate=None,
        reasons=(reason,),
    )


def test_picks_cheapest_feasible_candidate() -> None:
    candidates = (
        (_target("acc_expensive"), _ok("3.00")),
        (_target("acc_cheap"), _ok("1.50")),
        (_target("acc_mid"), _ok("2.00")),
    )
    placement = DefaultPlacementPolicy().select(
        recipe=_recipe(), spec=_spec(), candidates=candidates
    )
    assert placement.target.account_id == "acc_cheap"
    assert placement.cost_estimate.amount == Decimal("1.50")


def test_ignores_infeasible_candidates_even_if_cheaper() -> None:
    candidates = (
        (_target("acc_quotaless"), _bad("quota exhausted")),
        (_target("acc_ok"), _ok("4.99")),
    )
    placement = DefaultPlacementPolicy().select(
        recipe=_recipe(), spec=_spec(), candidates=candidates
    )
    assert placement.target.account_id == "acc_ok"


def test_raises_no_feasible_provider_with_collected_reasons() -> None:
    candidates = (
        (_target("acc_a"), _bad("no quota")),
        (_target("acc_b"), _bad("wrong region")),
    )
    with pytest.raises(NoFeasibleProvider) as exc_info:
        DefaultPlacementPolicy().select(
            recipe=_recipe(), spec=_spec(), candidates=candidates
        )
    assert exc_info.value.reasons == ("no quota", "wrong region")


def test_raises_no_feasible_provider_on_empty_candidates() -> None:
    with pytest.raises(NoFeasibleProvider) as exc_info:
        DefaultPlacementPolicy().select(recipe=_recipe(), spec=_spec(), candidates=())
    assert exc_info.value.reasons == ()


def test_single_feasible_candidate_wins() -> None:
    candidates = ((_target("acc_only"), _ok("9.99")),)
    placement = DefaultPlacementPolicy().select(
        recipe=_recipe(), spec=_spec(), candidates=candidates
    )
    assert placement.target.account_id == "acc_only"
    assert placement.cost_estimate.amount == Decimal("9.99")
    assert placement.region == Region("us-east")
