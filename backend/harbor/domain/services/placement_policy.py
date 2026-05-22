from __future__ import annotations

from typing import Protocol

from harbor.domain.placement import Feasibility, Placement, ProviderTarget
from harbor.domain.recipe import Recipe
from harbor.domain.resources import ResourceSpec


class PlacementPolicy(Protocol):
    """Ranks the feasible candidates and picks one. The use case is expected
    to call ProviderAdapter.feasibility on each connected target first and
    pass the results in; this keeps the policy pure (no I/O, no async) and
    purely about strategy. Raises NoFeasibleProvider when no candidate is
    feasible."""

    def select(
        self,
        *,
        recipe: Recipe,
        spec: ResourceSpec,
        candidates: tuple[tuple[ProviderTarget, Feasibility], ...],
    ) -> Placement: ...
