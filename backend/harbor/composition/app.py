"""FastAPI app factory.

``create_app`` builds the dependency container and returns a ready-to-mount
:class:`FastAPI` instance with the SYM-212 catalog/deployments routers
mounted. The container is attached to ``app.state.container`` so the routers
can pull use cases, the repository, the event bus, and the upstream HTTP
client out of it without re-wiring.

A ``lifespan`` hook is registered so the shared :class:`httpx.AsyncClient`
is closed cleanly on shutdown.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from harbor.composition.container import Container, build_container
from harbor.domain.ports.provider_registry import ConnectedProviderRegistry
from harbor.interfaces.http.routers.catalog import router as catalog_router
from harbor.interfaces.http.routers.deployments import (
    router as deployments_router,
)


def create_app(
    *,
    providers: ConnectedProviderRegistry | None = None,
    container: Container | None = None,
) -> FastAPI:
    """Build the Harbor FastAPI app.

    Parameters
    ----------
    providers:
        Optional provider registry forwarded to :func:`build_container`.
        Ignored when ``container`` is given.
    container:
        Optional pre-built container. Useful when tests want to assert on the
        same container instance used by the app — and when tests want to
        inject an :class:`httpx.AsyncClient` backed by a ``MockTransport``
        for the chat proxy.
    """

    resolved_container = container or build_container(providers=providers)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        try:
            yield
        finally:
            # Close the shared HTTP client at shutdown. Background deployment
            # tasks are left to finish on their own; cancelling them mid-flight
            # could leave aggregates in an inconsistent state.
            await resolved_container.http_client.aclose()

    app = FastAPI(title="Harbor backend", lifespan=lifespan)
    app.state.container = resolved_container

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    app.include_router(catalog_router)
    app.include_router(deployments_router)
    return app


__all__ = ["create_app"]
