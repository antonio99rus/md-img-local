from __future__ import annotations

import functools
import http.server
import threading
from pathlib import Path

import pytest

from helpers import PNG_BYTES
from socks5_proxy import Socks5Proxy, reserved_port


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

    run_main(path, "--allow-private")

    output = capsys.readouterr().out
    name = script.filename_for_url(image_server, ".png")
    assert (tmp_path / "media" / name).read_bytes() == PNG_BYTES
    assert f"![img](media/{name})" in path.read_text(encoding="utf-8")
    assert "Downloaded: 1" in output


def test_download_through_socks_proxy(
    script, run_main, tmp_path, image_server, socks_proxy, capsys
):
    path = write_md(tmp_path, image_server)

    run_main(path, f"--proxy={socks_proxy.url}", "--allow-private")

    output = capsys.readouterr().out
    name = script.filename_for_url(image_server, ".png")
    assert socks_proxy.connections >= 1
    assert (tmp_path / "media" / name).read_bytes() == PNG_BYTES
    assert f"![img](media/{name})" in path.read_text(encoding="utf-8")
    assert f"[PROXY] {socks_proxy.url}" in output
    assert "Downloaded: 1" in output


def test_unreachable_proxy_keeps_link(
    script, run_main, tmp_path, image_server, capsys
):
    pytest.importorskip("socks")
    path = write_md(tmp_path, image_server)

    # Порт остаётся занятым (bind без listen), поэтому отказ детерминирован.
    with reserved_port() as port:
        proxy = f"socks5://127.0.0.1:{port}"
        run_main(path, f"--proxy={proxy}", "--allow-private")

    output = capsys.readouterr()
    assert path.read_text(encoding="utf-8") == f"# Заметка\n\n![img]({image_server})\n"
    assert "Downloaded: 0" in output.out
    assert "Errors: 1" in output.out
    assert proxy in output.err
    assert "unreachable?" in output.err


def test_session_uses_environment_proxy_without_flag(script, monkeypatch):
    proxy = "http://127.0.0.1:3128"
    monkeypatch.setenv("HTTP_PROXY", proxy)
    monkeypatch.setenv("HTTPS_PROXY", proxy)
    monkeypatch.setenv("NO_PROXY", "example.invalid")
    monkeypatch.setenv("no_proxy", "example.invalid")
    session = script.build_session(None)
    try:
        settings = session.merge_environment_settings(
            "http://example.com/img.png", {}, False, None, None
        )
    finally:
        session.close()

    assert settings["proxies"]["http"] == proxy
    assert settings["proxies"]["https"] == proxy


def test_explicit_proxy_overrides_environment(
    script,
    run_main,
    tmp_path,
    image_server,
    socks_proxy,
    monkeypatch,
    capsys,
):
    # Эти значения заведомо нерабочие: запрос должен идти через явный --proxy.
    monkeypatch.setenv("HTTP_PROXY", "http://127.0.0.1:1")
    monkeypatch.setenv("HTTPS_PROXY", "http://127.0.0.1:1")
    monkeypatch.setenv("NO_PROXY", "example.invalid")
    monkeypatch.setenv("no_proxy", "example.invalid")
    path = write_md(tmp_path, image_server)

    run_main(path, f"--proxy={socks_proxy.url}", "--allow-private")

    output = capsys.readouterr().out
    name = script.filename_for_url(image_server, ".png")
    assert socks_proxy.connections >= 1
    assert (tmp_path / "media" / name).read_bytes() == PNG_BYTES
    assert f"![img](media/{name})" in path.read_text(encoding="utf-8")
    assert "Downloaded: 1" in output
