from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from harbor.domain.catalog import ModelRef


class WorkflowType(StrEnum):
    CHAT = "chat"
    FINETUNE = "finetune"
    STEER = "steer"


class Priority(StrEnum):
    LATENCY = "latency"
    THROUGHPUT = "throughput"
    QUALITY = "quality"
    COST = "cost"


@dataclass(frozen=True, slots=True)
class Tuning:
    priority: Priority


@dataclass(frozen=True, slots=True)
class WorkflowRequest:
    model_ref: ModelRef
    workflow_type: WorkflowType
    tuning: Tuning
