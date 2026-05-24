"""Deployment lifecycle routes.

* ``POST /deployments`` — fire-and-forget kickoff of the
  :class:`CreateDeployment` use case.
* ``GET /deployments/{id}`` — snapshot of the latest aggregate state.
* ``GET /deployments/{id}/events`` — server-sent event stream of lifecycle
  events; terminates with an ``event: terminal`` marker on ``HEALTHY`` or
  ``FAILED``.
* ``POST /deployments/{id}/chat`` — OpenAI-compatible chat completions proxy
  to the provisioned endpoint. Honors the upstream's streaming behaviour.

Routers read the composition container off ``request.app.state.container``;
they do not import infrastructure adapters directly.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncGenerator, AsyncIterator

import httpx
from fastapi import APIRouter, HTTPException, Request, Response, status
from fastapi.responses import JSONResponse, StreamingResponse

from harbor.domain.catalog import ModelRef
from harbor.domain.deployment import Deployment, DeploymentState
from harbor.domain.endpoint import BearerToken, Endpoint, HeaderToken, NoAuth
from harbor.domain.events import (
    DeploymentEvent,
    DeploymentFailed,
    DeploymentHealthy,
)
from harbor.domain.identifiers import DeploymentId, OwnerId, TeamId
from harbor.domain.workflow import Tuning, WorkflowRequest
from harbor.interfaces.http.deps import http_container
from harbor.interfaces.http.schemas.chat import ChatRequest
from harbor.interfaces.http.schemas.deployments import (
    DeploymentRequest,
    DeploymentResponse,
    DeploymentStatus,
    event_to_dto,
)

router = APIRouter(tags=["deployments"])


# TODO(auth): replace with the authenticated principal once SYM-? lands.
# Until then every request is attributed to a shared default owner/team so
# the in-memory repository can still segregate by team for `list_for_team`.
_DEFAULT_OWNER = OwnerId("user_default")
_DEFAULT_TEAM = TeamId("team_default")

_TERMINAL_MARKER = b"event: terminal\ndata: {}\n\n"

# "Stream-terminal" states are the ones at which the SSE stream sends a
# terminal marker and closes. This is intentionally narrower than the domain
# ``Deployment.is_terminal`` predicate (TERMINATED/FAILED): a freshly
# HEALTHY deployment is still alive in the domain, but for the SYM-212 SSE
# stream the interesting events are over.
_STREAM_TERMINAL_STATES = frozenset({DeploymentState.HEALTHY, DeploymentState.FAILED})


def _to_workflow_request(body: DeploymentRequest) -> WorkflowRequest:
    return WorkflowRequest(
        model_ref=ModelRef(identifier=body.model_ref),
        workflow_type=body.workflow_type,
        tuning=Tuning(priority=body.priority),
    )


@router.post(
    "/deployments",
    response_model=DeploymentResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def create_deployment(
    body: DeploymentRequest,
    request: Request,
) -> DeploymentResponse:
    """Kick off a new deployment and return its identifier immediately.

    The identifier is minted synchronously via the container's
    :class:`IdFactory` so the response can carry it before the background
    ``CreateDeployment`` task has a chance to publish ``DeploymentRequested``.
    """

    container = http_container(request)
    deployment_id = container.id_factory.new_deployment_id()
    workflow_request = _to_workflow_request(body)

    task = asyncio.create_task(
        container.create_deployment.execute(
            request=workflow_request,
            owner=_DEFAULT_OWNER,
            team=_DEFAULT_TEAM,
            deployment_id=deployment_id,
        )
    )
    # Keep a reference so the task is not garbage-collected while running.
    container.background_tasks.add(task)
    task.add_done_callback(container.background_tasks.discard)

    return DeploymentResponse(deployment_id=deployment_id)


@router.get("/deployments/{deployment_id}", response_model=DeploymentStatus)
async def get_deployment(deployment_id: str, request: Request) -> DeploymentStatus:
    """Return the current state snapshot."""

    container = http_container(request)
    dep = await container.repo.get(DeploymentId(deployment_id))
    if dep is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Deployment not found: {deployment_id}",
        )
    return DeploymentStatus.from_domain(dep)


# ---------- SSE event stream ----------


def _sse_payload(event: DeploymentEvent) -> bytes:
    dto = event_to_dto(event)
    return f"data: {dto.model_dump_json()}\n\n".encode()


async def _stream_until_terminal(
    subscription: AsyncIterator[DeploymentEvent],
) -> AsyncGenerator[bytes, None]:
    """Drain the bus, emitting one ``data:`` frame per event until terminal."""

    async for event in subscription:
        yield _sse_payload(event)
        if isinstance(event, (DeploymentHealthy, DeploymentFailed)):
            yield _TERMINAL_MARKER
            return


async def _stream_already_terminal(
    final_event: DeploymentEvent,
) -> AsyncGenerator[bytes, None]:
    yield _sse_payload(final_event)
    yield _TERMINAL_MARKER


def _synthetic_terminal_event(deployment: Deployment) -> DeploymentEvent:
    """Reconstruct a terminal event from a repository snapshot.

    Used when a client subscribes after the deployment has already reached a
    terminal state — the bus has no buffered events to replay, so we
    synthesize one from the aggregate's current fields.
    """

    if deployment.state is DeploymentState.HEALTHY:
        assert deployment.endpoint is not None  # invariant of HEALTHY state
        return DeploymentHealthy(
            deployment_id=deployment.id,
            at=deployment.updated_at,
            endpoint=deployment.endpoint,
        )
    if deployment.state is DeploymentState.FAILED:
        reason = deployment.failure_reason or "Deployment failed."
        return DeploymentFailed(
            deployment_id=deployment.id,
            at=deployment.updated_at,
            reason=reason,
        )
    raise AssertionError(
        f"State {deployment.state} is not a terminal state with a synthesizable event."
    )


@router.get("/deployments/{deployment_id}/events")
async def stream_events(deployment_id: str, request: Request) -> StreamingResponse:
    """Stream lifecycle events as SSE until the deployment is terminal."""

    container = http_container(request)
    dep_id = DeploymentId(deployment_id)
    dep = await container.repo.get(dep_id)
    if dep is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Deployment not found: {deployment_id}",
        )

    if dep.state in _STREAM_TERMINAL_STATES:
        synthetic = _synthetic_terminal_event(dep)
        return StreamingResponse(
            _stream_already_terminal(synthetic),
            media_type="text/event-stream",
        )

    subscription = container.bus.subscribe(dep_id)
    return StreamingResponse(
        _stream_until_terminal(subscription),
        media_type="text/event-stream",
    )


# ---------- Chat proxy ----------


def _auth_headers(endpoint: Endpoint) -> dict[str, str]:
    """Render the auth section of the upstream request headers."""

    if isinstance(endpoint.auth, BearerToken):
        return {"Authorization": f"Bearer {endpoint.auth.value}"}
    if isinstance(endpoint.auth, HeaderToken):
        return {endpoint.auth.name: endpoint.auth.value}
    if isinstance(endpoint.auth, NoAuth):
        return {}
    raise AssertionError(
        f"Unknown auth variant: {type(endpoint.auth).__name__}"
    )  # pragma: no cover - exhaustiveness


def _chat_completions_url(endpoint: Endpoint) -> str:
    """Compose the OpenAI-compatible chat completions URL."""

    base = endpoint.url.rstrip("/")
    return f"{base}/chat/completions"


def _upstream_chat_payload(deployment: Deployment, raw_body: bytes) -> bytes:
    """Render the upstream chat body with the deployment's model identifier."""

    payload = json.loads(raw_body.decode())
    if not isinstance(payload, dict):
        raise ValueError("Chat request body must be a JSON object.")

    model_identifier = (
        deployment.recipe.model.identifier
        if deployment.recipe is not None
        else deployment.request.model_ref.identifier
    )
    payload["model"] = model_identifier
    return json.dumps(payload, separators=(",", ":")).encode()


