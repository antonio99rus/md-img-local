from __future__ import annotations

from pathlib import Path

import pytest
import requests

from helpers import PNG_BYTES, FakeResponse, FakeSession

URL = "http://example.com/pic.png"


def make_downloader(
    script, tmp_path: Path, session: FakeSession, allow_private: bool = False
):
    media_dir = tmp_path / "media"
    return script.Downloader(
        media_dir, tmp_path, session, allow_private=allow_private
    )


def redirect(location: str, status: int = 302) -> FakeResponse:
    return FakeResponse(headers={"Location": location}, status_code=status)


def test_mask_url_hides_userinfo(script):
    masked = script.mask_url("http://user:secret@example.com/a.png")

    assert masked == "http://***@example.com/a.png"
    assert "secret" not in masked
    assert "user" not in masked


def test_mask_url_hides_password_without_username(script):
    masked = script.mask_url("http://:secret@example.com/a.png")

    assert masked == "http://***@example.com/a.png"


def test_mask_url_hides_sensitive_query_values(script):
    masked = script.mask_url(
        "https://example.com/a.png?token=abc&size=2&X-Amz-Signature=deadbeef"
    )

    assert "token=***" in masked
    assert "X-Amz-Signature=***" in masked
    assert "size=2" in masked
    assert "abc" not in masked
    assert "deadbeef" not in masked


def test_mask_url_drops_fragment_and_limits_length(script):
    masked = script.mask_url("http://example.com/" + "a" * 500 + "#frag")

    assert len(masked) <= script.LOG_URL_LIMIT
    assert "#frag" not in masked


def test_mask_url_replaces_control_characters(script):
    masked = script.mask_url("http://example.com/a\x00b\x1b.png")

    assert "\x00" not in masked
    assert "\x1b" not in masked


def test_proxy_unsupported_masks_credentials(script):
    with pytest.raises(script.ProxyConfigError) as error:
        script.parse_proxy("ftp://user:secret@127.0.0.1:3128")

    message = str(error.value)
    assert "secret" not in message
    assert "user" not in message
    assert "***@" in message


@pytest.mark.parametrize(
    "address",
    [
        "127.0.0.1",
        "10.1.2.3",
        "192.168.0.1",
        "172.16.0.1",
        "169.254.1.1",
        "0.0.0.0",
        "224.0.0.1",
        "::1",
        "fd00::1",
        "fe80::1",
        "::ffff:127.0.0.1",
    ],
)
def test_private_and_special_addresses_are_blocked(script, address):
    assert script.is_blocked_address(address) is True


@pytest.mark.parametrize(
    "address",
    ["93.184.216.34", "8.8.8.8", "2606:2800:220:1:248:1893:25c8:1946"],
)
def test_public_addresses_are_allowed(script, address):
    assert script.is_blocked_address(address) is False


def test_ensure_url_allowed_accepts_public_host(script):
    script.ensure_url_allowed("https://example.com/a.png")


@pytest.mark.parametrize(
    "url",
    [
        "http://127.0.0.1/a.png",
        "http://10.0.0.5/a.png",
        "http://169.254.169.254/latest/meta-data/",
        "http://[::1]/a.png",
    ],
)
def test_ensure_url_allowed_rejects_private_addresses(script, url):
    with pytest.raises(script.UrlBlocked, match="private"):
        script.ensure_url_allowed(url)


def test_ensure_url_allowed_can_be_overridden(script):
    script.ensure_url_allowed("http://127.0.0.1/a.png", allow_private=True)


@pytest.mark.parametrize("url", ["ftp://example.com/a.png", "file:///etc/passwd"])
def test_ensure_url_allowed_rejects_other_schemes(script, url):
    with pytest.raises(script.UrlBlocked, match="scheme"):
        script.ensure_url_allowed(url)


def test_ensure_url_allowed_requires_host(script):
    with pytest.raises(script.UrlBlocked, match="host"):
        script.ensure_url_allowed("http:///a.png")


