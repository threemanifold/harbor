"""HTTP tests for the catalog router.

The router pulls a :class:`ModelCatalog` instance off the composition
container and projects each :class:`ModelEntry` into the wire DTO. The
default container ships with :class:`StaticModelCatalog.qwen_default`, so a
plain :func:`create_app` already serves the two Qwen entries that SYM-208
needs.
"""

from __future__ import annotations

import httpx
from httpx import ASGITransport

from harbor.composition.app import create_app


async def test_get_catalog_lists_qwen_entries() -> None:
    app = create_app()
    async with httpx.AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        resp = await client.get("/catalog")

    assert resp.status_code == 200
    body = resp.json()
    assert isinstance(body, list)
    identifiers = {entry["identifier"] for entry in body}
    assert identifiers == {"Qwen/Qwen2.5-3B-Instruct", "Qwen/Qwen2.5-7B-Instruct"}

    qwen3b = next(
        entry for entry in body if entry["identifier"] == "Qwen/Qwen2.5-3B-Instruct"
    )
    assert qwen3b["parameters_billion"] == 3.09
    assert qwen3b["native_dtype"] == "bf16"
    assert qwen3b["max_context"] == 32_768
    assert qwen3b["weights_size_gb"] == 6.2


async def test_openapi_schema_renders() -> None:
    app = create_app()
    async with httpx.AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        resp = await client.get("/openapi.json")

    assert resp.status_code == 200
    schema = resp.json()
    assert schema["info"]["title"] == "Harbor backend"
    # The four SYM-212 routes are all present.
    paths = schema["paths"]
    assert "/catalog" in paths
    assert "/deployments" in paths
    assert "/deployments/{deployment_id}" in paths
    assert "/deployments/{deployment_id}/events" in paths
    assert "/deployments/{deployment_id}/chat" in paths
