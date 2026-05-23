"""Default :class:`~harbor.domain.services.recipe_compiler.RecipeCompiler`.

Translates a user's :class:`WorkflowRequest` plus the matching
:class:`ModelEntry` into a concrete :class:`Recipe` for the Qwen e2e slice.

Decisions:

* Runtime is always vLLM (the only runtime wired up in this slice).
* Weights dtype is BF16 (Qwen2.5 native).
* Quantization defaults to ``NONE``; we opt into AWQ-INT4 only for 7B-class
  models when the request prioritises ``COST`` — that pairs with the 24 GB
  accelerator options in :class:`DefaultResourceResolver`.
* Context length is taken straight from :attr:`ModelEntry.max_context`.
* Serving policy is single-replica, no tensor parallelism — adequate for both
  Qwen2.5-3B and Qwen2.5-7B on a single accelerator.
* The artifact source is the Hugging Face Hub repo whose identifier matches the
  ``ModelRef``; revision is left ``None`` so vLLM resolves the latest commit.
"""

from __future__ import annotations

from harbor.domain.catalog import ModelEntry, WeightsDtype
from harbor.domain.recipe import (
    HuggingFaceHub,
    Quantization,
    Recipe,
    Runtime,
    ServingPolicy,
)
from harbor.domain.workflow import Priority, WorkflowRequest

# Models at or above this many parameters (billions) are treated as the "7B
# tier" — eligible for AWQ-INT4 to fit on 24 GB accelerators.
_SEVEN_B_THRESHOLD = 6.0


class DefaultRecipeCompiler:
    """Pure, deterministic compiler for the Qwen catalog."""

    def compile(self, request: WorkflowRequest, entry: ModelEntry) -> Recipe:
        return Recipe(
            model=request.model_ref,
            runtime=Runtime.VLLM,
            weights_dtype=WeightsDtype.BF16,
            quantization=_pick_quantization(request, entry),
            context_len=entry.max_context,
            artifact_source=HuggingFaceHub(repo=request.model_ref.identifier),
            serving=ServingPolicy(tensor_parallel=1, replicas=1),
            tuning=request.tuning,
        )


def _pick_quantization(request: WorkflowRequest, entry: ModelEntry) -> Quantization:
    is_seven_b = entry.parameters_billion >= _SEVEN_B_THRESHOLD
    if is_seven_b and request.tuning.priority is Priority.COST:
        return Quantization.AWQ_INT4
    return Quantization.NONE
