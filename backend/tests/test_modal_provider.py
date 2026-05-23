"""Unit tests for :class:`ModalProviderAdapter`.

The adapter is driven by a hand-rolled fake :class:`ModalClient` so we can
assert on its event sequence without touching the real Modal SDK.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from decimal import Decimal

import pytest

from harbor.domain.catalog import ModelRef, WeightsDtype
from harbor.domain.endpoint import BearerToken, Endpoint
from harbor.domain.identifiers import ProviderAccountId, Region
from harbor.domain.placement import (
    Cost,
    CostGranularity,
    Placement,
    ProviderKind,
    ProviderTarget,
)
from harbor.domain.ports.provider_adapter import (
    EndpointReady,
    InfrastructureReady,
    ProvisionEvent,
    ProvisionFailed,
    ProvisioningProgress,
    ProvisioningStarted,
)
from harbor.domain.provider_plan import ProviderPlan, ProvisionHandle
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
from harbor.infrastructure.providers.modal.adapter import (
    ModalPlanPayload,
    ModalProviderAdapter,
    ModalProvisionHandle,
)
from harbor.infrastructure.providers.modal.client import (
    ModalFunctionRef,
    ModalLookupError,
)

REGION = Region("modal-default")
QWEN_3B = "Qwen/Qwen2.5-3B-Instruct"
QWEN_7B = "Qwen/Qwen2.5-7B-Instruct"


# ---- Domain helpers --------------------------------------------------------


def _recipe(repo: str, quantization: Quantization = Quantization.NONE) -> Recipe:
    model = ModelRef(identifier=repo)
    return Recipe(
        model=model,
        runtime=Runtime.VLLM,
        weights_dtype=WeightsDtype.BF16,
        quantization=quantization,
        context_len=32_768,
        artifact_source=HuggingFaceHub(repo=repo),
        serving=ServingPolicy(tensor_parallel=1, replicas=1),
        tuning=Tuning(priority=Priority.QUALITY),
    )


def _spec_3b() -> ResourceSpec:
    return ResourceSpec(
        accelerator_options=(
            AcceleratorOption(
                accelerators=(AcceleratorClass(name="L4", memory_gb=24),)
            ),
            AcceleratorOption(
                accelerators=(AcceleratorClass(name="A10G", memory_gb=24),)
            ),
        ),
        cpu_min=8,
        ram_min_gb=32,
        disk_min_gb=100,
        image=RuntimeImage(reference="vllm/vllm-openai:v0.6.4"),
    )


def _spec_7b_awq() -> ResourceSpec:
    return ResourceSpec(
        accelerator_options=(
            AcceleratorOption(
                accelerators=(AcceleratorClass(name="A10G", memory_gb=24),)
            ),
        ),
        cpu_min=8,
        ram_min_gb=32,
        disk_min_gb=100,
        image=RuntimeImage(reference="vllm/vllm-openai:v0.6.4"),
    )


def _target() -> ProviderTarget:
    return ProviderTarget(
        kind=ProviderKind.MODAL,
        account_id=ProviderAccountId("harbor-team"),
        region=REGION,
    )


def _placement(option: AcceleratorOption) -> Placement:
    return Placement(
        target=_target(),
        accelerator_choice=option,
        region=REGION,
        cost_estimate=Cost(amount=Decimal("0.80")),
    )


# ---- Fake ModalClient ------------------------------------------------------


@dataclass
class FakeModalClient:
    """Hand-rolled stand-in for the production Modal client.

    Pre-records lookup results, controls how many health-check polls return
    False before flipping True, and records every teardown call so tests can
    assert on best-effort behaviour.
    """

    lookups: dict[tuple[str, str], ModalFunctionRef] = field(default_factory=dict)
    lookup_error: Exception | None = None
    health_after_attempts: int = 0
    health_raise: Exception | None = None
    health_attempts: int = field(default=0)
    stopped: list[tuple[str, str]] = field(default_factory=list)

    async def lookup_function(
        self, *, app_name: str, function_name: str
    ) -> ModalFunctionRef:
        if self.lookup_error is not None:
            raise self.lookup_error
        return self.lookups[(app_name, function_name)]

    async def health_check(self, *, web_url: str) -> bool:
        self.health_attempts += 1
        if self.health_raise is not None:
            raise self.health_raise
        return self.health_attempts > self.health_after_attempts

    async def stop_function(self, *, app_name: str, function_name: str) -> None:
        self.stopped.append((app_name, function_name))


def _adapter(
    client: FakeModalClient,
    *,
    web_url_3b: str | None = None,
    web_url_7b: str | None = None,
    max_health_attempts: int = 10,
) -> ModalProviderAdapter:
    return ModalProviderAdapter(
        client=client,
        region=REGION,
        web_url_3b=web_url_3b,
        web_url_7b=web_url_7b,
        poll_interval_s=0.0,  # don't sleep in tests
        max_health_attempts=max_health_attempts,
    )


async def _collect(events: AsyncIterator[ProvisionEvent]) -> list[ProvisionEvent]:
    out: list[ProvisionEvent] = []
    async for event in events:
        out.append(event)
    return out


# ---- feasibility -----------------------------------------------------------


async def test_feasibility_ok_for_qwen_3b_picks_l4() -> None:
    adapter = _adapter(FakeModalClient())
    feas = await adapter.feasibility(_recipe(QWEN_3B), _spec_3b())
    assert feas.ok is True
    assert feas.chosen_option is not None
    (accel,) = feas.chosen_option.accelerators
    assert accel.name == "L4"
    assert feas.cost_estimate is not None
    assert feas.cost_estimate.amount == Decimal("0.80")
    assert feas.cost_estimate.granularity == CostGranularity.HOURLY
    assert feas.region == REGION
    assert feas.reasons == ()


async def test_feasibility_ok_for_qwen_7b_awq_picks_a10g() -> None:
    adapter = _adapter(FakeModalClient())
    feas = await adapter.feasibility(
        _recipe(QWEN_7B, quantization=Quantization.AWQ_INT4), _spec_7b_awq()
    )
    assert feas.ok is True
    assert feas.chosen_option is not None
    (accel,) = feas.chosen_option.accelerators
    assert accel.name == "A10G"
    assert feas.cost_estimate is not None
    assert feas.cost_estimate.amount == Decimal("1.10")


async def test_feasibility_rejects_unsupported_model() -> None:
    adapter = _adapter(FakeModalClient())
    feas = await adapter.feasibility(_recipe("meta-llama/Llama-3-8B"), _spec_3b())
    assert feas.ok is False
    assert feas.chosen_option is None
    assert feas.cost_estimate is None
    assert feas.region is None
    assert len(feas.reasons) == 1
    assert "Qwen2.5" in feas.reasons[0]


async def test_feasibility_rejects_empty_accelerator_options() -> None:
    adapter = _adapter(FakeModalClient())
    spec = ResourceSpec(
        accelerator_options=(),
        cpu_min=8,
        ram_min_gb=32,
        disk_min_gb=100,
        image=RuntimeImage(reference="vllm/vllm-openai:v0.6.4"),
    )
    feas = await adapter.feasibility(_recipe(QWEN_3B), spec)
    assert feas.ok is False
    assert "accelerator" in feas.reasons[0].lower()


# ---- plan ------------------------------------------------------------------


async def test_plan_emits_modal_payload_for_3b() -> None:
    adapter = _adapter(
        FakeModalClient(),
        web_url_3b="https://harbor--qwen-3b.modal.run",
    )
    option = AcceleratorOption(
        accelerators=(AcceleratorClass(name="L4", memory_gb=24),)
    )
    plan = await adapter.plan(_recipe(QWEN_3B), _placement(option))
    assert isinstance(plan.payload, ModalPlanPayload)
    assert plan.payload.app_name == "harbor-qwen-vllm"
    assert plan.payload.function_name == "serve_3b"
    assert plan.payload.web_url == "https://harbor--qwen-3b.modal.run"
    assert plan.payload.model_repo == QWEN_3B
    assert plan.payload.gpu == "L4"


async def test_plan_emits_modal_payload_for_7b() -> None:
    adapter = _adapter(
        FakeModalClient(),
        web_url_7b="https://harbor--qwen-7b.modal.run",
    )
    option = AcceleratorOption(
        accelerators=(AcceleratorClass(name="A10G", memory_gb=24),)
    )
    plan = await adapter.plan(
        _recipe(QWEN_7B, quantization=Quantization.AWQ_INT4), _placement(option)
    )
    assert isinstance(plan.payload, ModalPlanPayload)
    assert plan.payload.function_name == "serve_7b"
    assert plan.payload.gpu == "A10G"


async def test_plan_carries_environment() -> None:
    adapter = ModalProviderAdapter(
        client=FakeModalClient(),
        region=REGION,
        web_url_3b="https://x.modal.run",
        environment={"HF_TOKEN": "hf_abc"},
    )
    option = AcceleratorOption(
        accelerators=(AcceleratorClass(name="L4", memory_gb=24),)
    )
    plan = await adapter.plan(_recipe(QWEN_3B), _placement(option))
    assert isinstance(plan.payload, ModalPlanPayload)
    assert plan.payload.env == {"HF_TOKEN": "hf_abc"}


async def test_plan_unsupported_model_raises() -> None:
    adapter = _adapter(FakeModalClient(), web_url_3b="https://x.modal.run")
    option = AcceleratorOption(
        accelerators=(AcceleratorClass(name="L4", memory_gb=24),)
    )
    with pytest.raises(ValueError) as exc_info:
        await adapter.plan(_recipe("meta-llama/Llama-3-8B"), _placement(option))
    assert "unsupported" in str(exc_info.value).lower()


# ---- provision -------------------------------------------------------------


async def test_provision_happy_path_emits_documented_sequence() -> None:
    client = FakeModalClient(health_after_attempts=2)
    adapter = _adapter(client, web_url_3b="https://harbor--qwen-3b.modal.run")
    plan = ProviderPlan(
        target=_target(),
        payload=ModalPlanPayload(
            app_name="harbor-qwen-vllm",
            function_name="serve_3b",
            web_url="https://harbor--qwen-3b.modal.run",
            model_repo=QWEN_3B,
            gpu="L4",
            env={},
        ),
    )

    events = await _collect(adapter.provision(plan))
    types = [type(e) for e in events]

    # Documented order: Started, InfrastructureReady, ..., EndpointReady.
    assert types[0] is ProvisioningStarted
    assert types[1] is InfrastructureReady
    assert types[-1] is EndpointReady
    # No failures along the way.
    assert ProvisionFailed not in types
    # The endpoint should expose the OpenAI base URL with /v1 appended.
    last_event = events[-1]
    assert isinstance(last_event, EndpointReady)
    assert last_event.endpoint == Endpoint(
        url="https://harbor--qwen-3b.modal.run/v1",
        auth=BearerToken(value="modal-public"),
        openai_compatible=True,
    )

    # The ProvisioningStarted handle carries enough info to drive teardown.
    started = events[0]
    assert isinstance(started, ProvisioningStarted)
    ref = started.handle.reference
    assert isinstance(ref, ModalProvisionHandle)
    assert ref.function_name == "serve_3b"


async def test_provision_emits_progress_during_health_polling() -> None:
    # Tune the loop: 12 attempts before healthy → progress emitted at every
    # 5th attempt (positions 5 and 10). Use a generous cap so the polling
    # loop actually reaches those tick boundaries.
    client = FakeModalClient(health_after_attempts=11)
    adapter = _adapter(
        client,
        web_url_3b="https://x.modal.run",
        max_health_attempts=20,
    )
    plan = ProviderPlan(
        target=_target(),
        payload=ModalPlanPayload(
            app_name="harbor-qwen-vllm",
            function_name="serve_3b",
            web_url="https://x.modal.run",
            model_repo=QWEN_3B,
            gpu="L4",
            env={},
        ),
    )
    events = await _collect(adapter.provision(plan))

    progress = [e for e in events if isinstance(e, ProvisioningProgress)]
    assert len(progress) >= 2
    # Percentages are monotonically non-decreasing within the run.
    percents = [p.percent for p in progress]
    assert percents == sorted(percents)
    for p in progress:
        assert 0 <= p.percent <= 95
        assert "healthz" in p.message


async def test_provision_uses_pre_baked_web_url_and_skips_lookup() -> None:
    client = FakeModalClient(
        health_after_attempts=0,
        lookup_error=AssertionError("lookup should not be called"),
    )
    adapter = _adapter(client, web_url_3b="https://baked.modal.run")
    plan = ProviderPlan(
        target=_target(),
        payload=ModalPlanPayload(
            app_name="harbor-qwen-vllm",
            function_name="serve_3b",
            web_url="https://baked.modal.run",
            model_repo=QWEN_3B,
            gpu="L4",
            env={},
        ),
    )
    events = await _collect(adapter.provision(plan))
    assert not any(isinstance(e, ProvisionFailed) for e in events)


async def test_provision_falls_back_to_lookup_when_web_url_absent() -> None:
    client = FakeModalClient(health_after_attempts=0)
    client.lookups[("harbor-qwen-vllm", "serve_3b")] = ModalFunctionRef(
        app_name="harbor-qwen-vllm",
        function_name="serve_3b",
        web_url="https://resolved.modal.run",
    )
    adapter = _adapter(client)
    plan = ProviderPlan(
        target=_target(),
        payload=ModalPlanPayload(
            app_name="harbor-qwen-vllm",
            function_name="serve_3b",
            web_url="",  # blank → adapter must look up
            model_repo=QWEN_3B,
            gpu="L4",
            env={},
        ),
    )
    events = await _collect(adapter.provision(plan))
    # Endpoint URL comes from the lookup result.
    last_event = events[-1]
    assert isinstance(last_event, EndpointReady)
    assert last_event.endpoint.url == "https://resolved.modal.run/v1"


async def test_provision_translates_lookup_error_to_provision_failed() -> None:
    client = FakeModalClient(
        lookup_error=ModalLookupError("function not found"),
    )
    adapter = _adapter(client)
    plan = ProviderPlan(
        target=_target(),
        payload=ModalPlanPayload(
            app_name="harbor-qwen-vllm",
            function_name="serve_3b",
            web_url="",
            model_repo=QWEN_3B,
            gpu="L4",
            env={},
        ),
    )
    events = await _collect(adapter.provision(plan))
    assert len(events) == 1
    failed = events[0]
    assert isinstance(failed, ProvisionFailed)
    assert "Modal lookup failed" in failed.reason
    assert "function not found" in failed.reason


async def test_provision_fails_when_health_never_recovers() -> None:
    # Permanently unhealthy — all attempts return False.
    client = FakeModalClient(health_after_attempts=999)
    adapter = _adapter(client, web_url_3b="https://x.modal.run", max_health_attempts=3)
    plan = ProviderPlan(
        target=_target(),
        payload=ModalPlanPayload(
            app_name="harbor-qwen-vllm",
            function_name="serve_3b",
            web_url="https://x.modal.run",
            model_repo=QWEN_3B,
            gpu="L4",
            env={},
        ),
    )
    events = await _collect(adapter.provision(plan))
    types = [type(e) for e in events]
    assert ProvisionFailed in types
    assert EndpointReady not in types
    final = events[-1]
    assert isinstance(final, ProvisionFailed)
    assert "did not become healthy" in final.reason


async def test_provision_treats_health_check_exceptions_as_unhealthy() -> None:
    # Simulate transient cold-start errors that the adapter must ignore.
    client = FakeModalClient(
        health_after_attempts=0, health_raise=ConnectionError("boom")
    )
    adapter = _adapter(client, web_url_3b="https://x.modal.run", max_health_attempts=2)
    plan = ProviderPlan(
        target=_target(),
        payload=ModalPlanPayload(
            app_name="harbor-qwen-vllm",
            function_name="serve_3b",
            web_url="https://x.modal.run",
            model_repo=QWEN_3B,
            gpu="L4",
            env={},
        ),
    )
    events = await _collect(adapter.provision(plan))
    # Exception was swallowed → adapter kept polling → eventually failed
    # rather than raising.
    final = events[-1]
    assert isinstance(final, ProvisionFailed)


async def test_provision_rejects_foreign_plan_payload() -> None:
    adapter = _adapter(FakeModalClient(), web_url_3b="https://x.modal.run")
    plan = ProviderPlan(target=_target(), payload={"foreign": True})
    events = await _collect(adapter.provision(plan))
    final = events[-1]
    assert isinstance(final, ProvisionFailed)
    assert "crashed" in final.reason or "ModalPlanPayload" in final.reason


# ---- teardown --------------------------------------------------------------


async def test_teardown_calls_stop_function_with_handle_coordinates() -> None:
    client = FakeModalClient()
    adapter = _adapter(client)
    handle = ProvisionHandle(
        target=_target(),
        reference=ModalProvisionHandle(
            app_name="harbor-qwen-vllm",
            function_name="serve_3b",
            web_url="https://x.modal.run",
        ),
    )
    await adapter.teardown(handle)
    assert client.stopped == [("harbor-qwen-vllm", "serve_3b")]


async def test_teardown_swallows_modal_errors_best_effort() -> None:
    class FailingClient(FakeModalClient):
        async def stop_function(self, *, app_name: str, function_name: str) -> None:
            raise RuntimeError("modal API down")

    client = FailingClient()
    adapter = _adapter(client)
    handle = ProvisionHandle(
        target=_target(),
        reference=ModalProvisionHandle(
            app_name="harbor-qwen-vllm",
            function_name="serve_3b",
            web_url="https://x.modal.run",
        ),
    )
    # Should not raise.
    await adapter.teardown(handle)


async def test_teardown_ignores_foreign_handle() -> None:
    client = FakeModalClient()
    adapter = _adapter(client)
    handle = ProvisionHandle(target=_target(), reference="not-a-modal-handle")
    await adapter.teardown(handle)
    assert client.stopped == []


# ---- ProviderAdapter Protocol sanity ---------------------------------------


def test_adapter_kind_is_modal() -> None:
    assert ModalProviderAdapter.kind is ProviderKind.MODAL
