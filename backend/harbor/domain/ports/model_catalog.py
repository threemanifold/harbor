from __future__ import annotations

from typing import Protocol

from harbor.domain.catalog import ModelEntry, ModelRef


class ModelCatalog(Protocol):
    async def get(self, ref: ModelRef) -> ModelEntry | None: ...

    async def list_all(self) -> tuple[ModelEntry, ...]:
        """Return every entry the catalog knows about.

        Used by ``GET /catalog`` to render the model picker. Order is
        adapter-defined — clients are expected to sort/filter on their side.
        """
        ...
