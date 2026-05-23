"""Pydantic catalog payload.

A flat projection of :class:`harbor.domain.catalog.ModelEntry` suitable for
clients picking a model from a dropdown — strings only, no nested types.
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from harbor.domain.catalog import ModelEntry


class CatalogEntry(BaseModel):
    """One row in the ``GET /catalog`` response."""

    identifier: str = Field(
        ..., description="Model identifier (e.g. ``Qwen/Qwen2.5-3B-Instruct``)."
    )
    parameters_billion: float = Field(..., description="Parameter count in billions.")
    native_dtype: str = Field(..., description="Native weights dtype (e.g. ``bf16``).")
    max_context: int = Field(..., description="Maximum context length in tokens.")
    weights_size_gb: float = Field(
        ..., description="On-disk weights size in gigabytes."
    )

    @classmethod
    def from_domain(cls, entry: ModelEntry) -> "CatalogEntry":
        return cls(
            identifier=entry.ref.identifier,
            parameters_billion=entry.parameters_billion,
            native_dtype=entry.native_dtype.value,
            max_context=entry.max_context,
            weights_size_gb=entry.weights_size_gb,
        )


__all__ = ["CatalogEntry"]
