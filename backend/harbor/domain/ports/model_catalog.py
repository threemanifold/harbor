from __future__ import annotations

from typing import Protocol

from harbor.domain.catalog import ModelEntry, ModelRef


class ModelCatalog(Protocol):
    async def get(self, ref: ModelRef) -> ModelEntry | None: ...
