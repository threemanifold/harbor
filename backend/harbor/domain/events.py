from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from harbor.domain.endpoint import Endpoint
from harbor.domain.identifiers import DeploymentId
from harbor.domain.placement import Placement
from harbor.domain.recipe import Recipe


@dataclass(frozen=True, slots=True)
class DeploymentRequested:
    deployment_id: DeploymentId
    at: datetime


@dataclass(frozen=True, slots=True)
class DeploymentCompiled:
    deployment_id: DeploymentId
    at: datetime
    recipe: Recipe


@dataclass(frozen=True, slots=True)
class DeploymentPlaced:
    deployment_id: DeploymentId
    at: datetime
    placement: Placement


@dataclass(frozen=True, slots=True)
class DeploymentProvisioning:
    deployment_id: DeploymentId
    at: datetime


@dataclass(frozen=True, slots=True)
class DeploymentProgress:
    deployment_id: DeploymentId
    at: datetime
    percent: int
    message: str


@dataclass(frozen=True, slots=True)
class DeploymentHealthy:
    deployment_id: DeploymentId
    at: datetime
    endpoint: Endpoint


@dataclass(frozen=True, slots=True)
class DeploymentDegraded:
    deployment_id: DeploymentId
    at: datetime
    reason: str


@dataclass(frozen=True, slots=True)
class DeploymentTerminating:
    deployment_id: DeploymentId
    at: datetime


@dataclass(frozen=True, slots=True)
class DeploymentTerminated:
    deployment_id: DeploymentId
    at: datetime


@dataclass(frozen=True, slots=True)
class DeploymentFailed:
    deployment_id: DeploymentId
    at: datetime
    reason: str


DeploymentEvent = (
    DeploymentRequested
    | DeploymentCompiled
    | DeploymentPlaced
    | DeploymentProvisioning
    | DeploymentProgress
    | DeploymentHealthy
    | DeploymentDegraded
    | DeploymentTerminating
    | DeploymentTerminated
    | DeploymentFailed
)
