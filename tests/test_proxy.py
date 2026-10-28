from __future__ import annotations

import sys

import pytest


@pytest.mark.parametrize("raw", [None, "", "   ", "\t\n"])
def test_parse_proxy_empty_means_no_proxy(script, raw):
    assert script.parse_proxy(raw) is None


def test_parse_proxy_accepts_socks5(script):
    assert script.parse_proxy("socks5://127.0.0.1:3066") == "socks5://127.0.0.1:3066"


def test_parse_proxy_normalizes_scheme(script):
    assert script.parse_proxy("SOCKS5H://127.0.0.1:3066") == "socks5h://127.0.0.1:3066"


def test_parse_proxy_drops_trailing_slash(script):
    assert script.parse_proxy("http://proxy.example:3128/") == (
        "http://proxy.example:3128"
    )


def test_parse_proxy_keeps_credentials(script):
    assert script.parse_proxy("socks5://user:pass@127.0.0.1:1080") == (
        "socks5://user:pass@127.0.0.1:1080"
    )


def test_parse_proxy_accepts_ipv6(script):
    assert script.parse_proxy("socks5://[::1]:1080") == "socks5://[::1]:1080"


@pytest.mark.parametrize(
    ("raw", "message"),
    [
        ("socks5://127.0.0.1", "port"),
        ("socks5://:1080", "host"),
        ("socks5://127.0.0.1:99999", "invalid"),
        ("ftp://127.0.0.1:1080", "unsupported"),
        ("127.0.0.1:3066", "scheme"),
        ("localhost:3066", "scheme"),
        ("socks5://127.0.0.1:1080/path", "only contain"),
        ("socks5://127.0.0.1:1080?x=1", "only contain"),
        ("socks5://127.0.0.1:1080#frag", "only contain"),
        ("socks5://127.0.0.1:1080 x", "spaces"),
    ],
)
def test_parse_proxy_rejects_invalid(script, raw, message):
    with pytest.raises(script.ProxyConfigError, match=message):
        script.parse_proxy(raw)


def test_mask_proxy_without_credentials(script):
    assert script.mask_proxy("socks5://127.0.0.1:3066") == "socks5://127.0.0.1:3066"


def test_mask_proxy_hides_password(script):
    assert script.mask_proxy("socks5://user:secret@127.0.0.1:1080") == (
        "socks5://user:***@127.0.0.1:1080"
    )


def test_mask_proxy_hides_password_without_username(script):
    assert script.mask_proxy("socks5://:secret@127.0.0.1:1080") == (
        "socks5://:***@127.0.0.1:1080"
    )


def test_mask_proxy_keeps_ipv6_brackets(script):
    assert script.mask_proxy("socks5://u:p@[::1]:1080") == "socks5://u:***@[::1]:1080"


def test_mask_proxy_keeps_username_without_password(script):
    assert script.mask_proxy("socks5://user@127.0.0.1:1080") == (
        "socks5://user@127.0.0.1:1080"
    )


def test_ensure_socks_support_ignores_http(script):
    script.ensure_socks_support("http://127.0.0.1:3128")


def test_ensure_socks_support_requires_pysocks(script, monkeypatch):
    monkeypatch.setitem(sys.modules, "socks", None)
    with pytest.raises(script.ProxyConfigError, match="PySocks"):
        script.ensure_socks_support("socks5://127.0.0.1:3066")


def test_ensure_socks_support_passes_when_pysocks_installed(script):
    pytest.importorskip("socks")
    script.ensure_socks_support("socks5://127.0.0.1:3066")


def test_build_session_without_proxy(script):
    session = script.build_session(None)
    try:
        assert session.proxies == {}
        assert session.trust_env is True
        assert "Mozilla" in session.headers["User-Agent"]
    finally:
        session.close()


def test_build_session_with_proxy(script):
    proxy = "socks5://127.0.0.1:3066"
    session = script.build_session(proxy)
    try:
        assert session.proxies == {"http": proxy, "https": proxy}
        # Явный прокси не должен перебиваться HTTP_PROXY/HTTPS_PROXY/NO_PROXY.
        assert session.trust_env is False
    finally:
        session.close()
