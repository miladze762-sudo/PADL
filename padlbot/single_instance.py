from __future__ import annotations

import socket


class SingleInstanceError(RuntimeError):
    pass


def acquire_single_instance_lock(host: str, port: int) -> socket.socket:
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        sock.bind((host, port))
        sock.listen(1)
    except OSError as exc:
        sock.close()
        raise SingleInstanceError("Another bot instance is already running") from exc
    return sock
