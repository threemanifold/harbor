"""Tests for :class:`DefaultModalClient` — the stdlib-only Modal client used
when the runtime isn't configured with the modal SDK."""

from __future__ import annotations

import http.server
import socket
import threading
from collections.abc import Iterator
from contextlib import contextmanager

import pytest

from harbor.infrastructure.providers.modal.client import ModalLookupError
from harbor.infrastructure.providers.modal.default_client import DefaultModalClient


class _Handler(http.server.BaseHTTPRequestHandler):
    healthy: bool = True

    def do_GET(self) -> None:  # noqa: N802 - http.server API
        if self.path != "/healthz":
            self.send_response(404)
            self.end_headers()
            return
        if type(self).healthy:
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(b'{"status":"ok"}')
        else:
            self.send_response(503)
            self.end_headers()

    def log_message(self, format: str, *args: object) -> None:  # noqa: A002
        return  # silence test output


@contextmanager
def _running_server(*, healthy: bool) -> "Iterator[str]":
    handler_cls = type("_HandlerVariant", (_Handler,), {"healthy": healthy})
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    server = http.server.HTTPServer(("127.0.0.1", port), handler_cls)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{port}"
    finally:
        server.shutdown()
        server.server_close()


async def test_health_check_returns_true_on_2xx() -> None:
    with _running_server(healthy=True) as url:
        client = DefaultModalClient(timeout_s=2.0)
        assert await client.health_check(web_url=url) is True


async def test_health_check_returns_false_on_5xx() -> None:
    with _running_server(healthy=False) as url:
        client = DefaultModalClient(timeout_s=2.0)
        assert await client.health_check(web_url=url) is False


async def test_health_check_returns_false_on_connect_error() -> None:
    # Use a reserved-for-discard port that nothing should answer on.
    client = DefaultModalClient(timeout_s=0.5)
    assert await client.health_check(web_url="http://127.0.0.1:9") is False


async def test_health_check_blank_url_returns_false() -> None:
    client = DefaultModalClient()
    assert await client.health_check(web_url="") is False


async def test_lookup_function_raises_modal_lookup_error() -> None:
    client = DefaultModalClient()
    with pytest.raises(ModalLookupError):
        await client.lookup_function(app_name="x", function_name="y")


async def test_stop_function_is_a_noop() -> None:
    client = DefaultModalClient()
    # No assertion possible beyond "doesn't raise".
    await client.stop_function(app_name="x", function_name="y")
