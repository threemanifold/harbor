from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Self

from harbor.domain.endpoint import Endpoint
from harbor.domain.errors import InvalidStateTransition
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
from harbor.domain.identifiers import DeploymentId, OwnerId, TeamId
from harbor.domain.placement import Placement
from harbor.domain.provider_plan import ProviderPlan, ProvisionHandle
from harbor.domain.recipe import Recipe
from harbor.domain.workflow import WorkflowRequest


class DeploymentState(StrEnum):
    REQUESTED = "requested"
    COMPILED = "compiled"
    PLACED = "placed"
    PROVISIONING = "provisioning"
    STARTING = "starting"
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    TERMINATING = "terminating"
    TERMINATED = "terminated"
    FAILED = "failed"


_TERMINAL: frozenset[DeploymentState] = frozenset(
    {DeploymentState.TERMINATED, DeploymentState.FAILED}
)


class Deployment:
    """Aggregate root for a single deployment lifecycle.

    Transition methods enforce state-machine invariants and append events to
    an internal buffer drained by pull_events(). The aggregate performs no
    I/O — persistence is handled by a repository in infrastructure.
    """

    def __init__(
        self,
        *,
        deployment_id: DeploymentId,
        owner: OwnerId,
        team: TeamId,
        request: WorkflowRequest,
        created_at: datetime,
    ) -> None:
        self._id = deployment_id
        self._owner = owner
        self._team = team
        self._request = request
        self._state = DeploymentState.REQUESTED
        self._recipe: Recipe | None = None
        self._placement: Placement | None = None
        self._plan: ProviderPlan | None = None
        self._handle: ProvisionHandle | None = None
        self._endpoint: Endpoint | None = None
        self._failure_reason: str | None = None
        self._created_at = created_at
        self._updated_at = created_at
        self._events: list[DeploymentEvent] = [
            DeploymentRequested(deployment_id=deployment_id, at=created_at),
        ]

    @classmethod
    def start(
        cls,
        *,
        deployment_id: DeploymentId,
        owner: OwnerId,
        team: TeamId,
        request: WorkflowRequest,
        now: datetime,
    ) -> Self:
        return cls(
            deployment_id=deployment_id,
            owner=owner,
            team=team,
            request=request,
            created_at=now,
        )

    # ---- Read-only properties ----

    @property
    def id(self) -> DeploymentId:
        return self._id

    @property
    def owner(self) -> OwnerId:
        return self._owner

    @property
    def team(self) -> TeamId:
        return self._team

    @property
    def request(self) -> WorkflowRequest:
        return self._request

    @property
    def state(self) -> DeploymentState:
        return self._state

    @property
    def recipe(self) -> Recipe | None:
        return self._recipe

    @property
    def placement(self) -> Placement | None:
        return self._placement

    @property
    def plan(self) -> ProviderPlan | None:
        return self._plan

    @property
    def handle(self) -> ProvisionHandle | None:
        return self._handle

    @property
    def endpoint(self) -> Endpoint | None:
        return self._endpoint

    @property
    def failure_reason(self) -> str | None:
        return self._failure_reason

    @property
    def created_at(self) -> datetime:
        return self._created_at

    @property
    def updated_at(self) -> datetime:
        return self._updated_at

    @property
    def is_terminal(self) -> bool:
        return self._state in _TERMINAL

    # ---- Event log ----

    def pull_events(self) -> list[DeploymentEvent]:
        events = self._events
        self._events = []
        return events

    # ---- Transitions ----

    def compile_to(self, recipe: Recipe, *, now: datetime) -> None:
        self._require_state(DeploymentState.REQUESTED, "compile")
        self._recipe = recipe
        self._state = DeploymentState.COMPILED
        self._touch(now)
        self._emit(DeploymentCompiled(deployment_id=self._id, at=now, recipe=recipe))

    def place(self, placement: Placement, *, now: datetime) -> None:
        self._require_state(DeploymentState.COMPILED, "place")
        self._placement = placement
        self._state = DeploymentState.PLACED
        self._touch(now)
        self._emit(
            DeploymentPlaced(deployment_id=self._id, at=now, placement=placement)
        )

    def start_provisioning(
        self,
        *,
        plan: ProviderPlan,
        handle: ProvisionHandle,
        now: datetime,
    ) -> None:
        self._require_state(DeploymentState.PLACED, "start provisioning")
        self._plan = plan
        self._handle = handle
        self._state = DeploymentState.PROVISIONING
        self._touch(now)
        self._emit(DeploymentProvisioning(deployment_id=self._id, at=now))

    def mark_starting(self, *, now: datetime) -> None:
        self._require_state(DeploymentState.PROVISIONING, "mark starting")
        self._state = DeploymentState.STARTING
        self._touch(now)
        self._emit(DeploymentStarting(deployment_id=self._id, at=now))

    def report_progress(self, *, percent: int, message: str, now: datetime) -> None:
        if not 0 <= percent <= 100:
            raise ValueError(f"percent must be in 0..100, got {percent}")
        if self._state not in (
            DeploymentState.PROVISIONING,
            DeploymentState.STARTING,
        ):
            raise InvalidStateTransition(self._state, "report progress")
        self._touch(now)
        self._emit(
            DeploymentProgress(
                deployment_id=self._id,
                at=now,
                percent=percent,
                message=message,
            )
        )

    def mark_healthy(self, endpoint: Endpoint, *, now: datetime) -> None:
        if self._state not in (
            DeploymentState.STARTING,
            DeploymentState.DEGRADED,
        ):
            raise InvalidStateTransition(self._state, "mark healthy")
        self._endpoint = endpoint
        self._state = DeploymentState.HEALTHY
        self._touch(now)
        self._emit(DeploymentHealthy(deployment_id=self._id, at=now, endpoint=endpoint))

    def mark_degraded(self, *, reason: str, now: datetime) -> None:
        self._require_state(DeploymentState.HEALTHY, "mark degraded")
        self._state = DeploymentState.DEGRADED
        self._touch(now)
        self._emit(DeploymentDegraded(deployment_id=self._id, at=now, reason=reason))

    def request_termination(self, *, now: datetime) -> None:
        if self.is_terminal:
            raise InvalidStateTransition(self._state, "request termination")
        if self._state is DeploymentState.TERMINATING:
            return
        self._state = DeploymentState.TERMINATING
        self._touch(now)
        self._emit(DeploymentTerminating(deployment_id=self._id, at=now))

    def mark_terminated(self, *, now: datetime) -> None:
        self._require_state(DeploymentState.TERMINATING, "mark terminated")
        self._state = DeploymentState.TERMINATED
        self._touch(now)
        self._emit(DeploymentTerminated(deployment_id=self._id, at=now))

    def mark_failed(self, *, reason: str, now: datetime) -> None:
        if self.is_terminal:
            raise InvalidStateTransition(self._state, "mark failed")
        self._failure_reason = reason
        self._state = DeploymentState.FAILED
        self._touch(now)
        self._emit(DeploymentFailed(deployment_id=self._id, at=now, reason=reason))

    # ---- Internals ----

    def _require_state(self, expected: DeploymentState, attempted: str) -> None:
        if self._state is not expected:
            raise InvalidStateTransition(self._state, attempted)

    def _emit(self, event: DeploymentEvent) -> None:
        self._events.append(event)

    def _touch(self, now: datetime) -> None:
        self._updated_at = now
