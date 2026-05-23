"""Environment-backed configuration for the Modal provider adapter.

Reads Modal workspace credentials and the deployed Modal web URLs for the
Qwen2.5 3B / 7B vLLM endpoints (see :mod:`modal_apps.qwen_vllm`).

Per the ``Config has no internal harbor imports`` import-linter contract,
this module imports nothing from :mod:`harbor`; it is consumed exclusively
from :mod:`harbor.composition`.
"""

from __future__ import annotations

import os
from dataclasses import dataclass


class ModalConfigError(ValueError):
    """Raised when the Modal env config is incomplete or inconsistent."""


@dataclass(frozen=True, slots=True)
class ModalConfig:
    """Resolved Modal env config.

    Attributes
    ----------
    token_id, token_secret:
        Modal API credentials (the equivalent of ``modal token set``).
    workspace:
        The Modal workspace these credentials belong to. The adapter uses it
        to look up the deployed ``harbor-qwen-vllm`` app.
    web_url_3b, web_url_7b:
        Optional pre-resolved web URLs for the ``serve_3b`` / ``serve_7b``
        functions. When set, the adapter skips Modal-side lookup and goes
        straight to health polling — useful in dev when SYM-213 has already
        ``modal deploy``-ed the app.
    hf_token:
        Optional Hugging Face token surfaced to the adapter for logs /
        debugging. The Modal Function itself reads ``HF_TOKEN`` from the
        ``harbor-hf`` Modal Secret, not from this value.
    """

    token_id: str
    token_secret: str
    workspace: str
    web_url_3b: str | None = None
    web_url_7b: str | None = None
    hf_token: str | None = None


def load_modal_config(
    env: "os._Environ[str] | dict[str, str] | None" = None,
) -> ModalConfig:
    """Load :class:`ModalConfig` from process env (or an injected mapping).

    Raises
    ------
    ModalConfigError
        If any of the required variables is missing or blank.
    """
    source: dict[str, str] | os._Environ[str]
    source = env if env is not None else os.environ

    def _required(name: str) -> str:
        value = source.get(name, "").strip()
        if not value:
            raise ModalConfigError(f"Missing required Modal env variable: {name!r}.")
        return value

    def _optional(name: str) -> str | None:
        value = source.get(name, "").strip()
        return value or None

    return ModalConfig(
        token_id=_required("MODAL_TOKEN_ID"),
        token_secret=_required("MODAL_TOKEN_SECRET"),
        workspace=_required("MODAL_WORKSPACE"),
        web_url_3b=_optional("MODAL_WEB_URL_3B"),
        web_url_7b=_optional("MODAL_WEB_URL_7B"),
        hf_token=_optional("HF_TOKEN"),
    )


def try_load_modal_config(
    env: "os._Environ[str] | dict[str, str] | None" = None,
) -> ModalConfig | None:
    """Return :class:`ModalConfig` if Modal env vars are set, otherwise None.

    Composition uses this to decide whether to wire the real Modal registry
    or fall back to the empty / fake one (for tests and ``/health`` smoke).
    """
    source = env if env is not None else os.environ
    if not any(
        source.get(name, "").strip()
        for name in ("MODAL_TOKEN_ID", "MODAL_TOKEN_SECRET", "MODAL_WORKSPACE")
    ):
        return None
    return load_modal_config(env)


__all__ = [
    "ModalConfig",
    "ModalConfigError",
    "load_modal_config",
    "try_load_modal_config",
]
