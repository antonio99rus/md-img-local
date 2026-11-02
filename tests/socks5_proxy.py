from __future__ import annotations

import contextlib
import select
import socket
import struct
import threading
from collections.abc import Iterator


class Socks5Proxy:
    """Минимальный SOCKS5-прокси только для CONNECT (без авторизации)."""

    def __init__(self) -> None:
        self._server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._server.bind(("127.0.0.1", 0))
        self._server.listen(16)
        self._server.settimeout(0.2)
        self._stop = threading.Event()
        self.connections = 0
        self._lock = threading.Lock()
        self._handlers: list[threading.Thread] = []
        self._sockets: set[socket.socket] = set()
        self._thread = threading.Thread(target=self._serve, daemon=True)

    @property
    def port(self) -> int:
        return self._server.getsockname()[1]

    @property
    def url(self) -> str:
        return f"socks5://127.0.0.1:{self.port}"

    def start(self) -> Socks5Proxy:
        self._thread.start()
        return self

    def stop(self) -> None:
        self._stop.set()
        self._thread.join(timeout=5)
        with self._lock:
            sockets = list(self._sockets)
            handlers = list(self._handlers)
        # Будим релей, иначе его select() ждёт до 10 секунд и держит teardown.
        for item in sockets:
            with contextlib.suppress(OSError):
                item.shutdown(socket.SHUT_RDWR)
            with contextlib.suppress(OSError):
                item.close()
        self._server.close()
        for handler in handlers:
            handler.join(timeout=5)

    def _track(self, connection: socket.socket) -> None:
        with self._lock:
            self._sockets.add(connection)

    def _untrack(self, connection: socket.socket) -> None:
        with self._lock:
            self._sockets.discard(connection)

    def _serve(self) -> None:
        while not self._stop.is_set():
            try:
                connection, _ = self._server.accept()
            except TimeoutError:
                continue
            except OSError:
                break
            with self._lock:
                self.connections += 1
                handler = threading.Thread(
                    target=self._handle, args=(connection,), daemon=True
                )
                self._handlers.append(handler)
            handler.start()

    @staticmethod
    def _read(connection: socket.socket, size: int) -> bytes:
        data = b""
        while len(data) < size:
            chunk = connection.recv(size - len(data))
            if not chunk:
                raise ConnectionError("unexpected eof")
            data += chunk
        return data

    def _handle(self, connection: socket.socket) -> None:
        upstream = None
        self._track(connection)
        try:
            _, method_count = self._read(connection, 2)
            self._read(connection, method_count)
            connection.sendall(b"\x05\x00")

            _, command, _, address_type = self._read(connection, 4)
            if address_type == 1:
                host = socket.inet_ntoa(self._read(connection, 4))
            elif address_type == 3:
                host = self._read(connection, self._read(connection, 1)[0]).decode()
            else:
                host = socket.inet_ntop(socket.AF_INET6, self._read(connection, 16))
            port = struct.unpack("!H", self._read(connection, 2))[0]

            if command != 1:
                connection.sendall(b"\x05\x07\x00\x01" + b"\x00" * 6)
                return

            upstream = socket.create_connection((host, port), timeout=10)
            self._track(upstream)
            connection.sendall(b"\x05\x00\x00\x01" + b"\x00" * 6)
            self._relay(connection, upstream)
        except OSError:
            pass
        finally:
            self._untrack(connection)
            connection.close()
            if upstream is not None:
                self._untrack(upstream)
                upstream.close()

    @staticmethod
    def _relay(client: socket.socket, upstream: socket.socket) -> None:
        sockets = [client, upstream]
        while True:
            try:
                readable, _, _ = select.select(sockets, [], [], 10)
            except OSError:
                return
            if not readable:
                return
            for source in readable:
                data = source.recv(65536)
                if not data:
                    return
                (upstream if source is client else client).sendall(data)


@contextlib.contextmanager
def reserved_port() -> Iterator[int]:
    """Держит порт занятым, не слушая его: connect гарантированно получает отказ."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        sock.bind(("127.0.0.1", 0))
        yield sock.getsockname()[1]
    finally:
        sock.close()
