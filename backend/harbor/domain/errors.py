from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from harbor.domain.deployment import DeploymentState


class DomainError(Exception):
    pass


class InvalidStateTransition(DomainError):
    def __init__(self, current: DeploymentState, attempted: str) -> None:
        super().__init__(f"Cannot {attempted} from state {current.value!r}.")
        self.current = current
        self.attempted = attempted
