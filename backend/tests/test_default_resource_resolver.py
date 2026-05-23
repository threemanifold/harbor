from harbor.application.services.resource_resolver import DefaultResourceResolver
from harbor.domain.catalog import ModelRef, WeightsDtype
from harbor.domain.recipe import (
    HuggingFaceHub,
    Quantization,
    Recipe,
    Runtime,
    ServingPolicy,
)
from harbor.domain.resources import ResourceSpec
from harbor.domain.workflow import Priority, Tuning


def _recipe(
    *, identifier: str, quantization: Quantization = Quantization.NONE
) -> Recipe:
    model = ModelRef(identifier=identifier)
    return Recipe(
        model=model,
        runtime=Runtime.VLLM,
        weights_dtype=WeightsDtype.BF16,
        quantization=quantization,
        context_len=32_768,
        artifact_source=HuggingFaceHub(repo=identifier),
        serving=ServingPolicy(tensor_parallel=1, replicas=1),
        tuning=Tuning(priority=Priority.QUALITY),
    )


def _accelerator_names(spec: ResourceSpec) -> list[tuple[str, ...]]:
    return [
        tuple(a.name for a in option.accelerators)
        for option in spec.accelerator_options
    ]


def test_three_b_bf16_offers_l4_and_a10g_24gb() -> None:
    spec = DefaultResourceResolver().resolve(
        _recipe(identifier="Qwen/Qwen2.5-3B-Instruct")
    )
    options = _accelerator_names(spec)
    assert options == [("L4",), ("A10G",)]
    # Both options are single-GPU 24 GB shapes.
    for option in spec.accelerator_options:
        (accel,) = option.accelerators
        assert accel.memory_gb == 24


def test_seven_b_bf16_requires_a100_40gb() -> None:
    spec = DefaultResourceResolver().resolve(
        _recipe(identifier="Qwen/Qwen2.5-7B-Instruct")
    )
    options = _accelerator_names(spec)
    assert options == [("A100",)]
    (option,) = spec.accelerator_options
    (accel,) = option.accelerators
    assert accel.memory_gb == 40


def test_seven_b_awq_fits_on_a10g_24gb() -> None:
    spec = DefaultResourceResolver().resolve(
        _recipe(
            identifier="Qwen/Qwen2.5-7B-Instruct",
            quantization=Quantization.AWQ_INT4,
        )
    )
    options = _accelerator_names(spec)
    assert options == [("A10G",)]


def test_image_is_pinned_to_vllm() -> None:
    spec = DefaultResourceResolver().resolve(
        _recipe(identifier="Qwen/Qwen2.5-3B-Instruct")
    )
    assert spec.image.reference.startswith("vllm/")


def test_unknown_model_falls_back_to_largest_option() -> None:
    # No "3B" or "7B" hint in the name — resolver should not silently pick a
    # 24 GB shape and risk an OOM.
    spec = DefaultResourceResolver().resolve(_recipe(identifier="acme/unknown-model"))
    options = _accelerator_names(spec)
    assert options == [("A100",)]


def test_resource_minimums_are_reasonable() -> None:
    spec = DefaultResourceResolver().resolve(
        _recipe(identifier="Qwen/Qwen2.5-3B-Instruct")
    )
    assert spec.cpu_min >= 4
    assert spec.ram_min_gb >= 16
    assert spec.disk_min_gb >= 50
