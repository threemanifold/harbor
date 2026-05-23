"""``GET /catalog`` — list known models.

Backed by the :class:`harbor.domain.ports.model_catalog.ModelCatalog`
singleton stored on the composition container. The router never instantiates
the catalog itself; it pulls whatever was wired in at startup.
"""

from __future__ import annotations

from fastapi import APIRouter, Request

from harbor.interfaces.http.deps import http_container
from harbor.interfaces.http.schemas.catalog import CatalogEntry

router = APIRouter(tags=["catalog"])


@router.get("/catalog", response_model=list[CatalogEntry])
async def list_catalog(request: Request) -> list[CatalogEntry]:
    """Return every model the catalog knows about.

    Used by the model picker on the frontend. Ordering is the catalog's
    natural order — Qwen3B then Qwen7B for the default static catalog.
    """
    container = http_container(request)
    entries = await container.catalog.list_all()
    return [CatalogEntry.from_domain(entry) for entry in entries]


__all__ = ["router"]
