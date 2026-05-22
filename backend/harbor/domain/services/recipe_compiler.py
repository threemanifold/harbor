from __future__ import annotations

from typing import Protocol

from harbor.domain.catalog import ModelEntry
from harbor.domain.recipe import Recipe
from harbor.domain.workflow import WorkflowRequest


class RecipeCompiler(Protocol):
    """Translates a user's WorkflowRequest plus the matching ModelEntry into
    a concrete Recipe (runtime, dtype, quantization, context, serving). Pure
    logic — no I/O. Implementations choose how to weight Tuning.priority."""

    def compile(self, request: WorkflowRequest, entry: ModelEntry) -> Recipe: ...
