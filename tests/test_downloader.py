from __future__ import annotations

from pathlib import Path

import certifi
import pytest
import requests

from helpers import PNG_BYTES, FakeResponse, FakeSession


def make_downloader(script, tmp_path: Path, session: FakeSession, proxy_label=None):
    media_dir = tmp_path / "media"
    media_dir.mkdir(parents=True, exist_ok=True)
    return script.Downloader(media_dir, tmp_path, session, proxy_label)


def test_localize_downloads_and_returns_relative_path(script, tmp_path):
    url = "http://example.com/images/pic.png"
    session = FakeSession({url: FakeResponse()})
    downloader = make_downloader(script, tmp_path, session)

    result = downloader.localize(url)

    assert result.startswith("media/pic-")
    assert result.endswith(".png")
    assert (tmp_path / result).read_bytes() == PNG_BYTES
    assert downloader.downloaded == 1
    assert downloader.failed == 0


def test_localize_passes_expected_request_options(script, tmp_path):
    url = "http://example.com/pic.png"
    session = FakeSession({url: FakeResponse()})
    make_downloader(script, tmp_path, session).localize(url)

    _, kwargs = session.calls[0]
    assert kwargs["verify"] == certifi.where()
    assert kwargs["timeout"] == 30


def test_localize_dedupes_same_url(script, tmp_path):
    url = "http://example.com/pic.png"
    session = FakeSession({url: FakeResponse()})
    downloader = make_downloader(script, tmp_path, session)

    first = downloader.localize(url)
    second = downloader.localize(url)

    assert first == second
    assert len(session.calls) == 1
    assert downloader.downloaded == 1


def test_localize_ignores_local_urls(script, tmp_path):
    session = FakeSession()
    downloader = make_downloader(script, tmp_path, session)

    assert downloader.localize("media/pic.png") == "media/pic.png"
    assert downloader.localize("../pic.png") == "../pic.png"
    assert session.calls == []


def test_localize_uses_content_type_extension(script, tmp_path):
    url = "http://example.com/download"
    session = FakeSession({url: FakeResponse(headers={"Content-Type": "image/png"})})

    result = make_downloader(script, tmp_path, session).localize(url)

    assert result.endswith(".png")


def test_localize_falls_back_to_bin(script, tmp_path):
    url = "http://example.com/download"
    session = FakeSession({url: FakeResponse(headers={})})

    result = make_downloader(script, tmp_path, session).localize(url)

    assert result.endswith(".bin")


def test_localize_keeps_query_in_hash(script, tmp_path):
    first_url = "http://example.com/img.png?a=1"
    second_url = "http://example.com/img.png?a=2"
    session = FakeSession(
        {first_url: FakeResponse(), second_url: FakeResponse()}
    )
    downloader = make_downloader(script, tmp_path, session)

    first = downloader.localize(first_url)
    second = downloader.localize(second_url)

    assert first != second
    assert first.endswith(".png") and second.endswith(".png")


def test_localize_reports_connection_error_with_proxy_hint(script, tmp_path, capsys):
    url = "http://example.com/pic.png"
    session = FakeSession({url: requests.ConnectionError("boom")})
    downloader = make_downloader(
        script, tmp_path, session, "socks5://127.0.0.1:3066"
    )

    result = downloader.localize(url)

    output = capsys.readouterr().out
    assert result == url
    assert downloader.failed == 1
    assert "[ERROR]" in output
    assert "socks5://127.0.0.1:3066" in output
    assert "unreachable?" in output


def test_localize_reports_http_error_without_hint(script, tmp_path, capsys):
    url = "http://example.com/missing.png"
    session = FakeSession({url: FakeResponse(status_code=404)})

    result = make_downloader(script, tmp_path, session).localize(url)

    output = capsys.readouterr().out
    assert result == url
    assert "HTTP 404" in output
    assert "proxy" not in output


def test_localize_reports_write_error(script, tmp_path, capsys, monkeypatch):
    url = "http://example.com/pic.png"
    session = FakeSession({url: FakeResponse()})

    def fail_write(self, data):
        raise OSError("disk full")

    monkeypatch.setattr(Path, "write_bytes", fail_write)

    result = make_downloader(script, tmp_path, session).localize(url)

    assert result == url
    assert "Failed to save" in capsys.readouterr().out


def test_filename_for_url_is_deterministic(script):
    first = script.filename_for_url("http://example.com/a.png", ".png")
    second = script.filename_for_url("http://example.com/a.png", ".png")
    other = script.filename_for_url("http://example.com/b.png", ".png")

    assert first == second
    assert first != other
    assert first.startswith("a-") and first.endswith(".png")


@pytest.mark.parametrize(
    ("url", "headers", "expected"),
    [
        ("http://example.com/pic.PNG", {}, ".png"),
        ("http://example.com/pic.php", {}, ".php"),
        ("http://example.com/archive.tar.gz", {}, ".gz"),
        ("http://example.com/pic.verylongextension", {}, ".bin"),
        (
            "http://example.com/pic.verylongextension",
            {"Content-Type": "image/jpeg"},
            ".jpg",
        ),
        (
            "http://example.com/download",
            {"Content-Type": "image/jpeg; charset=x"},
            ".jpg",
        ),
        ("http://example.com/download", {}, ".bin"),
    ],
)
def test_extension_from_response(script, url, headers, expected):
    response = FakeResponse(headers=headers)
    assert script.extension_from_response(response, url) == expected
