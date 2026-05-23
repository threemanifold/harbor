"""HTTP tests for ``POST /deployments/{id}/chat``.

The chat proxy looks the deployment up in the repository, requires a
``HEALTHY`` state, and forwards the request body to the deployment's
provisioned endpoint with the stored bearer token attached. Tests use
:class:`httpx.MockTransport` mounted on the container's
:class:`httpx.AsyncClient` to stub the upstream completely.
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from decimal import Decimal
from typing import cast

import httpx
from httpx import ASGITransport

from harbor.composition.app import create_app
from harbor.composition.container import Container, build_container
from harbor.domain.catalog import ModelRef, WeightsDtype
from harbor.domain.deployment import Deployment
from harbor.domain.endpoint import BearerToken, Endpoint
from harbor.domain.identifiers import (
    DeploymentId,
    OwnerId,
    ProviderAccountId,
    Region,
    TeamId,
)
from harbor.domain.placement import (
    Cost,
    Placement,
    ProviderKind,
    ProviderTarget,
)
from harbor.domain.provider_plan import ProviderPlan, ProvisionHandle
from harbor.domain.recipe import (
    HuggingFaceHub,
    Quantization,
    Recipe,
    Runtime,
    ServingPolicy,
)
from harbor.domain.resources import AcceleratorClass, AcceleratorOption
from harbor.domain.workflow import (
    Priority,
    Tuning,
    WorkflowRequest,
    WorkflowType,
)


class _ChunkedStream(httpx.AsyncByteStream):
    """Helper that turns a list of chunks into a streamable response body.

    ``httpx.MockTransport`` defaults responses to a fully-buffered body, but
    the chat-proxy under test calls ``client.stream("POST", ...)`` and
    iterates via ``aiter_raw``. The buffered path raises ``StreamConsumed``
    because the body has already been read once, so the stub upstream needs
    to expose an actual async iterator.
    """

    def __init__(self, chunks: list[bytes]) -> None:
        self._chunks = chunks

    async def __aiter__(self) -> AsyncIterator[bytes]:
        for chunk in self._chunks:
            yield chunk

    async def aclose(self) -> None:
        return None


T0 = datetime(2026, 5, 22, 12, 0, 0, tzinfo=UTC)
UPSTREAM_BASE = "https://harbor-1.modal.run/v1"
UPSTREAM_AUTH = "secret-upstream-token"

REGION = Region("us-east")
TARGET = ProviderTarget(
    kind=ProviderKind.MODAL,
    account_id=ProviderAccountId("acc_1"),
    region=REGION,
)


def _placement() -> Placement:
    accel = AcceleratorOption(
        accelerators=(AcceleratorClass(name="H100", memory_gb=80),)
    )
    return Placement(
        target=TARGET,
        accelerator_choice=accel,
        region=REGION,
        cost_estimate=Cost(amount=Decimal("3.50")),
    )


def _healthy_deployment(deployment_id: str = "dep_test") -> Deployment:
    """Build a HEALTHY :class:`Deployment` aggregate without running the use case."""

    request = WorkflowRequest(
        model_ref=ModelRef(identifier="Qwen/Qwen2.5-3B-Instruct"),
        workflow_type=WorkflowType.CHAT,
        tuning=Tuning(priority=Priority.QUALITY),
    )
    dep = Deployment.start(
        deployment_id=DeploymentId(deployment_id),
        owner=OwnerId("user_default"),
        team=TeamId("team_default"),
        request=request,
        now=T0,
    )
    recipe = Recipe(
        model=request.model_ref,
        runtime=Runtime.VLLM,
        weights_dtype=WeightsDtype.BF16,
        quantization=Quantization.NONE,
        context_len=32_768,
        artifact_source=HuggingFaceHub(repo=request.model_ref.identifier),
        serving=ServingPolicy(),
        tuning=request.tuning,
    )
    dep.compile_to(recipe, now=T0)
    dep.place(_placement(), now=T0)
    dep.start_provisioning(
        plan=ProviderPlan(target=TARGET, payload={}),
        handle=ProvisionHandle(target=TARGET, reference="ref"),
        now=T0,
    )
    dep.mark_starting(now=T0)
    dep.mark_healthy(
        Endpoint(
            url=UPSTREAM_BASE,
            auth=BearerToken(value=UPSTREAM_AUTH),
            openai_compatible=True,
        ),
        now=T0,
    )
    # Drain events so they don't leak onto the bus when we save.
    dep.pull_events()
    return dep


# ---------- Helpers ----------


async def _save(container: Container, dep: Deployment) -> None:
    await container.repo.save(dep)


def _build_stub_app(
    handler: httpx.MockTransport,
    *,
    deployment_id: str = "dep_test",
) -> tuple[Container, str]:
    """Wire a container with a MockTransport-backed httpx client.

    The caller is responsible for pre-populating ``container.repo`` with the
    deployment under test.
    """

    client = httpx.AsyncClient(transport=handler, timeout=httpx.Timeout(5.0))
    container = build_container(http_client=client)
    return container, deployment_id


# ---------- Tests ----------


async def test_chat_proxy_non_streaming_passes_body_and_strips_auth() -> None:
    seen_request: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen_request["url"] = str(request.url)
        seen_request["method"] = request.method
        seen_request["authorization"] = request.headers.get("authorization")
        seen_request["accept"] = request.headers.get("accept")
        seen_request["body"] = json.loads(request.content.decode())
        return httpx.Response(
            200,
            json={
                "id": "chatcmpl-1",
                "object": "chat.completion",
                "created": 0,
                "model": "qwen",
                "choices": [
                    {
                        "index": 0,
                        "message": {"role": "assistant", "content": "hi"},
                        "finish_reason": "stop",
                    }
                ],
                "usage": {
                    "prompt_tokens": 1,
                    "completion_tokens": 1,
                    "total_tokens": 2,
                },
            },
        )

    transport = httpx.MockTransport(handler)
    container, deployment_id = _build_stub_app(transport)
    await _save(container, _healthy_deployment(deployment_id))
    app = create_app(container=container)

    async with httpx.AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as http:
        resp = await http.post(
            f"/deployments/{deployment_id}/chat",
            json={
                "model": "Qwen/Qwen2.5-3B-Instruct",
                "messages": [{"role": "user", "content": "hi"}],
            },
        )

    assert resp.status_code == 200
    body = resp.json()
    assert body["choices"][0]["message"]["content"] == "hi"

    # Upstream URL: <endpoint>/chat/completions, with the stored bearer token.
    assert seen_request["url"] == f"{UPSTREAM_BASE}/chat/completions"
    assert seen_request["method"] == "POST"
    assert seen_request["authorization"] == f"Bearer {UPSTREAM_AUTH}"
    assert seen_request["accept"] == "application/json"

    # The original body was forwarded verbatim (extra OpenAI fields preserved).
    body_seen = cast(dict[str, object], seen_request["body"])
    assert body_seen["model"] == "Qwen/Qwen2.5-3B-Instruct"
    assert body_seen["messages"] == [{"role": "user", "content": "hi"}]

    # The upstream bearer token must NOT appear in the response sent to the
    # client (neither headers nor body).
    assert "authorization" not in {k.lower() for k in resp.headers.keys()}
    assert UPSTREAM_AUTH not in resp.text


async def test_chat_proxy_streams_when_stream_true() -> None:
    upstream_chunks = [
        b'data: {"id": "1", "choices": [{"index": 0, "delta": {"content": "hel"}}]}\n\n',
        b'data: {"id": "1", "choices": [{"index": 0, "delta": {"content": "lo"}}]}\n\n',
        b"data: [DONE]\n\n",
    ]

    seen_request: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen_request["url"] = str(request.url)
        seen_request["accept"] = request.headers.get("accept")
        seen_request["body"] = json.loads(request.content.decode())
        return httpx.Response(
            200,
            headers={"content-type": "text/event-stream"},
            stream=_ChunkedStream(list(upstream_chunks)),
        )

    transport = httpx.MockTransport(handler)
    container, deployment_id = _build_stub_app(transport)
    await _save(container, _healthy_deployment(deployment_id))
    app = create_app(container=container)

    received = bytearray()
    async with httpx.AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as http:
        async with http.stream(
            "POST",
            f"/deployments/{deployment_id}/chat",
            json={
                "model": "Qwen/Qwen2.5-3B-Instruct",
                "messages": [{"role": "user", "content": "hi"}],
                "stream": True,
            },
        ) as resp:
            assert resp.status_code == 200
            assert resp.headers["content-type"].startswith("text/event-stream")
            async for chunk in resp.aiter_raw():
                received.extend(chunk)

    # The upstream content (every chunk we scheduled) is in the response body.
    assert b"hel" in bytes(received)
    assert b"lo" in bytes(received)
    assert b"[DONE]" in bytes(received)
    assert seen_request["accept"] == "text/event-stream"
    body_seen = cast(dict[str, object], seen_request["body"])
    assert body_seen["stream"] is True
    # No leakage of upstream auth into the client-visible body.
    assert UPSTREAM_AUTH.encode() not in bytes(received)


async def test_chat_proxy_404_when_unknown_deployment() -> None:
    transport = httpx.MockTransport(lambda r: httpx.Response(500))
    container, _ = _build_stub_app(transport, deployment_id="dep_test")
    app = create_app(container=container)

    async with httpx.AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as http:
        resp = await http.post(
            "/deployments/dep_unknown/chat",
            json={
                "model": "Qwen/Qwen2.5-3B-Instruct",
                "messages": [{"role": "user", "content": "hi"}],
            },
        )
    assert resp.status_code == 404


async def test_chat_proxy_409_when_not_healthy() -> None:
    transport = httpx.MockTransport(lambda r: httpx.Response(500))
    container, deployment_id = _build_stub_app(transport)
    # Build a deployment in REQUESTED state (no further transitions).
    dep = Deployment.start(
        deployment_id=DeploymentId(deployment_id),
        owner=OwnerId("user_default"),
        team=TeamId("team_default"),
        request=WorkflowRequest(
            model_ref=ModelRef(identifier="Qwen/Qwen2.5-3B-Instruct"),
            workflow_type=WorkflowType.CHAT,
            tuning=Tuning(priority=Priority.QUALITY),
        ),
        now=T0,
    )
    dep.pull_events()
    await _save(container, dep)

    app = create_app(container=container)
    async with httpx.AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as http:
        resp = await http.post(
            f"/deployments/{deployment_id}/chat",
            json={
                "model": "Qwen/Qwen2.5-3B-Instruct",
                "messages": [{"role": "user", "content": "hi"}],
            },
        )
    assert resp.status_code == 409
    assert "HEALTHY" in resp.json()["detail"]


async def test_chat_proxy_validation_errors_return_422() -> None:
    transport = httpx.MockTransport(lambda r: httpx.Response(500))
    container, deployment_id = _build_stub_app(transport)
    await _save(container, _healthy_deployment(deployment_id))
    app = create_app(container=container)

    async with httpx.AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as http:
        # Missing required "messages" field.
        resp = await http.post(
            f"/deployments/{deployment_id}/chat",
            json={"model": "Qwen/Qwen2.5-3B-Instruct"},
        )
    assert resp.status_code == 422
    assert isinstance(resp.json()["detail"], list)
