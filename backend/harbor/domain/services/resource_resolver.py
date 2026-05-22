from __future__ import annotations

from typing import Protocol

from harbor.domain.recipe import Recipe
from harbor.domain.resources import ResourceSpec


class ResourceResolver(Protocol):
    """Derives a ResourceSpec from a Recipe — i.e. translates 'serve this
    model with this runtime and dtype' into a set of acceptable hardware
    shapes plus container image and host requirements."""

    def resolve(self, recipe: Recipe) -> ResourceSpec: ...
