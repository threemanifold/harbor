"""Static :class:`~harbor.domain.ports.model_catalog.ModelCatalog`.

Hard-coded catalog seeded with the two Qwen2.5 instruct models that the e2e
slice (SYM-208) supports. The numbers are sourced from the published model
cards on Hugging Face:

* ``Qwen/Qwen2.5-3B-Instruct``: 3.09B parameters, BF16, 32 768 context tokens,
  ~6.2 GB on disk.
* ``Qwen/Qwen2.5-7B-Instruct``: 7.62B parameters, BF16, 32 768 context tokens,
  ~15.2 GB on disk.

Future work will replace this with a HF Hub-backed adapter; the protocol stays
unchanged.
"""

from __future__ import annotations

from collections.abc import Iterable

from harbor.domain.catalog import ModelEntry, ModelRef, WeightsDtype

QWEN2_5_3B_INSTRUCT: ModelEntry = ModelEntry(
    ref=ModelRef(identifier="Qwen/Qwen2.5-3B-Instruct"),
    parameters_billion=3.09,
    native_dtype=WeightsDtype.BF16,
    max_context=32_768,
    weights_size_gb=6.2,
)

QWEN2_5_7B_INSTRUCT: ModelEntry = ModelEntry(
    ref=ModelRef(identifier="Qwen/Qwen2.5-7B-Instruct"),
    parameters_billion=7.62,
    native_dtype=WeightsDtype.BF16,
    max_context=32_768,
    weights_size_gb=15.2,
)

QWEN_DEFAULT_ENTRIES: tuple[ModelEntry, ...] = (
    QWEN2_5_3B_INSTRUCT,
    QWEN2_5_7B_INSTRUCT,
)


class StaticModelCatalog:
    """Dict-backed catalog. Construct directly or via :meth:`qwen_default`."""

    def __init__(self, entries: Iterable[ModelEntry]) -> None:
        self._entries: dict[ModelRef, ModelEntry] = {
            entry.ref: entry for entry in entries
        }

    @classmethod
    def qwen_default(cls) -> "StaticModelCatalog":
        """The Qwen2.5 3B + 7B catalog used by the SYM-208 e2e flow."""
        return cls(QWEN_DEFAULT_ENTRIES)

    async def get(self, ref: ModelRef) -> ModelEntry | None:
        return self._entries.get(ref)
