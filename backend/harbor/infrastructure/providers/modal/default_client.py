"""Stdlib-only default :class:`ModalClient` for the Harbor backend.

This implementation deliberately avoids importing the ``modal`` SDK so the
runtime stays light. It assumes the deployment URLs are pre-resolved via
``MODAL_WEB_URL_3B`` / ``MODAL_WEB_URL_7B`` env vars — the path SYM-211 is
explicitly scoped to (the real ``modal deploy`` lives in SYM-213).

Capabilities
------------
* :meth:`lookup_function` — only useful when the caller did *not* pre-resolve
  a URL. Raises :class:`ModalLookupError` so the adapter falls back to its
  diagnostic path. A future ticket can plug in a real Modal SDK implementation.
* :meth:`health_check` — performs an HTTPS GET against ``<web_url>/healthz``
  with a short per-request timeout, run on a background thread so we never
  block the event loop.
* :meth:`stop_function` — no-op; Modal Functions scale to zero on their own
  via the ``scaledown_window`` configured in :mod:`modal_apps.qwen_vllm`.

Tests inject their own fake client; this default exists solely so the
composition root can wire a real registry without pulling in a heavy SDK.
"""

from __future__ import annotations

import asyncio
import urllib.error
import urllib.request

from harbor.infrastructure.providers.modal.client import (
    ModalFunctionRef,
    ModalLookupError,
)


class DefaultModalClient:
    """HTTP-only Modal client suitable for env-plumbed deployments.

    Parameters
    ----------
    timeout_s:
        Per-request timeout for ``/healthz`` polls. Modal cold-starts can be
        long, but each individual request should resolve quickly; the polling
        loop in :class:`ModalProviderAdapter` handles overall patience.
    """

    def __init__(self, *, timeout_s: float = 5.0) -> None:
        self._timeout_s = timeout_s

    async def lookup_function(
        self, *, app_name: str, function_name: str
    ) -> ModalFunctionRef:
        raise ModalLookupError(
            "DefaultModalClient cannot resolve Modal Function URLs without "
            "the modal SDK. Set MODAL_WEB_URL_3B / MODAL_WEB_URL_7B in the "
            "env so the adapter can skip lookup, or wire a real "
            "modal-SDK-backed client into composition."
        )

    async def health_check(self, *, web_url: str) -> bool:
        if not web_url:
            return False
        target = web_url.rstrip("/") + "/healthz"
        return await asyncio.to_thread(self._sync_health, target)

    def _sync_health(self, url: str) -> bool:
        request = urllib.request.Request(url, method="GET")
        try:
            with urllib.request.urlopen(request, timeout=self._timeout_s) as response:
                status: int = int(response.status)
                return 200 <= status < 300
        except (urllib.error.URLError, TimeoutError, ConnectionError):
            return False

    async def stop_function(self, *, app_name: str, function_name: str) -> None:
        # Modal Functions scale to zero on the configured idle window; an
        # explicit stop would require the modal SDK. The adapter treats
        # teardown as best-effort, so silently returning is correct.
        return None


__all__ = ["DefaultModalClient"]
