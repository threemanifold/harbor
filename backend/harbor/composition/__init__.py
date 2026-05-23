"""Composition root.

Re-exports the most common entry points so call sites can write
``from harbor.composition import build_container, create_app``.
"""

from harbor.composition.app import create_app
from harbor.composition.container import Container, build_container
from harbor.composition.ids import UuidIdFactory
from harbor.composition.providers import EmptyProviderRegistry

__all__ = [
    "Container",
    "EmptyProviderRegistry",
    "UuidIdFactory",
    "build_container",
    "create_app",
]
