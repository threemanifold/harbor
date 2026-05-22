from __future__ import annotations

from typing import Protocol

from harbor.domain.identifiers import DeploymentId


class IdFactory(Protocol):
    """Mints new opaque identifiers. Injected into use cases so tests can
    use deterministic IDs (e.g. dep_1, dep_2) instead of random UUIDs."""

    def new_deployment_id(self) -> DeploymentId: ...
