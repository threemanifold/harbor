"""FastAPI app factory.

``create_app`` builds the dependency container and returns a ready-to-mount
:class:`FastAPI` instance with a ``/health`` endpoint. The container is
attached to ``app.state.container`` so the SYM-212 routers can pull use cases
out of it without re-wiring.
"""

from __future__ import annotations

from fastapi import FastAPI

from harbor.composition.container import Container, build_container
from harbor.domain.ports.provider_registry import ConnectedProviderRegistry


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
        same container instance used by the app.
    """

    resolved_container = container or build_container(providers=providers)

    app = FastAPI(title="Harbor backend")
    app.state.container = resolved_container

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    # NOTE: SYM-212 mounts the deployments router here, pulling
    # ``app.state.container.create_deployment`` etc. out of the container.
    return app


__all__ = ["create_app"]
