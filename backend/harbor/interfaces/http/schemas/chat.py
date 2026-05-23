"""OpenAI-compatible chat completions request body.

The proxy is intentionally pass-through: any field OpenAI defines (tools,
``response_format``, ``stop``, ...) is accepted via ``model_config["extra"]
= "allow"`` and forwarded verbatim. The schema only validates the few keys
the proxy needs to read (``model``, ``messages``, ``stream``).

``ChatResponse`` mirrors the non-streaming OpenAI response. It is exposed
solely so FastAPI can document the route in the generated OpenAPI schema —
the proxy returns the upstream body verbatim and does **not** validate it.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

# ---------- Request ----------


class ChatMessage(BaseModel):
    """One message in a chat completion request.

    Mirrors OpenAI's message shape but stays permissive: ``content`` is
    typed as ``Any`` so multi-modal arrays (``[{type: "text", ...}]``) pass
    through unchanged.
    """

    model_config = ConfigDict(extra="allow")

    role: Literal["system", "user", "assistant", "tool", "developer"] = Field(
        ..., description="Author of this message."
    )
    content: Any = Field(
        default=None,
        description=(
            "Message content. String for text-only messages; array of parts "
            "for multi-modal content; null for tool/assistant messages that "
            "only carry tool calls."
        ),
    )


class ChatRequest(BaseModel):
    """Body for ``POST /deployments/{id}/chat``.

    Accepts every OpenAI-defined field via ``extra="allow"`` so the proxy
    can pass it through to the upstream verbatim. The proxy itself only
    inspects ``stream`` to choose between buffered JSON and streamed SSE
    response handling.
    """

    model_config = ConfigDict(extra="allow")

    model: str = Field(..., description="Model identifier.", min_length=1)
    messages: list[ChatMessage] = Field(
        ..., description="Chat history sent to the model.", min_length=1
    )
    stream: bool = Field(
        default=False,
        description=(
            "When ``true`` the upstream's SSE stream is forwarded to the "
            "client as ``text/event-stream``; otherwise the upstream JSON "
            "body is returned in full."
        ),
    )


# ---------- Response ----------


class ChatResponse(BaseModel):
    """OpenAI chat completion response — for documentation only.

    The proxy never deserialises into this model. It is referenced from the
    ``response_model`` on the non-streaming code path so the generated
    OpenAPI spec advertises a sensible shape.
    """

    model_config = ConfigDict(extra="allow")

    id: str
    object: Literal["chat.completion"] = "chat.completion"
    created: int
    model: str
    choices: list[dict[str, Any]]
    usage: dict[str, Any] | None = None


__all__ = ["ChatMessage", "ChatRequest", "ChatResponse"]
