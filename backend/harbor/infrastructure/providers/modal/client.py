"""Thin abstraction over the ``modal`` SDK calls the adapter needs.

The Harbor backend deliberately does **not** depend on the ``modal`` package
(it is a deploy-time / dev tool, not a runtime dep of the API). Wrapping the
operations the adapter needs behind a small Protocol gives us two wins:

1. ``ModalProviderAdapter`` can be unit-tested with a hand-rolled fake
   client — no network, no SDK import.
2. Composition can inject a real ``modal``-SDK-backed client when the
   ``modal`` package is installed, without leaking those imports into the
   provider package's top level (which would break ``import-linter``'s onion
   contracts and crash imports on a stock backend install).

This module deliberately stays a leaf: nothing in :mod:`harbor.domain`
imports it. Tests construct ``ModalProviderAdapter`` directly with a fake
client object that quacks like :class:`ModalClient`.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True, slots=True)
class ModalFunctionRef:
    """Reference to a deployed Modal Function.

    Attributes
    ----------
    app_name:
        The Modal app the function lives in (e.g. ``"harbor-qwen-vllm"``).
    function_name:
        The function's symbolic name (e.g. ``"serve_3b"``).
    web_url:
        The function's deployed HTTPS endpoint (``*.modal.run``).
    """

    app_name: str
    function_name: str
    web_url: str


class ModalLookupError(RuntimeError):
    """Raised by :class:`ModalClient` when the named app/function can't be
    located in the workspace."""


class ModalClient(Protocol):
    """The subset of the ``modal`` SDK that :class:`ModalProviderAdapter`
    actually uses. Implementations are credentialed (the real impl receives
    its token id/secret at construction time)."""

    async def lookup_function(
        self, *, app_name: str, function_name: str
    ) -> ModalFunctionRef: ...

    async def health_check(self, *, web_url: str) -> bool:
        """Return True when the function's ``/healthz`` returns 2xx."""
        ...

    async def stop_function(self, *, app_name: str, function_name: str) -> None:
        """Best-effort teardown — never raises on already-stopped functions."""
        ...


__all__ = [
    "ModalClient",
    "ModalFunctionRef",
    "ModalLookupError",
]
