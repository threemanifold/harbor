from harbor.application.services.recipe_compiler import DefaultRecipeCompiler
from harbor.domain.catalog import ModelEntry, ModelRef, WeightsDtype
from harbor.domain.recipe import HuggingFaceHub, Quantization, Runtime
from harbor.domain.workflow import Priority, Tuning, WorkflowRequest, WorkflowType


def _entry(*, params_b: float) -> ModelEntry:
    return ModelEntry(
        ref=ModelRef(identifier=f"Qwen/Qwen2.5-{int(params_b)}B-Instruct"),
        parameters_billion=params_b,
        native_dtype=WeightsDtype.BF16,
        max_context=32_768,
        weights_size_gb=params_b * 2,
    )


def _request(
    ref: ModelRef, *, priority: Priority = Priority.QUALITY
) -> WorkflowRequest:
    return WorkflowRequest(
        model_ref=ref,
        workflow_type=WorkflowType.CHAT,
        tuning=Tuning(priority=priority),
    )


def test_three_b_model_compiles_to_bf16_no_quantization() -> None:
    entry = _entry(params_b=3.09)
    request = _request(entry.ref, priority=Priority.QUALITY)

    recipe = DefaultRecipeCompiler().compile(request, entry)

    assert recipe.runtime is Runtime.VLLM
    assert recipe.weights_dtype is WeightsDtype.BF16
    assert recipe.quantization is Quantization.NONE
    assert recipe.context_len == entry.max_context
    assert recipe.serving.tensor_parallel == 1
    assert recipe.serving.replicas == 1
    assert recipe.tuning == request.tuning
    assert recipe.model == request.model_ref
    assert isinstance(recipe.artifact_source, HuggingFaceHub)
    assert recipe.artifact_source.repo == entry.ref.identifier
    assert recipe.artifact_source.revision is None


def test_three_b_model_ignores_cost_priority_for_quantization() -> None:
    # 3B doesn't need quantization to fit on 24 GB, so COST priority should
    # still produce a BF16 recipe.
    entry = _entry(params_b=3.09)
    request = _request(entry.ref, priority=Priority.COST)

    recipe = DefaultRecipeCompiler().compile(request, entry)

    assert recipe.quantization is Quantization.NONE


def test_seven_b_model_with_cost_priority_compiles_to_awq_int4() -> None:
    entry = _entry(params_b=7.62)
    request = _request(entry.ref, priority=Priority.COST)

    recipe = DefaultRecipeCompiler().compile(request, entry)

    assert recipe.quantization is Quantization.AWQ_INT4
    assert recipe.weights_dtype is WeightsDtype.BF16  # dtype still BF16


def test_seven_b_model_without_cost_priority_stays_bf16() -> None:
    entry = _entry(params_b=7.62)
    for priority in (Priority.QUALITY, Priority.LATENCY, Priority.THROUGHPUT):
        recipe = DefaultRecipeCompiler().compile(
            _request(entry.ref, priority=priority), entry
        )
        assert recipe.quantization is Quantization.NONE, priority


def test_context_length_tracks_model_entry() -> None:
    entry = ModelEntry(
        ref=ModelRef(identifier="Qwen/Qwen2.5-7B-Instruct"),
        parameters_billion=7.62,
        native_dtype=WeightsDtype.BF16,
        max_context=8_192,  # not the default
        weights_size_gb=15.0,
    )
    recipe = DefaultRecipeCompiler().compile(_request(entry.ref), entry)
    assert recipe.context_len == 8_192
