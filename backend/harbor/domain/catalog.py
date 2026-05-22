from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class WeightsDtype(StrEnum):
    BF16 = "bf16"
    FP16 = "fp16"
    FP32 = "fp32"
    INT8 = "int8"
    INT4 = "int4"
    MXFP4 = "mxfp4"


@dataclass(frozen=True, slots=True)
class ModelRef:
    identifier: str


@dataclass(frozen=True, slots=True)
class ModelEntry:
    ref: ModelRef
    parameters_billion: float
    native_dtype: WeightsDtype
    max_context: int
    weights_size_gb: float
