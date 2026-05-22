from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


@dataclass(frozen=True, slots=True)
class AcceleratorClass:
    name: str
    memory_gb: int
    vendor: str = "nvidia"


class Interconnect(StrEnum):
    NVLINK = "nvlink"
    PCIE = "pcie"


@dataclass(frozen=True, slots=True)
class AcceleratorOption:
    accelerators: tuple[AcceleratorClass, ...]
    interconnect: Interconnect | None = None


@dataclass(frozen=True, slots=True)
class RuntimeImage:
    reference: str


@dataclass(frozen=True, slots=True)
class ResourceSpec:
    accelerator_options: tuple[AcceleratorOption, ...]
    cpu_min: int
    ram_min_gb: int
    disk_min_gb: int
    image: RuntimeImage
