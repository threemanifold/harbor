from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class BearerToken:
    value: str


@dataclass(frozen=True, slots=True)
class HeaderToken:
    name: str
    value: str


@dataclass(frozen=True, slots=True)
class NoAuth:
    pass


EndpointAuth = BearerToken | HeaderToken | NoAuth


@dataclass(frozen=True, slots=True)
class Endpoint:
    url: str
    auth: EndpointAuth
    openai_compatible: bool
