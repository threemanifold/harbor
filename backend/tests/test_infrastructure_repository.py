from datetime import UTC, datetime

from harbor.domain.catalog import ModelRef
from harbor.domain.deployment import Deployment
from harbor.domain.identifiers import DeploymentId, OwnerId, TeamId
from harbor.domain.workflow import Priority, Tuning, WorkflowRequest, WorkflowType
from harbor.infrastructure.persistence.memory import InMemoryDeploymentRepository

T0 = datetime(2026, 5, 22, 12, 0, 0, tzinfo=UTC)
TEAM_A = TeamId("team_a")
TEAM_B = TeamId("team_b")


def _request() -> WorkflowRequest:
    return WorkflowRequest(
        model_ref=ModelRef(identifier="Qwen/Qwen2.5-3B-Instruct"),
        workflow_type=WorkflowType.CHAT,
        tuning=Tuning(priority=Priority.QUALITY),
    )


def _new(*, dep_id: str, team: TeamId) -> Deployment:
    return Deployment.start(
        deployment_id=DeploymentId(dep_id),
        owner=OwnerId("owner"),
        team=team,
        request=_request(),
        now=T0,
    )


async def test_save_then_get_round_trips_the_aggregate() -> None:
    repo = InMemoryDeploymentRepository()
    dep = _new(dep_id="dep_1", team=TEAM_A)
    await repo.save(dep)
    loaded = await repo.get(DeploymentId("dep_1"))
    assert loaded is dep


async def test_get_unknown_id_returns_none() -> None:
    repo = InMemoryDeploymentRepository()
    assert await repo.get(DeploymentId("dep_nope")) is None


async def test_save_overwrites_in_place() -> None:
    repo = InMemoryDeploymentRepository()
    dep = _new(dep_id="dep_1", team=TEAM_A)
    await repo.save(dep)
    # Mutating the aggregate (via a transition) and saving again should not
    # duplicate it — the repo should still expose a single entry.
    from harbor.domain.catalog import WeightsDtype
    from harbor.domain.recipe import (
        HuggingFaceHub,
        Quantization,
        Recipe,
        Runtime,
        ServingPolicy,
    )

    recipe = Recipe(
        model=ModelRef(identifier="Qwen/Qwen2.5-3B-Instruct"),
        runtime=Runtime.VLLM,
        weights_dtype=WeightsDtype.BF16,
        quantization=Quantization.NONE,
        context_len=32_768,
        artifact_source=HuggingFaceHub(repo="Qwen/Qwen2.5-3B-Instruct"),
        serving=ServingPolicy(tensor_parallel=1, replicas=1),
        tuning=Tuning(priority=Priority.QUALITY),
    )
    dep.compile_to(recipe, now=T0)
    await repo.save(dep)
    listed = await repo.list_for_team(TEAM_A)
    assert len(listed) == 1
    assert listed[0] is dep


async def test_list_for_team_filters_by_team() -> None:
    repo = InMemoryDeploymentRepository()
    dep_a = _new(dep_id="dep_a", team=TEAM_A)
    dep_b = _new(dep_id="dep_b", team=TEAM_B)
    dep_a2 = _new(dep_id="dep_a2", team=TEAM_A)
    await repo.save(dep_a)
    await repo.save(dep_b)
    await repo.save(dep_a2)

    a_results = await repo.list_for_team(TEAM_A)
    b_results = await repo.list_for_team(TEAM_B)

    a_ids = {d.id for d in a_results}
    b_ids = {d.id for d in b_results}
    assert a_ids == {DeploymentId("dep_a"), DeploymentId("dep_a2")}
    assert b_ids == {DeploymentId("dep_b")}


async def test_list_for_team_empty_when_no_deployments() -> None:
    repo = InMemoryDeploymentRepository()
    assert await repo.list_for_team(TEAM_A) == ()
