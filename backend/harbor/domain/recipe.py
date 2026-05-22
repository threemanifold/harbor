from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from harbor.domain.catalog import ModelRef, WeightsDtype
from harbor.domain.workflow import Tuning


class Runtime(StrEnum):
    VLLM = "vllm"
    TGI = "tgi"
    LLAMA_CPP = "llama_cpp"
    MODAL_NATIVE = "modal_native"
    PROXY = "proxy"


class Quantization(StrEnum):
    NONE = "none"
    AWQ_INT4 = "awq_int4"
    GPTQ_INT4 = "gptq_int4"
    BNB_NF4 = "bnb_nf4"
    FP8 = "fp8"


@dataclass(frozen=True, slots=True)
class HuggingFaceHub:
    repo: str
    revision: str | None = None


@dataclass(frozen=True, slots=True)
class S3Bucket:
    bucket: str
    key: str
    region: str


@dataclass(frozen=True, slots=True)
class GCSBucket:
    bucket: str
    object_path: str


ArtifactSource = HuggingFaceHub | S3Bucket | GCSBucket


@dataclass(frozen=True, slots=True)
class ServingPolicy:
    tensor_parallel: int = 1
    replicas: int = 1


@dataclass(frozen=True, slots=True)
class Recipe:
    model: ModelRef
    runtime: Runtime
    weights_dtype: WeightsDtype
    quantization: Quantization
    context_len: int
    artifact_source: ArtifactSource
    serving: ServingPolicy
    tuning: Tuning
