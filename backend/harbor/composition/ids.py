"""UUID-backed :class:`~harbor.domain.ports.id_factory.IdFactory`.

Produces opaque, URL-safe deployment ids of the form ``dep_<12-hex-chars>``.
Lives in :mod:`harbor.composition` because identifier minting is a wiring
concern — the use case doesn't care how ids are generated, only that the port
returns a fresh value each call.
"""

from __future__ import annotations

import uuid

from harbor.domain.identifiers import DeploymentId


class UuidIdFactory:
    """Random UUID4-based id factory.

    The full uuid is trimmed to 12 hex chars — 48 bits of entropy, plenty for
    a single development backend, and short enough to keep logs scannable.
    """

    def new_deployment_id(self) -> DeploymentId:
        return DeploymentId(f"dep_{uuid.uuid4().hex[:12]}")
