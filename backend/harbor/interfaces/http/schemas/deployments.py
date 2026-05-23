"""Pydantic models for the deployments HTTP surface.

This module deliberately avoids re-exporting domain dataclasses; the wire
shape is owned by the interface layer so it can evolve independently of the
aggregate. ``DeploymentEventDTO`` is a discriminated union over the eleven
:mod:`harbor.domain.events` cases — clients dispatch on the ``type`` literal.
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, Field

from harbor.domain.deployment import Deployment, DeploymentState
from harbor.domain.events import (
    DeploymentCompiled,
    DeploymentDegraded,
    DeploymentEvent,
    DeploymentFailed,
    DeploymentHealthy,
    DeploymentPlaced,
    DeploymentProgress,
    DeploymentProvisioning,
    DeploymentRequested,
    DeploymentStarting,
    DeploymentTerminated,
    DeploymentTerminating,
)
from harbor.domain.workflow import Priority, WorkflowType

# ---------- Request body ----------


class DeploymentRequest(BaseModel):
    """Body for ``POST /deployments``.

    Mirrors :class:`harbor.domain.workflow.WorkflowRequest` but flat: the
    router converts this DTO into the domain object before handing it to
    :class:`CreateDeployment`.
    """

    model_ref: str = Field(
        ...,
        description="Model identifier as listed under ``GET /catalog``.",
        min_length=1,
    )
    workflow_type: WorkflowType = Field(
        ...,
        description="High-level workflow type the model will serve.",
    )
    priority: Priority = Field(
        ...,
        description="Tuning priority for placement and compilation.",
    )


# ---------- Response bodies ----------


class DeploymentResponse(BaseModel):
    """Returned synchronously by ``POST /deployments``."""

    deployment_id: str = Field(..., description="Opaque deployment identifier.")


class DeploymentStatus(BaseModel):
    """Returned by ``GET /deployments/{id}``."""

    deployment_id: str
    state: DeploymentState = Field(..., description="Current lifecycle state.")
    endpoint_url: str | None = Field(
        default=None,
        description=(
            "OpenAI-compatible endpoint URL. Only populated once the "
            "deployment reaches ``HEALTHY``."
        ),
    )
    failure_reason: str | None = Field(
        default=None,
        description="Populated when the deployment is in ``FAILED`` state.",
    )
    created_at: datetime
    updated_at: datetime

    @classmethod
    def from_domain(cls, deployment: Deployment) -> "DeploymentStatus":
        return cls(
            deployment_id=deployment.id,
            state=deployment.state,
            endpoint_url=(
                deployment.endpoint.url if deployment.endpoint is not None else None
            ),
            failure_reason=deployment.failure_reason,
            created_at=deployment.created_at,
            updated_at=deployment.updated_at,
        )


# ---------- Event DTOs ----------


class _BaseDeploymentEvent(BaseModel):
    """Fields shared by every variant of :data:`DeploymentEventDTO`."""

    deployment_id: str
    at: datetime


class DeploymentRequestedDTO(_BaseDeploymentEvent):
    type: Literal["requested"] = "requested"


class DeploymentCompiledDTO(_BaseDeploymentEvent):
    type: Literal["compiled"] = "compiled"
    model: str = Field(..., description="Identifier of the compiled model.")
    runtime: str = Field(..., description="Runtime label (e.g. ``vllm``).")
    quantization: str = Field(..., description="Quantization scheme.")
    context_len: int = Field(..., description="Context length in tokens.")


class DeploymentPlacedDTO(_BaseDeploymentEvent):
    type: Literal["placed"] = "placed"
    provider: str = Field(..., description="Provider kind (e.g. ``modal``).")
    region: str = Field(..., description="Region label.")


class DeploymentProvisioningDTO(_BaseDeploymentEvent):
    type: Literal["provisioning"] = "provisioning"


class DeploymentStartingDTO(_BaseDeploymentEvent):
    type: Literal["starting"] = "starting"


class DeploymentProgressDTO(_BaseDeploymentEvent):
    type: Literal["progress"] = "progress"
    percent: int = Field(..., ge=0, le=100)
    message: str


class DeploymentHealthyDTO(_BaseDeploymentEvent):
    type: Literal["healthy"] = "healthy"
    endpoint_url: str = Field(
        ...,
        description=(
            "OpenAI-compatible endpoint URL. Upstream auth headers are kept "
            "server-side; clients use ``POST /deployments/{id}/chat`` to "
            "exchange messages."
        ),
    )


class DeploymentDegradedDTO(_BaseDeploymentEvent):
    type: Literal["degraded"] = "degraded"
    reason: str


class DeploymentTerminatingDTO(_BaseDeploymentEvent):
    type: Literal["terminating"] = "terminating"


class DeploymentTerminatedDTO(_BaseDeploymentEvent):
    type: Literal["terminated"] = "terminated"


class DeploymentFailedDTO(_BaseDeploymentEvent):
    type: Literal["failed"] = "failed"
    reason: str


DeploymentEventDTO = Annotated[
    DeploymentRequestedDTO
    | DeploymentCompiledDTO
    | DeploymentPlacedDTO
    | DeploymentProvisioningDTO
    | DeploymentStartingDTO
    | DeploymentProgressDTO
    | DeploymentHealthyDTO
    | DeploymentDegradedDTO
    | DeploymentTerminatingDTO
    | DeploymentTerminatedDTO
    | DeploymentFailedDTO,
    Field(discriminator="type"),
]


def event_to_dto(event: DeploymentEvent) -> _BaseDeploymentEvent:
    """Translate a domain event to its wire DTO.

    The router serialises the result with ``model_dump_json()``; the union
    annotation is just for OpenAPI exposure.
    """

    if isinstance(event, DeploymentRequested):
        return DeploymentRequestedDTO(deployment_id=event.deployment_id, at=event.at)
    if isinstance(event, DeploymentCompiled):
        return DeploymentCompiledDTO(
            deployment_id=event.deployment_id,
            at=event.at,
            model=event.recipe.model.identifier,
            runtime=event.recipe.runtime.value,
            quantization=event.recipe.quantization.value,
            context_len=event.recipe.context_len,
        )
    if isinstance(event, DeploymentPlaced):
        return DeploymentPlacedDTO(
            deployment_id=event.deployment_id,
            at=event.at,
            provider=event.placement.target.kind.value,
            region=event.placement.region,
        )
    if isinstance(event, DeploymentProvisioning):
        return DeploymentProvisioningDTO(deployment_id=event.deployment_id, at=event.at)
    if isinstance(event, DeploymentStarting):
        return DeploymentStartingDTO(deployment_id=event.deployment_id, at=event.at)
    if isinstance(event, DeploymentProgress):
        return DeploymentProgressDTO(
            deployment_id=event.deployment_id,
            at=event.at,
            percent=event.percent,
            message=event.message,
        )
    if isinstance(event, DeploymentHealthy):
        return DeploymentHealthyDTO(
            deployment_id=event.deployment_id,
            at=event.at,
            endpoint_url=event.endpoint.url,
        )
    if isinstance(event, DeploymentDegraded):
        return DeploymentDegradedDTO(
            deployment_id=event.deployment_id, at=event.at, reason=event.reason
        )
    if isinstance(event, DeploymentTerminating):
        return DeploymentTerminatingDTO(deployment_id=event.deployment_id, at=event.at)
    if isinstance(event, DeploymentTerminated):
        return DeploymentTerminatedDTO(deployment_id=event.deployment_id, at=event.at)
    if isinstance(event, DeploymentFailed):
        return DeploymentFailedDTO(
            deployment_id=event.deployment_id, at=event.at, reason=event.reason
        )
    raise AssertionError(
        f"Unknown deployment event variant: {type(event).__name__}"
    )  # pragma: no cover - mypy exhaustiveness fallback


__all__ = [
    "DeploymentCompiledDTO",
    "DeploymentDegradedDTO",
    "DeploymentEventDTO",
    "DeploymentFailedDTO",
    "DeploymentHealthyDTO",
    "DeploymentPlacedDTO",
    "DeploymentProgressDTO",
    "DeploymentProvisioningDTO",
    "DeploymentRequest",
    "DeploymentRequestedDTO",
    "DeploymentResponse",
    "DeploymentStartingDTO",
    "DeploymentStatus",
    "DeploymentTerminatedDTO",
    "DeploymentTerminatingDTO",
    "event_to_dto",
]
