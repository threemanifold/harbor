"""Default :class:`~harbor.domain.services.resource_resolver.ResourceResolver`.

Maps a :class:`Recipe` to a :class:`ResourceSpec` that lists acceptable
accelerator shapes for the Qwen e2e slice and pins the vLLM runtime image.

The model size is inferred from the ``ModelRef`` identifier (e.g. ``"3B"`` or
``"7B"`` in the slug) — this is fine for the Qwen catalog and keeps the
:class:`Recipe` shape unchanged. When the size cannot be inferred we fall back
to the largest option (A100 40 GB BF16) so the deployment doesn't silently
under-provision.

Selected hardware shapes:

* 3B BF16  → L4 (24 GB) **or** A10G (24 GB)
* 7B AWQ-INT4 → A10G (24 GB)
* 7B BF16 → A100 (40 GB)
"""

from __future__ import annotations

import re

from harbor.domain.catalog import ModelRef
from harbor.domain.recipe import Quantization, Recipe
from harbor.domain.resources import (
    AcceleratorClass,
    AcceleratorOption,
    ResourceSpec,
    RuntimeImage,
)

# Pinned vLLM container image. Composition can override later if needed.
_VLLM_IMAGE = RuntimeImage(reference="vllm/vllm-openai:v0.6.4")

_L4_24GB = AcceleratorClass(name="L4", memory_gb=24)
_A10G_24GB = AcceleratorClass(name="A10G", memory_gb=24)
_A100_40GB = AcceleratorClass(name="A100", memory_gb=40)

# Conservative defaults — enough headroom for vLLM + Qwen2.5 weights + KV cache
# at 32k context.
_CPU_MIN = 8
_RAM_MIN_GB = 32
_DISK_MIN_GB = 100

# Threshold for the "7B tier" in billions of parameters.
_SEVEN_B_THRESHOLD = 6.0

_SIZE_PATTERN = re.compile(r"(\d+(?:\.\d+)?)\s*[bB]\b")


class DefaultResourceResolver:
    """Maps Recipe → ResourceSpec for the Qwen catalog."""

    def resolve(self, recipe: Recipe) -> ResourceSpec:
        size_b = _infer_params_billion(recipe.model)
        is_seven_b_tier = size_b is None or size_b >= _SEVEN_B_THRESHOLD

        if recipe.quantization is Quantization.AWQ_INT4:
            # ~4 GB weights → comfortably fits on a single 24 GB GPU. We only
            # ship AWQ for the 7B tier today; the 3B tier never quantises.
            options: tuple[AcceleratorOption, ...] = (
                AcceleratorOption(accelerators=(_A10G_24GB,)),
            )
        elif is_seven_b_tier:
            # 7B BF16 (~14 GB) plus KV cache + activations doesn't fit on 24 GB.
            options = (AcceleratorOption(accelerators=(_A100_40GB,)),)
        else:
            # 3B BF16 (~6 GB) fits on L4 or A10G — list both so the placement
            # policy can pick the cheapest target.
            options = (
                AcceleratorOption(accelerators=(_L4_24GB,)),
                AcceleratorOption(accelerators=(_A10G_24GB,)),
            )

        return ResourceSpec(
            accelerator_options=options,
            cpu_min=_CPU_MIN,
            ram_min_gb=_RAM_MIN_GB,
            disk_min_gb=_DISK_MIN_GB,
            image=_VLLM_IMAGE,
        )


def _infer_params_billion(model: ModelRef) -> float | None:
    match = _SIZE_PATTERN.search(model.identifier)
    if match is None:
        return None
    try:
        return float(match.group(1))
    except ValueError:  # pragma: no cover - regex guarantees numeric match
        return None