async def _stream_proxy(
    client: httpx.AsyncClient,
    method: str,
    url: str,
    payload: bytes,
    headers: dict[str, str],
) -> AsyncGenerator[bytes, None]:
    """Open an upstream streaming request and forward bytes verbatim.

    The ``httpx`` context manager stays open for the lifetime of the
    generator so the connection isn't closed before the client finishes
    consuming the stream.
    """

    async with client.stream(method, url, content=payload, headers=headers) as resp:
        async for chunk in resp.aiter_raw():
            yield chunk


@router.post(
    "/deployments/{deployment_id}/chat",
)
async def chat_proxy(
    deployment_id: str,
    body: ChatRequest,
    request: Request,
) -> Response:
    """Proxy a chat completions request to the provisioned endpoint.

    * Looks the deployment up in the repository.
    * 404 if unknown, 409 if not in ``HEALTHY`` state.
    * Forwards OpenAI-compatible fields through, but pins ``model`` to the
      deployment recipe identifier so UI labels cannot leak into vLLM.
    * Adds only the upstream auth header server-side, so the upstream bearer
      token never leaves the backend process.
    """

    container = http_container(request)
    dep = await container.repo.get(DeploymentId(deployment_id))
    if dep is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Deployment not found: {deployment_id}",
        )
    if dep.state is not DeploymentState.HEALTHY or dep.endpoint is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                f"Deployment is in state {dep.state.value!r}; chat requires HEALTHY."
            ),
        )

    raw_body = _upstream_chat_payload(dep, await request.body())
    upstream_url = _chat_completions_url(dep.endpoint)
    headers = {
        "Content-Type": "application/json",
        "Accept": ("text/event-stream" if body.stream else "application/json"),
        **_auth_headers(dep.endpoint),
    }

    if body.stream:
        return StreamingResponse(
            _stream_proxy(
                container.http_client, "POST", upstream_url, raw_body, headers
            ),
            media_type="text/event-stream",
        )

    upstream = await container.http_client.post(
        upstream_url, content=raw_body, headers=headers
    )
    # Preserve the upstream content-type when present; default to JSON.
    media_type = upstream.headers.get("content-type", "application/json")
    try:
        payload = upstream.json()
    except json.JSONDecodeError:
        return Response(
            content=upstream.content,
            status_code=upstream.status_code,
            media_type=media_type,
        )
    return JSONResponse(content=payload, status_code=upstream.status_code)


__all__ = ["router"]
