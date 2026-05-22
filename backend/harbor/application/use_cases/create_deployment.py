from __future__ import annotations

import asyncio
from typing import assert_never

from harbor.domain.deployment import Deployment
from harbor.domain.errors import NoFeasibleProvider
from harbor.domain.identifiers import DeploymentId, OwnerId, TeamId
from harbor.domain.placement import Feasibility, ProviderTarget
from harbor.domain.ports.clock import Clock
from harbor.domain.ports.deployment_repository import DeploymentRepository
from harbor.domain.ports.event_bus import EventBus
from harbor.domain.ports.id_factory import IdFactory
from harbor.domain.ports.model_catalog import ModelCatalog
from harbor.domain.ports.provider_adapter import (
    EndpointReady,
    InfrastructureReady,
    ProvisionFailed,
    ProvisioningProgress,
    ProvisioningStarted,
)
from harbor.domain.ports.provider_registry import ConnectedProviderRegistry
from harbor.domain.services.placement_policy import PlacementPolicy
from harbor.domain.services.recipe_compiler import RecipeCompiler
from harbor.domain.services.resource_resolver import ResourceResolver
from harbor.domain.workflow import WorkflowRequest


class CreateDeployment:
    """Orchestrates the seven-step flow from a user's WorkflowRequest to a
    healthy deployed endpoint. All dependencies are domain ports or strategy
    Protocols — no I/O happens here, it's pushed to the adapters. The use
    case awaits provisioning to completion; production callers (HTTP route)
    are expected to wrap execute() in asyncio.create_task so the request
    returns immediately and the chat UI subscribes to events via the bus."""

    def __init__(
        self,
        *,
        catalog: ModelCatalog,
        compiler: RecipeCompiler,
        resolver: ResourceResolver,
        policy: PlacementPolicy,
        providers: ConnectedProviderRegistry,
        repo: DeploymentRepository,
        bus: EventBus,
        clock: Clock,
        id_factory: IdFactory,
    ) -> None:
        self._catalog = catalog
        self._compiler = compiler
        self._resolver = resolver
        self._policy = policy
        self._providers = providers
        self._repo = repo
        self._bus = bus
        self._clock = clock
        self._id_factory = id_factory

    async def execute(
        self,
        *,
        request: WorkflowRequest,
        owner: OwnerId,
        team: TeamId,
    ) -> DeploymentId:
        dep = Deployment.start(
            deployment_id=self._id_factory.new_deployment_id(),
            owner=owner,
            team=team,
            request=request,
            now=self._clock.now(),
        )
        await self._commit(dep)

        entry = await self._catalog.get(request.model_ref)
        if entry is None:
            dep.mark_failed(
                reason=(
                    f"Model not found in catalog: {request.model_ref.identifier!r}"
                ),
                now=self._clock.now(),
            )
            await self._commit(dep)
            return dep.id

        recipe = self._compiler.compile(request, entry)
        dep.compile_to(recipe, now=self._clock.now())
        await self._commit(dep)

        spec = self._resolver.resolve(recipe)

        targets = await self._providers.list_targets(team)
        if not targets:
            dep.mark_failed(
                reason="No providers connected for this team.",
                now=self._clock.now(),
            )
            await self._commit(dep)
            return dep.id

        feasibilities = await asyncio.gather(
            *(adapter.feasibility(recipe, spec) for _, adapter in targets)
        )
        candidates: tuple[tuple[ProviderTarget, Feasibility], ...] = tuple(
            (target, feas)
            for (target, _adapter), feas in zip(targets, feasibilities, strict=True)
        )

        try:
            placement = self._policy.select(
                recipe=recipe, spec=spec, candidates=candidates
            )
        except NoFeasibleProvider as exc:
            dep.mark_failed(reason=str(exc), now=self._clock.now())
            await self._commit(dep)
            return dep.id

        dep.place(placement, now=self._clock.now())
        await self._commit(dep)

        adapter = next(a for t, a in targets if t == placement.target)
        plan = await adapter.plan(recipe, placement)

        try:
            async for event in adapter.provision(plan):
                if isinstance(event, ProvisioningStarted):
                    dep.start_provisioning(
                        plan=plan, handle=event.handle, now=self._clock.now()
                    )
                    await self._commit(dep)
                elif isinstance(event, ProvisioningProgress):
                    dep.report_progress(
                        percent=event.percent,
                        message=event.message,
                        now=self._clock.now(),
                    )
                    await self._commit(dep)
                elif isinstance(event, InfrastructureReady):
                    dep.mark_starting(now=self._clock.now())
                    await self._commit(dep)
                elif isinstance(event, EndpointReady):
                    dep.mark_healthy(event.endpoint, now=self._clock.now())
                    await self._commit(dep)
                    break
                elif isinstance(event, ProvisionFailed):
                    dep.mark_failed(reason=event.reason, now=self._clock.now())
                    await self._commit(dep)
                    break
                else:
                    assert_never(event)
        except Exception as exc:
            if not dep.is_terminal:
                dep.mark_failed(
                    reason=f"Provisioning crashed: {exc!s}",
                    now=self._clock.now(),
                )
                await self._commit(dep)
            raise

        return dep.id

    async def _commit(self, dep: Deployment) -> None:
        await self._repo.save(dep)
        for event in dep.pull_events():
            await self._bus.publish(event)
