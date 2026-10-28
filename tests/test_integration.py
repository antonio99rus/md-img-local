from __future__ import annotations

import functools
import http.server
import threading
from pathlib import Path

import pytest

from helpers import PNG_BYTES
from socks5_proxy import Socks5Proxy, free_port


class QuietHandler(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *args):  # noqa: A002 - подпись из стандартной библиотеки
        pass


@pytest.fixture
def image_server(tmp_path):
    root = tmp_path / "site"
    root.mkdir()
    (root / "img.png").write_bytes(PNG_BYTES)

    handler = functools.partial(QuietHandler, directory=str(root))
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}/img.png"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


@pytest.fixture
def socks_proxy():
    pytest.importorskip("socks")
    proxy = Socks5Proxy().start()
    try:
        yield proxy
    finally:
        proxy.stop()


def write_md(tmp_path: Path, url: str) -> Path:
    path = tmp_path / "note.md"
    path.write_text(f"# Заметка\n\n![img]({url})\n", encoding="utf-8")
    return path


def test_download_without_proxy(script, run_main, tmp_path, image_server, capsys):
    path = write_md(tmp_path, image_server)

    run_main(path)

    output = capsys.readouterr().out
    name = script.filename_for_url(image_server, ".png")
    assert (tmp_path / "media" / name).read_bytes() == PNG_BYTES
    assert f"![img](media/{name})" in path.read_text(encoding="utf-8")
    assert "Скачано: 1" in output


def test_download_through_socks_proxy(
    script, run_main, tmp_path, image_server, socks_proxy, capsys
):
    path = write_md(tmp_path, image_server)

    run_main(path, f"--proxy={socks_proxy.url}")

    output = capsys.readouterr().out
    name = script.filename_for_url(image_server, ".png")
    assert socks_proxy.connections >= 1
    assert (tmp_path / "media" / name).read_bytes() == PNG_BYTES
    assert f"![img](media/{name})" in path.read_text(encoding="utf-8")
    assert f"[PROXY] {socks_proxy.url}" in output
    assert "Скачано: 1" in output


def test_unreachable_proxy_keeps_link(
    script, run_main, tmp_path, image_server, capsys
):
    path = write_md(tmp_path, image_server)
    proxy = f"socks5://127.0.0.1:{free_port()}"

    run_main(path, f"--proxy={proxy}")

    output = capsys.readouterr().out
    assert path.read_text(encoding="utf-8") == f"# Заметка\n\n![img]({image_server})\n"
    assert "Скачано: 0" in output
    assert "Ошибок: 1" in output
    assert proxy in output
    assert "недоступен?" in output
