from __future__ import annotations

from dataclasses import dataclass

from harbor.domain.placement import ProviderTarget


@dataclass(frozen=True, slots=True)
class ProviderPlan:
    """A provider-specific plan derived from a Recipe + Placement. The payload
    is opaque to the domain; each ProviderAdapter knows its own concrete
    shape."""

    target: ProviderTarget
    payload: object
