"""Container shape required by the HTTP routers.

The composition root injects a :class:`harbor.composition.container.Container`
onto ``app.state.container`` at startup. The routers must not import that
class directly — the import-linter ``Onion layers`` contract bans
``interfaces -> composition`` — so they consume a structural
:class:`HttpContainer` Protocol instead.

The real ``Container`` satisfies this Protocol by virtue of having the same
attribute names; mypy verifies that conformance whenever a router calls
:func:`http_container`.
"""

from __future__ import annotations

import asyncio
from typing import Protocol

import httpx
from fastapi import Request

from harbor.application.use_cases.create_deployment import CreateDeployment
from harbor.domain.ports.deployment_repository import DeploymentRepository
from harbor.domain.ports.event_bus import EventBus
from harbor.domain.ports.id_factory import IdFactory
from harbor.domain.ports.model_catalog import ModelCatalog


class HttpContainer(Protocol):
    """Subset of the composition :class:`Container` the routers consume."""

    create_deployment: CreateDeployment
    id_factory: IdFactory
    catalog: ModelCatalog
    repo: DeploymentRepository
    bus: EventBus
    http_client: httpx.AsyncClient
    background_tasks: set[asyncio.Task[object]]


def http_container(request: Request) -> HttpContainer:
    """Return the container attached by :func:`create_app`.

    Casting via ``cast``/``typing.cast`` is intentionally avoided: ``app.state``
    is typed ``Any`` by Starlette, so the assignment from the composition root
    is statically untyped on entry. The annotated return value here gives mypy
    a precise shape from the router's perspective.
    """

    container: HttpContainer = request.app.state.container
    return container


__all__ = ["HttpContainer", "http_container"]
