from __future__ import annotations

from pathlib import Path

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
    assert "verify" not in kwargs
    assert kwargs["timeout"] == script.REQUEST_TIMEOUT
    assert kwargs["stream"] is True
    assert kwargs["allow_redirects"] is False


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


def test_localize_rejects_missing_content_type(script, tmp_path, capsys):
    url = "http://example.com/download"
    session = FakeSession({url: FakeResponse(headers={})})

    result = make_downloader(script, tmp_path, session).localize(url)

    assert result == url
    assert "Content-Type" in capsys.readouterr().err
    assert list((tmp_path / "media").iterdir()) == []


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

    output = capsys.readouterr().err
    assert result == url
    assert downloader.failed == 1
    assert "[ERROR]" in output
    assert "socks5://127.0.0.1:3066" in output
    assert "unreachable?" in output


def test_localize_reports_http_error_without_hint(script, tmp_path, capsys):
    url = "http://example.com/missing.png"
    session = FakeSession({url: FakeResponse(status_code=404)})

    result = make_downloader(script, tmp_path, session).localize(url)

    output = capsys.readouterr().err
    assert result == url
    assert "HTTP 404" in output
    assert "proxy" not in output


def test_localize_reports_write_error(script, tmp_path, capsys, monkeypatch):
    url = "http://example.com/pic.png"
    session = FakeSession({url: FakeResponse()})

    def fail_write(media_dir, destination, data):
        raise OSError("disk full")

    monkeypatch.setattr(script, "store_download", fail_write)

    result = make_downloader(script, tmp_path, session).localize(url)

    assert result == url
    assert "Failed to save" in capsys.readouterr().err


def test_build_session_limits_redirects(script):
    session = script.build_session(None)
    try:
        assert session.max_redirects == 5
    finally:
        session.close()


def test_filename_for_url_is_deterministic(script):
    first = script.filename_for_url("http://example.com/a.png", ".png")
    second = script.filename_for_url("http://example.com/a.png", ".png")
    other = script.filename_for_url("http://example.com/b.png", ".png")

    assert first == second
    assert first != other
    assert first.startswith("a-") and first.endswith(".png")


@pytest.mark.parametrize(
    ("content_type", "expected"),
    [
        ("image/png", ".png"),
        ("image/jpeg", ".jpg"),
        ("image/PNG", ".png"),
        ("image/vnd.microsoft.icon", ".ico"),
        ("image/svg+xml", ".bin"),
        ("text/html", ".bin"),
        ("", ".bin"),
    ],
)
def test_extension_for_content_type(script, content_type, expected):
    assert script.extension_for_content_type(content_type) == expected


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        ("http://example.com/a.png", "http://example.com/a.png"),
        ("http://Example.COM/a.png#frag", "http://example.com/a.png"),
        ("HTTPS://Example.com:443/a.png", "https://example.com/a.png"),
        ("http://example.com:80/a.png", "http://example.com/a.png"),
        ("http://example.com:8080/a.png", "http://example.com:8080/a.png"),
        ("http://example.com/a.png?x=1#f", "http://example.com/a.png?x=1"),
        (
            "http://user:pw@Example.com/a.png",
            "http://user:pw@example.com/a.png",
        ),
        ("http://[::1]/a.png#x", "http://[::1]/a.png"),
        ("not a url", "not a url"),
    ],
)
def test_canonical_url(script, url, expected):
    assert script.canonical_url(url) == expected


def test_localize_dedupes_urls_differing_by_fragment(script, tmp_path):
    base = "http://example.com/pic.png"
    session = FakeSession({base: FakeResponse()})
    downloader = make_downloader(script, tmp_path, session)

    first = downloader.localize(f"{base}#one")
    second = downloader.localize(f"{base}#two")

    assert first == second
    assert len(session.calls) == 1
    assert session.calls[0][0] == base


def test_localize_returns_original_url_after_cached_failure(script, tmp_path):
    base = "http://example.com/pic.png"
    session = FakeSession({base: FakeResponse(status_code=404)})
    downloader = make_downloader(script, tmp_path, session)

    first = downloader.localize(f"{base}#one")
    second = downloader.localize(f"{base}#two")

    assert first == f"{base}#one"
    assert second == f"{base}#two"
    assert len(session.calls) == 1


def test_filename_for_url_limits_stem_length(script):
    url = "http://example.com/" + "a" * 300 + ".png"

    name = script.filename_for_url(url, ".png")

    stem = name.rsplit("-", 1)[0]
    assert len(stem) <= script.FILENAME_STEM_LIMIT
    assert len(name) <= script.FILENAME_STEM_LIMIT + 1 + 16 + 4


def test_filename_for_url_uses_long_hash(script):
    name = script.filename_for_url("http://example.com/a.png", ".png")

    hash_part = name.rsplit("-", 1)[1].removesuffix(".png")
    assert len(hash_part) == script.URL_HASH_LENGTH
    assert all(char in "0123456789abcdef" for char in hash_part)


def test_filename_for_url_keeps_unicode_stem(script):
    name = script.filename_for_url("http://example.com/картинка.png", ".png")

    assert name.startswith("картинка-")


@pytest.mark.parametrize("reserved", ["CON", "nul", "COM1", "LPT9"])
def test_filename_for_url_escapes_windows_reserved_names(script, reserved):
    name = script.filename_for_url(
        f"http://example.com/{reserved}.png", ".png"
    )

    stem = name.rsplit("-", 1)[0]
    assert stem.lower() not in script.WINDOWS_RESERVED_NAMES