def test_ensure_url_allowed_rejects_unresolvable_host(script, monkeypatch):
    def failing_getaddrinfo(*args, **kwargs):
        raise OSError("name resolution failed")

    monkeypatch.setattr(script.socket, "getaddrinfo", failing_getaddrinfo)

    with pytest.raises(script.UrlBlocked, match="resolve"):
        script.ensure_url_allowed("http://missing.example/a.png")


def test_downloader_blocks_private_url_without_request(
    script, tmp_path, capsys
):
    session = FakeSession({URL: FakeResponse()})
    downloader = make_downloader(script, tmp_path, session)

    result = downloader.localize("http://127.0.0.1/a.png")

    assert result == "http://127.0.0.1/a.png"
    assert session.calls == []
    assert downloader.failed == 1
    assert "private" in capsys.readouterr().err


def test_downloader_allows_private_url_when_opted_in(script, tmp_path):
    url = "http://127.0.0.1/a.png"
    session = FakeSession({url: FakeResponse()})
    downloader = make_downloader(script, tmp_path, session, allow_private=True)

    result = downloader.localize(url)

    assert result.startswith("media/")
    assert (tmp_path / result).read_bytes() == PNG_BYTES
    assert downloader.downloaded == 1


def test_downloader_follows_relative_redirect(script, tmp_path):
    session = FakeSession(
        {
            URL: redirect("final.png"),
            "http://example.com/final.png": FakeResponse(),
        }
    )
    downloader = make_downloader(script, tmp_path, session)

    result = downloader.localize(URL)

    assert result.startswith("media/")
    assert [call[0] for call in session.calls] == [
        URL,
        "http://example.com/final.png",
    ]


def test_downloader_checks_redirect_target(script, tmp_path, capsys):
    session = FakeSession(
        {
            URL: redirect("http://127.0.0.1/secret.png"),
        }
    )
    downloader = make_downloader(script, tmp_path, session)

    result = downloader.localize(URL)

    assert result == URL
    assert [call[0] for call in session.calls] == [URL]
    assert downloader.failed == 1
    assert "private" in capsys.readouterr().err


def test_downloader_limits_redirects(script, tmp_path, capsys):
    session = FakeSession({URL: redirect("/pic.png")})
    downloader = make_downloader(script, tmp_path, session)

    result = downloader.localize(URL)

    assert result == URL
    assert len(session.calls) == script.MAX_REDIRECTS + 1
    assert downloader.failed == 1
    assert "redirects" in capsys.readouterr().err


def test_downloader_rejects_redirect_without_location(
    script, tmp_path, capsys
):
    session = FakeSession({URL: FakeResponse(headers={}, status_code=302)})
    downloader = make_downloader(script, tmp_path, session)

    result = downloader.localize(URL)

    assert result == URL
    assert downloader.failed == 1
    assert "Location" in capsys.readouterr().err


def test_success_log_masks_query_secrets(script, tmp_path, capsys):
    secret_url = "http://example.com/pic.png?token=secretvalue"
    session = FakeSession({secret_url: FakeResponse()})
    downloader = make_downloader(script, tmp_path, session)

    result = downloader.localize(secret_url)

    captured = capsys.readouterr()
    assert result.startswith("media/")
    assert "token=***" in captured.out
    assert "secretvalue" not in captured.out
    assert "secretvalue" not in captured.err


def test_error_log_masks_url_from_exception(script, tmp_path, capsys):
    secret_url = "http://example.com/pic.png?token=secretvalue"
    session = FakeSession(
        {secret_url: requests.ConnectionError(f"failed for {secret_url}")}
    )
    downloader = make_downloader(script, tmp_path, session)

    downloader.localize(secret_url)

    captured = capsys.readouterr()
    assert "token=***" in captured.err
    assert "secretvalue" not in captured.out
    assert "secretvalue" not in captured.err
