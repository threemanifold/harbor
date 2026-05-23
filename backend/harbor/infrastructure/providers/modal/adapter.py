"""Modal-backed :class:`~harbor.domain.ports.provider_adapter.ProviderAdapter`.

Drives provisioning of the deployed ``harbor-qwen-vllm`` Modal app
(see :mod:`modal_apps.qwen_vllm`) for Qwen2.5-3B-Instruct and
Qwen2.5-7B-Instruct.

Design highlights
-----------------
* The ``modal`` SDK is not a backend runtime dependency. The adapter talks to
  a :class:`~harbor.infrastructure.providers.modal.client.ModalClient`
  Protocol, which composition wires to either a real-SDK-backed client or a
  fake (tests).
* :meth:`feasibility` is hard-coded to the two Qwen models the slice
  supports. Any other model is rejected up-front, mirroring the catalog in
  :mod:`harbor.infrastructure.catalog.static`.
* :meth:`provision` is an async generator that interleaves Modal lookup,
  health polling and the documented :class:`ProvisionEvent` sequence.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from dataclasses import dataclass
from decimal import Decimal

from harbor.domain.endpoint import BearerToken, Endpoint
from harbor.domain.identifiers import Region
from harbor.domain.placement import (
    Cost,
    CostGranularity,
    Feasibility,
    Placement,
    ProviderKind,
    ProviderTarget,
)
from harbor.domain.ports.provider_adapter import (
    EndpointReady,
    InfrastructureReady,
    ProvisionEvent,
    ProvisionFailed,
    ProvisioningProgress,
    ProvisioningStarted,
)
from harbor.domain.provider_plan import ProviderPlan, ProvisionHandle
from harbor.domain.recipe import Recipe
from harbor.domain.resources import AcceleratorOption, ResourceSpec
from harbor.infrastructure.providers.modal.client import (
    ModalClient,
    ModalFunctionRef,
    ModalLookupError,
)

# ----- Tunables -------------------------------------------------------------

# Modal pricing (USD/hour) is hard-coded for the slice. These are the
# published L4 / A10G on-demand rates as of 2026-05; replace with a live
# pricing source when SYM-208 graduates beyond the e2e.
_L4_HOURLY_USD = Decimal("0.80")
_A10G_HOURLY_USD = Decimal("1.10")

# Synthetic auth token returned to callers. Modal web endpoints don't
# require client-side auth headers in this slice (the deployed function is
# publicly addressable by URL); a placeholder BearerToken keeps the
# downstream :class:`Endpoint` shape uniform with future authed providers.
_DEFAULT_BEARER = "modal-public"

# How many times we poll ``/healthz`` before giving up. The Qwen 7B image
# can take ~120 s to load on cold-start, so 90 retries × 2 s = 3 minutes
# gives plenty of headroom while still failing fast on a permanently broken
# deploy.
_HEALTH_MAX_ATTEMPTS = 90
_HEALTH_POLL_INTERVAL_S = 2.0

# ----- Plan payload ---------------------------------------------------------

# Hard-coded supported repos. Keeping them as a frozenset (rather than a
# table keyed on ModelRef) avoids any ambiguity around the value's hash and
# matches the StaticModelCatalog naming.
_QWEN_3B_REPO = "Qwen/Qwen2.5-3B-Instruct"
_QWEN_7B_REPO = "Qwen/Qwen2.5-7B-Instruct"
_SUPPORTED_REPOS = frozenset({_QWEN_3B_REPO, _QWEN_7B_REPO})


@dataclass(frozen=True, slots=True)
class ModalPlanPayload:
    """The concrete payload carried by :class:`ProviderPlan` for Modal.

    Stored verbatim on :class:`~harbor.domain.deployment.Deployment` via
    :attr:`Deployment.plan`, so the diagnostic UI can show users the exact
    Modal function the deployment is bound to.
    """

    app_name: str
    function_name: str
    web_url: str
    model_repo: str
    gpu: str
    env: dict[str, str]


@dataclass(frozen=True, slots=True)
class ModalProvisionHandle:
    """Opaque reference carried by :class:`ProvisionHandle.reference` for the
    Modal adapter. Lets :meth:`ModalProviderAdapter.teardown` re-derive the
    function coordinates without round-tripping through Modal."""

    app_name: str
    function_name: str
    web_url: str


# ----- Adapter --------------------------------------------------------------


class ModalProviderAdapter:
    """Modal-backed provider adapter for Qwen vLLM endpoints."""

    kind: ProviderKind = ProviderKind.MODAL

    def __init__(
        self,
        *,
        client: ModalClient,
        region: Region,
        app_name: str = "harbor-qwen-vllm",
        function_name_3b: str = "serve_3b",
        function_name_7b: str = "serve_7b",
        web_url_3b: str | None = None,
        web_url_7b: str | None = None,
        environment: dict[str, str] | None = None,
        poll_interval_s: float = _HEALTH_POLL_INTERVAL_S,
        max_health_attempts: int = _HEALTH_MAX_ATTEMPTS,
    ) -> None:
        self._client = client
        self._region = region
        self._app_name = app_name
        self._function_name_3b = function_name_3b
        self._function_name_7b = function_name_7b
        self._web_url_3b = web_url_3b
        self._web_url_7b = web_url_7b
        self._environment = dict(environment or {})
        self._poll_interval_s = poll_interval_s
        self._max_health_attempts = max_health_attempts

    # ---- feasibility ----

    async def feasibility(self, recipe: Recipe, spec: ResourceSpec) -> Feasibility:
        repo = recipe.model.identifier
        if repo not in _SUPPORTED_REPOS:
            return Feasibility(
                ok=False,
                chosen_option=None,
                region=None,
                cost_estimate=None,
                reasons=(f"Modal adapter only supports Qwen2.5 3B/7B (got {repo!r}).",),
            )

        # Pick the cheapest accelerator option the resolver offered. The
        # resolver already filters down to 24/40 GB shapes that fit the
        # selected model + quantization, so we don't need to second-guess.
        option = _pick_cheapest_option(spec, repo)
        if option is None:
            return Feasibility(
                ok=False,
                chosen_option=None,
                region=None,
                cost_estimate=None,
                reasons=("No Modal-supported accelerator option in spec.",),
            )

        accel_name = option.accelerators[0].name
        hourly = _hourly_cost_for(accel_name)
        return Feasibility(
            ok=True,
            chosen_option=option,
            # Modal exposes a single global plane to Harbor; we surface the
            # region the adapter was registered under so the resulting
            # Placement matches its ProviderTarget.
            region=self._region,
            cost_estimate=Cost(
                amount=hourly,
                currency="USD",
                granularity=CostGranularity.HOURLY,
            ),
            reasons=(),
        )

    # ---- plan ----

    async def plan(self, recipe: Recipe, placement: Placement) -> ProviderPlan:
        repo = recipe.model.identifier
        if repo not in _SUPPORTED_REPOS:
            raise ValueError(
                f"ModalProviderAdapter.plan called with unsupported model "
                f"{repo!r}; feasibility should have rejected this."
            )
        function_name = self._function_name_for(repo)
        web_url = self._web_url_for(repo)
        gpu = placement.accelerator_choice.accelerators[0].name
        payload = ModalPlanPayload(
            app_name=self._app_name,
            function_name=function_name,
            web_url=web_url or "",  # resolved at provision time if blank
            model_repo=repo,
            gpu=gpu,
            env=dict(self._environment),
        )
        return ProviderPlan(target=placement.target, payload=payload)

    # ---- provision ----

    async def provision(self, plan: ProviderPlan) -> AsyncIterator[ProvisionEvent]:
        try:
            payload = _require_payload(plan)
            async for event in self._provision_inner(plan.target, payload):
                yield event
        except ModalLookupError as exc:
            yield ProvisionFailed(reason=f"Modal lookup failed: {exc}")
        except asyncio.CancelledError:  # pragma: no cover - propagate cancellation
            raise
        except Exception as exc:  # noqa: BLE001 — translate to ProvisionFailed
            yield ProvisionFailed(reason=f"Modal provisioning crashed: {exc}")

    async def _provision_inner(
        self,
        target: ProviderTarget,
        payload: ModalPlanPayload,
    ) -> AsyncIterator[ProvisionEvent]:
        # 1. Resolve the function (may already have a pre-baked web URL).
        if payload.web_url:
            ref = ModalFunctionRef(
                app_name=payload.app_name,
                function_name=payload.function_name,
                web_url=payload.web_url,
            )
        else:
            ref = await self._client.lookup_function(
                app_name=payload.app_name,
                function_name=payload.function_name,
            )

        handle = ProvisionHandle(
            target=target,
            reference=ModalProvisionHandle(
                app_name=ref.app_name,
                function_name=ref.function_name,
                web_url=ref.web_url,
            ),
        )
        yield ProvisioningStarted(handle=handle)

        # 2. Infrastructure ready — Modal hands us a Function object as soon
        # as the App is deployed; the container itself comes up on first
        # request, which we wait for via /healthz.
        yield InfrastructureReady()

        # 3. Poll /healthz until the container is up.
        healthy = False
        for attempt in range(1, self._max_health_attempts + 1):
            try:
                healthy = await self._client.health_check(web_url=ref.web_url)
            except Exception:  # noqa: BLE001 — transient failures are normal during cold-start
                healthy = False
            if healthy:
                break
            # Emit a progress tick roughly every five attempts so the UI sees
            # the deployment is still alive.
            if attempt % 5 == 0:
                percent = min(95, int(40 + (attempt / self._max_health_attempts) * 55))
                yield ProvisioningProgress(
                    percent=percent,
                    message=(
                        f"waiting for /healthz on "
                        f"{ref.function_name} (attempt {attempt})"
                    ),
                )
            await asyncio.sleep(self._poll_interval_s)

        if not healthy:
            yield ProvisionFailed(
                reason=(
                    f"Modal function {ref.function_name!r} did not become "
                    f"healthy within {self._max_health_attempts} polls."
                )
            )
            return

        # 4. Endpoint ready — present an OpenAI-compatible URL.
        endpoint = Endpoint(
            url=_openai_base_url(ref.web_url),
            auth=BearerToken(value=_DEFAULT_BEARER),
            openai_compatible=True,
        )
        yield EndpointReady(endpoint=endpoint)

    # ---- teardown ----

    async def teardown(self, handle: ProvisionHandle) -> None:
        ref = handle.reference
        if not isinstance(ref, ModalProvisionHandle):
            # Foreign handle — best-effort means we silently skip.
            return
        try:
            await self._client.stop_function(
                app_name=ref.app_name, function_name=ref.function_name
            )
        except Exception:  # noqa: BLE001 — teardown is best-effort
            return

    # ---- internals ----

    def _function_name_for(self, repo: str) -> str:
        return (
            self._function_name_3b if repo == _QWEN_3B_REPO else self._function_name_7b
        )

    def _web_url_for(self, repo: str) -> str | None:
        return self._web_url_3b if repo == _QWEN_3B_REPO else self._web_url_7b


# ----- helpers --------------------------------------------------------------


def _pick_cheapest_option(spec: ResourceSpec, repo: str) -> AcceleratorOption | None:
    """Choose the cheapest 24/40 GB option the resolver offered."""
    options = spec.accelerator_options
    if not options:
        return None
    # The resolver lists 3B options as (L4, A10G). L4 is cheaper, so prefer
    # it; for 7B BF16 there's only A100. For 7B AWQ-INT4 there's only A10G.
    # We pick by lowest hourly cost among the options we recognise.
    best_option: AcceleratorOption | None = None
    best_cost: Decimal | None = None
    for option in options:
        accel = option.accelerators[0]
        cost = _hourly_cost_for(accel.name)
        if best_cost is None or cost < best_cost:
            best_cost = cost
            best_option = option
    return best_option


def _hourly_cost_for(accelerator_name: str) -> Decimal:
    if accelerator_name == "L4":
        return _L4_HOURLY_USD
    if accelerator_name == "A10G":
        return _A10G_HOURLY_USD
    if accelerator_name == "A100":
        # 40 GB A100 isn't a SYM-211 happy-path target (the 7B catalog
        # entry compiles to AWQ on COST priority), but quote a reasonable
        # number so the placement policy doesn't blow up on edge cases.
        return Decimal("3.40")
    # Unknown shape — treat as expensive so the policy avoids it.
    return Decimal("99.99")


def _openai_base_url(web_url: str) -> str:
    """Normalise the Modal web URL into the OpenAI-compatible base URL.

    Callers typically POST to ``<base>/chat/completions``; vLLM's OpenAI
    router mounts the standard ``/v1`` prefix, so we return the URL with a
    trailing ``/v1`` and no trailing slash.
    """
    base = web_url.rstrip("/")
    if base.endswith("/v1"):
        return base
    return f"{base}/v1"


def _require_payload(plan: ProviderPlan) -> ModalPlanPayload:
    payload = plan.payload
    if not isinstance(payload, ModalPlanPayload):
        raise TypeError(
            "ModalProviderAdapter received a ProviderPlan whose payload is "
            f"not ModalPlanPayload (got {type(payload).__name__})."
        )
    return payload


__all__ = [
    "ModalPlanPayload",
    "ModalProviderAdapter",
    "ModalProvisionHandle",
]
