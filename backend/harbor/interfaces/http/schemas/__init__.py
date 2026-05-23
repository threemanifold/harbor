"""Pydantic schemas for the Harbor HTTP API.

Schemas are grouped by router context:

* :mod:`harbor.interfaces.http.schemas.catalog` — model catalog payloads.
* :mod:`harbor.interfaces.http.schemas.deployments` — deployment lifecycle
  request/response/event payloads.
* :mod:`harbor.interfaces.http.schemas.chat` — OpenAI-compatible chat
  completions pass-through models.
"""
