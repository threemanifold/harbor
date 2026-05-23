"""HTTP tests for the deployments router.

Each test wires a small fake :class:`ProviderAdapter` into a real
:func:`build_container` so the in-memory infrastructure stack drives the
aggregate end-to-end. The fake adapter exposes an :class:`asyncio.Event`
gate so the SSE test can subscribe before any events fire on the bus.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from decimal import Decimal

import httpx
import pytest
from httpx import ASGITransport

from harbor.composition.app import create_app
from harbor.composition.container import build_container
from harbor.domain.deployment import DeploymentState
from harbor.domain.endpoint import BearerToken, Endpoint
from harbor.domain.identifiers import DeploymentId, ProviderAccountId, Region, TeamId
from harbor.domain.placement import (
    Cost,
    Feasibility,
    Placement,
    ProviderKind,
    ProviderTarget,
)
from harbor.domain.ports.provider_adapter import (
    EndpointReady,
    InfrastructureReady,
    ProvisionEvent,
    ProvisioningProgress,
    ProvisioningStarted,
)
from harbor.domain.provider_plan import ProviderPlan, ProvisionHandle
from harbor.domain.recipe import Recipe
from harbor.domain.resources import ResourceSpec

REGION = Region("us-east")
TARGET = ProviderTarget(
    kind=ProviderKind.MODAL,
    account_id=ProviderAccountId("acc_1"),
    region=REGION,
)


def _endpoint(url: str = "https://harbor-1.modal.run/v1") -> Endpoint:
    return Endpoint(
        url=url,
        auth=BearerToken(value="upstream-secret"),
        openai_compatible=True,
    )


@dataclass
class GatedAdapter:
    """ProviderAdapter that blocks on ``go`` before yielding any event.

    Used to ensure the SSE handler has time to subscribe to the bus before
    the deployment's lifecycle events start firing.
    """

    go: asyncio.Event
    endpoint_url: str = "https://harbor-1.modal.run/v1"
    kind: ProviderKind = ProviderKind.MODAL
    extra_events: tuple[ProvisionEvent, ...] = ()

    async def feasibility(self, recipe: Recipe, spec: ResourceSpec) -> Feasibility:
        option = spec.accelerator_options[0]
        return Feasibility(
            ok=True,
            chosen_option=option,
            region=REGION,
            cost_estimate=Cost(amount=Decimal("1.25")),
            reasons=(),
        )

    async def plan(self, recipe: Recipe, placement: Placement) -> ProviderPlan:
        return ProviderPlan(
            target=placement.target,
            payload={"model": recipe.model.identifier},
        )

    async def provision(self, plan: ProviderPlan) -> AsyncIterator[ProvisionEvent]:
        await self.go.wait()
        handle = ProvisionHandle(target=plan.target, reference="ref")
        yield ProvisioningStarted(handle=handle)
        for event in self.extra_events:
            yield event
        yield InfrastructureReady()
        yield ProvisioningProgress(percent=90, message="loading")
        yield EndpointReady(endpoint=_endpoint(self.endpoint_url))

    async def teardown(self, handle: ProvisionHandle) -> None:
        return None


@dataclass
class _Registry:
    adapter: GatedAdapter
    target: ProviderTarget = TARGET

    async def list_targets(
        self, team: TeamId
    ) -> tuple[tuple[ProviderTarget, GatedAdapter], ...]:
        return ((self.target, self.adapter),)


@dataclass
class _RegistryFactory:
    """Convenience holder used by every test."""

    go: asyncio.Event = field(default_factory=asyncio.Event)

    def build(
        self, *, endpoint_url: str = "https://harbor-1.modal.run/v1"
    ) -> _Registry:
        return _Registry(GatedAdapter(go=self.go, endpoint_url=endpoint_url))


_QWEN_BODY = {
    "model_ref": "Qwen/Qwen2.5-3B-Instruct",
    "workflow_type": "chat",
    "priority": "quality",
}


# ---------- POST /deployments ----------


async def test_create_deployment_returns_id_and_starts_task() -> None:
    factory = _RegistryFactory()
    container = build_container(providers=factory.build())
    app = create_app(container=container)

    async with httpx.AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        resp = await client.post("/deployments", json=_QWEN_BODY)

    assert resp.status_code == 202
    body = resp.json()
    deployment_id = body["deployment_id"]
    assert deployment_id.startswith("dep_")

    # The container should have an in-flight task for our deployment.
    assert len(container.background_tasks) == 1

    # Unblock the gated adapter and let the use case run to completion so the
    # task doesn't leak past the test boundary.
    factory.go.set()
    await asyncio.wait_for(
        asyncio.gather(*list(container.background_tasks), return_exceptions=True),
        timeout=2.0,
    )
    dep = await container.repo.get(DeploymentId(deployment_id))
    assert dep is not None
    assert dep.state is DeploymentState.HEALTHY


async def test_create_deployment_rejects_invalid_priority() -> None:
    factory = _RegistryFactory()
    container = build_container(providers=factory.build())
    app = create_app(container=container)

    async with httpx.AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        resp = await client.post(
            "/deployments",
            json={**_QWEN_BODY, "priority": "not-a-real-priority"},
        )

    assert resp.status_code == 422
    body = resp.json()
    assert "detail" in body
    # FastAPI/pydantic returns a structured list of errors.
    assert isinstance(body["detail"], list)


# ---------- GET /deployments/{id} ----------


async def test_get_deployment_returns_endpoint_url_when_healthy() -> None:
    factory = _RegistryFactory()
    container = build_container(providers=factory.build())
    app = create_app(container=container)

    async with httpx.AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        create_resp = await client.post("/deployments", json=_QWEN_BODY)
        deployment_id = create_resp.json()["deployment_id"]

        # Release the gate and wait for the use case to complete.
        factory.go.set()
        await asyncio.wait_for(
            asyncio.gather(*list(container.background_tasks), return_exceptions=True),
            timeout=2.0,
        )

        status_resp = await client.get(f"/deployments/{deployment_id}")

    assert status_resp.status_code == 200
    body = status_resp.json()
    assert body["deployment_id"] == deployment_id
    assert body["state"] == "healthy"
    assert body["endpoint_url"] == "https://harbor-1.modal.run/v1"
    assert body["failure_reason"] is None


async def test_get_deployment_404_when_unknown() -> None:
    factory = _RegistryFactory()
    container = build_container(providers=factory.build())
    app = create_app(container=container)

    async with httpx.AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        resp = await client.get("/deployments/dep_unknown")

    assert resp.status_code == 404
    assert "Deployment not found" in resp.json()["detail"]


# ---------- GET /deployments/{id}/events ----------


def _parse_sse_payload(line: str) -> dict[str, object]:
    assert line.startswith("data: ")
    parsed: dict[str, object] = json.loads(line[len("data: ") :])
    return parsed


async def test_sse_streams_events_until_terminal_marker() -> None:
    factory = _RegistryFactory()
    container = build_container(providers=factory.build())
    app = create_app(container=container)

    async with httpx.AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        # Kick off the deployment; the adapter is gated so events have not
        # fired yet by the time the response returns.
        create_resp = await client.post("/deployments", json=_QWEN_BODY)
        deployment_id = create_resp.json()["deployment_id"]

        async def collect_events() -> list[dict[str, object]]:
            collected: list[dict[str, object]] = []
            saw_terminal = False
            async with client.stream(
                "GET", f"/deployments/{deployment_id}/events"
            ) as resp:
                assert resp.status_code == 200
                assert resp.headers["content-type"].startswith("text/event-stream")
                async for raw_line in resp.aiter_lines():
                    if raw_line.startswith("data: "):
                        collected.append(_parse_sse_payload(raw_line))
                    elif raw_line.startswith("event: terminal"):
                        saw_terminal = True
                    if saw_terminal and (
                        collected and collected[-1].get("type") == "healthy"
                    ):
                        break
            return collected

        consume = asyncio.create_task(collect_events())
        # Give the SSE handler a moment to subscribe.
        await asyncio.sleep(0.05)
        factory.go.set()
        events = await asyncio.wait_for(consume, timeout=2.0)

    types = [event["type"] for event in events]
    # We may miss the very earliest events that fire before subscribe, but the
    # provisioning chain (provisioning, starting, progress, healthy) is gated
    # behind ``factory.go`` and is guaranteed to be streamed.
    assert "healthy" in types
    healthy = next(event for event in events if event["type"] == "healthy")
    assert healthy["endpoint_url"] == "https://harbor-1.modal.run/v1"
    assert healthy["deployment_id"] == deployment_id


async def test_sse_replays_terminal_state_when_already_done() -> None:
    factory = _RegistryFactory()
    container = build_container(providers=factory.build())
    app = create_app(container=container)

    async with httpx.AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        create_resp = await client.post("/deployments", json=_QWEN_BODY)
        deployment_id = create_resp.json()["deployment_id"]
        # Let the deployment finish before we subscribe.
        factory.go.set()
        await asyncio.wait_for(
            asyncio.gather(*list(container.background_tasks), return_exceptions=True),
            timeout=2.0,
        )

        collected: list[dict[str, object]] = []
        saw_terminal = False
        async with client.stream("GET", f"/deployments/{deployment_id}/events") as resp:
            assert resp.status_code == 200
            async for raw_line in resp.aiter_lines():
                if raw_line.startswith("data: "):
                    collected.append(_parse_sse_payload(raw_line))
                elif raw_line.startswith("event: terminal"):
                    saw_terminal = True
                if saw_terminal:
                    break

    assert saw_terminal
    assert len(collected) == 1
    assert collected[0]["type"] == "healthy"
    assert collected[0]["deployment_id"] == deployment_id


async def test_sse_404_for_unknown_deployment() -> None:
    container = build_container()
    app = create_app(container=container)
    async with httpx.AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        resp = await client.get("/deployments/dep_unknown/events")
    assert resp.status_code == 404


# ---------- shutdown cleanliness ----------


async def test_lifespan_closes_http_client() -> None:
    """Smoke check: the lifespan should aclose() the shared http client.

    Driven directly via the FastAPI lifespan context because httpx's
    :class:`ASGITransport` doesn't run lifespan startup/shutdown.
    """

    factory = _RegistryFactory()
    container = build_container(providers=factory.build())
    app = create_app(container=container)

    assert not container.http_client.is_closed
    async with app.router.lifespan_context(app):
        # Inside the lifespan: still open.
        assert not container.http_client.is_closed
    # After the lifespan exits, the http client should be closed.
    assert container.http_client.is_closed


# Keep the pytest collection marker so this module participates in any
# future asyncio-scope assertions.
_marker = pytest.mark.asyncio
