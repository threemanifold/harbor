"""Default implementations of the domain service strategies.

These classes satisfy the :class:`Protocol`\\ s declared in
:mod:`harbor.domain.services`. They are wired in :mod:`harbor.composition`
and must not be imported from :mod:`harbor.application.use_cases` (enforced by
import-linter).
"""

from harbor.application.services.placement_policy import DefaultPlacementPolicy
from harbor.application.services.recipe_compiler import DefaultRecipeCompiler
from harbor.application.services.resource_resolver import DefaultResourceResolver

__all__ = [
    "DefaultPlacementPolicy",
    "DefaultRecipeCompiler",
    "DefaultResourceResolver",
]
