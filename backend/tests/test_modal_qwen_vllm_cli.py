"""Regression tests for the vLLM CLI args built by ``modal_apps.qwen_vllm``.

The Modal app module imports ``modal`` and ``vllm`` at module/runtime,
neither of which is available in the backend test environment (the
``modal`` SDK is intentionally absent from ``backend/pyproject.toml`` per
the deployment-artifact contract — see :mod:`modal_apps.qwen_vllm`'s
module docstring). To exercise the pure ``_build_cli_args`` helper
without spinning up those imports, we AST-extract just that function
definition and ``exec`` it in an isolated namespace.

The helper is intentionally written to have no module-level dependencies
(no constants, no closures) so this extraction stays trivial.
"""

from __future__ import annotations

import ast
from pathlib import Path
from typing import Any, Callable

# ``backend/tests/`` → ``backend/`` → repo root → ``modal_apps/qwen_vllm.py``
_QWEN_VLLM_SOURCE = Path(__file__).resolve().parents[2] / "modal_apps" / "qwen_vllm.py"


def _load_build_cli_args() -> Callable[..., list[str]]:
    """Extract ``_build_cli_args`` from the Modal app source and exec it.

    We can't ``import modal_apps.qwen_vllm`` here — the import would pull
    in ``modal`` (not installed in this venv). So we parse the file,
    pluck out the ``_build_cli_args`` ``FunctionDef`` node, and compile
    it on its own.
    """
    source = _QWEN_VLLM_SOURCE.read_text()
    tree = ast.parse(source, filename=str(_QWEN_VLLM_SOURCE))
    fn_node = next(
        (
            n
            for n in tree.body
            if isinstance(n, ast.FunctionDef) and n.name == "_build_cli_args"
        ),
        None,
    )
    assert fn_node is not None, (
        "modal_apps/qwen_vllm.py is missing the _build_cli_args helper; "
        "this test relies on it being a top-level pure function."
    )
    module = ast.Module(body=[fn_node], type_ignores=[])
    namespace: dict[str, Any] = {}
    exec(
        compile(module, filename=str(_QWEN_VLLM_SOURCE), mode="exec"),
        namespace,
    )
    fn = namespace["_build_cli_args"]
    assert callable(fn)
    # ``exec``'d definitions land in the namespace as ``Any``; cast through
    # an explicit ``Callable`` annotation so mypy stays strict here.
    typed_fn: Callable[..., list[str]] = fn
    return typed_fn


def test_seven_b_awq_branch_aliases_served_model_name_to_catalog_id() -> None:
    """SYM-221: vLLM must accept the unquantized catalog identifier.

    The 7B endpoint loads the pre-quantized ``Qwen/Qwen2.5-7B-Instruct-AWQ``
    repo, but Harbor's catalog, adapter, and chat proxy all use the
    unquantized name ``Qwen/Qwen2.5-7B-Instruct``. Without an alias the
    chat proxy gets ``404 NotFoundError`` from vLLM.
    """
    build = _load_build_cli_args()
    args = build(
        model_repo="Qwen/Qwen2.5-7B-Instruct-AWQ",
        quantization="awq",
        max_model_len=32_768,
    )

    assert "--served-model-name" in args, (
        "7B branch must alias the served name to the catalog identifier; "
        "without it the chat proxy 404s. See SYM-221."
    )
    idx = args.index("--served-model-name")
    assert args[idx + 1] == "Qwen/Qwen2.5-7B-Instruct"

    # Guard the rest of the awq branch's invariants while we're here.
    assert "--quantization" in args
    assert args[args.index("--quantization") + 1] == "awq"
    assert "--dtype" in args
    assert args[args.index("--dtype") + 1] == "float16"


def test_three_b_dense_branch_does_not_alias_served_model_name() -> None:
    """The 3B (dense BF16) endpoint loads the unquantized repo directly,
    so vLLM's default served name already matches the catalog identifier.
    Aliasing here would be incorrect — and it must not be added by
    accident in a future refactor.
    """
    build = _load_build_cli_args()
    args = build(
        model_repo="Qwen/Qwen2.5-3B-Instruct",
        quantization=None,
        max_model_len=32_768,
    )

    assert "--served-model-name" not in args
    assert "--quantization" not in args
    assert "--dtype" in args
    assert args[args.index("--dtype") + 1] == "bfloat16"


def test_cli_args_carry_model_and_max_len() -> None:
    """Sanity: the helper actually wires through the model repo and the
    context length it's given (so callers can't silently drift)."""
    build = _load_build_cli_args()
    args = build(
        model_repo="Qwen/Qwen2.5-7B-Instruct-AWQ",
        quantization="awq",
        max_model_len=32_768,
    )

    assert "--model" in args
    assert args[args.index("--model") + 1] == "Qwen/Qwen2.5-7B-Instruct-AWQ"
    assert "--max-model-len" in args
    assert args[args.index("--max-model-len") + 1] == "32768"
