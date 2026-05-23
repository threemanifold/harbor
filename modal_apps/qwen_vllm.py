"""Modal app that serves Qwen 2.5 (3B and 7B) via vLLM with an
OpenAI-compatible HTTP API.

Deploy with::

    modal deploy modal_apps/qwen_vllm.py

The app is named ``harbor-qwen-vllm`` and exposes two independent ASGI web
endpoints — one per model — so the ``ModalProviderAdapter`` can target either
without bringing up both. Both endpoints:

* Speak OpenAI's ``/v1/chat/completions`` (and the rest of the OpenAI router)
  by mounting vLLM's official ``api_server`` FastAPI app.
* Expose ``/healthz`` for the adapter's provisioning poll.
* Mount the ``harbor-hf`` Modal secret so the in-container Hugging Face Hub
  client can pull gated weights.

This file is a *deployment artifact* — nothing in :mod:`harbor` imports it,
and the ``modal`` SDK is intentionally **not** in
``backend/pyproject.toml``. SYM-213 owns the actual ``modal deploy`` and the
end-to-end smoke test; this ticket only needs the module to exist and be
syntactically deployable.
"""

from __future__ import annotations

import os
from typing import Any

import modal

APP_NAME = "harbor-qwen-vllm"
HF_SECRET_NAME = "harbor-hf"

QWEN_3B_REPO = "Qwen/Qwen2.5-3B-Instruct"
QWEN_7B_REPO = "Qwen/Qwen2.5-7B-Instruct"

# ---- Tunables --------------------------------------------------------------

# Match the recipe compiler in harbor.application.services.recipe_compiler:
# Qwen2.5 supports 32k context out of the box.
_MAX_MODEL_LEN = 32_768

# Modal container lifetime / idle. Both apps spin a single container per
# request; we give them an hour ceiling and 15 minutes of idle before scale
# to zero.
_TIMEOUT_SECONDS = 60 * 60
_SCALEDOWN_WINDOW_SECONDS = 60 * 15
_CONTAINER_IDLE_TIMEOUT = 60 * 5

# ---- Image -----------------------------------------------------------------

# CUDA 12.4 dev image + vLLM 0.6.x + FastAPI + Hugging Face Hub with the
# accelerated downloader. Pinned versions keep cold-starts deterministic
# across redeploys.
_VLLM_IMAGE = (
    modal.Image.from_registry(
        "nvidia/cuda:12.4.1-devel-ubuntu22.04", add_python="3.12"
    )
    .pip_install(
        "vllm==0.6.4",
        "fastapi==0.115.4",
        "huggingface_hub[hf_transfer]==0.26.2",
    )
    .env(
        {
            # Accelerated parallel downloads from the HF Hub.
            "HF_HUB_ENABLE_HF_TRANSFER": "1",
            # Quiet vLLM's usage telemetry on Modal.
            "VLLM_DO_NOT_TRACK": "1",
        }
    )
)

app = modal.App(APP_NAME, image=_VLLM_IMAGE)

_HF_SECRET = modal.Secret.from_name(HF_SECRET_NAME)


# ---- ASGI builder ----------------------------------------------------------


def _build_vllm_asgi_app(
    *,
    model_repo: str,
    quantization: str | None,
) -> Any:
    """Build the FastAPI app that vLLM serves inside a Modal container.

    Imports happen inside the function because the surrounding module is also
    imported on the Modal client (i.e. on the deploy machine) where vLLM and
    CUDA are not installed.
    """
    import fastapi
    from vllm.engine.arg_utils import AsyncEngineArgs
    from vllm.engine.async_llm_engine import AsyncLLMEngine
    from vllm.entrypoints.openai.api_server import (
        build_app as build_vllm_app,
        init_app_state,
    )
    from vllm.entrypoints.openai.cli_args import make_arg_parser
    from vllm.utils import FlexibleArgumentParser

    # Translate our knobs into vLLM's CLI args so we use the same defaults
    # the upstream server applies.
    parser = make_arg_parser(FlexibleArgumentParser())
    cli_args: list[str] = [
        "--model",
        model_repo,
        "--max-model-len",
        str(_MAX_MODEL_LEN),
        "--dtype",
        "bfloat16",
        "--gpu-memory-utilization",
        "0.90",
        "--disable-log-requests",
    ]
    if quantization is not None:
        cli_args += ["--quantization", quantization]
    args = parser.parse_args(cli_args)

    engine_args = AsyncEngineArgs.from_cli_args(args)
    engine = AsyncLLMEngine.from_engine_args(engine_args)

    vllm_app: fastapi.FastAPI = build_vllm_app(args)
    init_app_state(engine, vllm_app.state, args)

    @vllm_app.get("/healthz")
    async def healthz() -> dict[str, str]:
        # AsyncLLMEngine.check_health() raises if the worker is dead, which
        # the ASGI runtime translates to a 5xx — exactly what the adapter's
        # provisioning poll wants to see.
        await engine.check_health()
        return {
            "status": "ok",
            "model": model_repo,
            "revision": os.environ.get("HF_HUB_REVISION", "latest"),
        }

    return vllm_app


# ---- Functions -------------------------------------------------------------


@app.function(
    gpu="L4",
    timeout=_TIMEOUT_SECONDS,
    scaledown_window=_SCALEDOWN_WINDOW_SECONDS,
    container_idle_timeout=_CONTAINER_IDLE_TIMEOUT,
    secrets=[_HF_SECRET],
)
@modal.asgi_app()
def serve_3b() -> Any:
    """Qwen 2.5-3B-Instruct on a single L4 (24 GB), BF16, no quantization."""
    return _build_vllm_asgi_app(model_repo=QWEN_3B_REPO, quantization=None)


@app.function(
    gpu="A10G",
    timeout=_TIMEOUT_SECONDS,
    scaledown_window=_SCALEDOWN_WINDOW_SECONDS,
    container_idle_timeout=_CONTAINER_IDLE_TIMEOUT,
    secrets=[_HF_SECRET],
)
@modal.asgi_app()
def serve_7b() -> Any:
    """Qwen 2.5-7B-Instruct on a single A10G (24 GB), AWQ-INT4."""
    return _build_vllm_asgi_app(model_repo=QWEN_7B_REPO, quantization="awq")
