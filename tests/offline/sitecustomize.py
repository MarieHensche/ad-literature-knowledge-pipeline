"""Disable outbound sockets in CI and inherited Python subprocesses."""

from __future__ import annotations

import os
import socket
from typing import Any


if os.getenv("AD_LIT_TEST_OFFLINE") == "1":
    _original_socket_connect = socket.socket.connect
    _original_socket_connect_ex = socket.socket.connect_ex

    def _blocked_message(address: object) -> str:
        return (
            "External network access is disabled during the offline test suite: "
            f"{address!r}"
        )

    def _offline_connect(self: socket.socket, address: Any) -> None:
        if self.family == socket.AF_UNIX:
            _original_socket_connect(self, address)
            return
        raise RuntimeError(_blocked_message(address))

    def _offline_connect_ex(self: socket.socket, address: Any) -> int:
        if self.family == socket.AF_UNIX:
            return _original_socket_connect_ex(self, address)
        raise RuntimeError(_blocked_message(address))

    def _offline_create_connection(
        address: tuple[str, int],
        timeout: object = socket._GLOBAL_DEFAULT_TIMEOUT,
        source_address: tuple[str, int] | None = None,
        *,
        all_errors: bool = False,
    ) -> socket.socket:
        del timeout, source_address, all_errors
        raise RuntimeError(_blocked_message(address))

    socket.socket.connect = _offline_connect
    socket.socket.connect_ex = _offline_connect_ex
    socket.create_connection = _offline_create_connection
