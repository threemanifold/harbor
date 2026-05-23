"""Process entry point.

``uvicorn harbor.main:app`` boots the full Harbor backend with the default
container (empty provider registry until SYM-213 plugs in Modal).
"""

from __future__ import annotations

from harbor.composition.app import create_app

app = create_app()

__all__ = ["app"]
