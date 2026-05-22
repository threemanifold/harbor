from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from enum import StrEnum

from harbor.domain.identifiers import ProviderAccountId, Region
from harbor.domain.resources import AcceleratorOption


class ProviderKind(StrEnum):
    MODAL = "modal"
    GCP = "gcp"
    AWS = "aws"
    PROXY = "proxy"


class CostGranularity(StrEnum):
    HOURLY = "hourly"
    MONTHLY = "monthly"
    ONE_TIME = "one_time"


@dataclass(frozen=True, slots=True)
class Cost:
    amount: Decimal
    currency: str = "USD"
    granularity: CostGranularity = CostGranularity.HOURLY


@dataclass(frozen=True, slots=True)
class ProviderTarget:
    kind: ProviderKind
    account_id: ProviderAccountId
    region: Region


@dataclass(frozen=True, slots=True)
class Feasibility:
    ok: bool
    chosen_option: AcceleratorOption | None
    region: Region | None
    cost_estimate: Cost | None
    reasons: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class Placement:
    target: ProviderTarget
    accelerator_choice: AcceleratorOption
    region: Region
    cost_estimate: Cost
