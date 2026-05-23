"""Default :class:`~harbor.domain.services.placement_policy.PlacementPolicy`.

Picks the cheapest feasible :class:`ProviderTarget` by
:attr:`Cost.amount`. Raises :class:`NoFeasibleProvider` when no candidate is
feasible, surfacing the collected reasons for diagnostics.

The policy is pure: it never performs I/O and never inspects credentials. The
caller (use case) is responsible for materialising the per-target
:class:`Feasibility` results in advance.
"""

from __future__ import annotations

from decimal import Decimal

from harbor.domain.errors import NoFeasibleProvider
from harbor.domain.placement import Feasibility, Placement, ProviderTarget
from harbor.domain.recipe import Recipe
from harbor.domain.resources import ResourceSpec


class DefaultPlacementPolicy:
    """Cheapest feasible candidate wins."""

    def select(
        self,
        *,
        recipe: Recipe,
        spec: ResourceSpec,
        candidates: tuple[tuple[ProviderTarget, Feasibility], ...],
    ) -> Placement:
        feasible: list[tuple[ProviderTarget, Feasibility]] = [
            (target, feas) for target, feas in candidates if feas.ok
        ]
        if not feasible:
            reasons = tuple(r for _, feas in candidates for r in feas.reasons)
            raise NoFeasibleProvider(reasons=reasons)

        target, winner = min(feasible, key=_cost_amount)
        # The protocol contract: when ok, chosen_option / region / cost are set.
        assert winner.chosen_option is not None
        assert winner.region is not None
        assert winner.cost_estimate is not None
        return Placement(
            target=target,
            accelerator_choice=winner.chosen_option,
            region=winner.region,
            cost_estimate=winner.cost_estimate,
        )


def _cost_amount(item: tuple[ProviderTarget, Feasibility]) -> Decimal:
    _, feas = item
    # Guaranteed by the ok-branch filter above; assertion documents intent for
    # type-checkers without requiring a runtime fallback.
    assert feas.cost_estimate is not None
    return feas.cost_estimate.amount
