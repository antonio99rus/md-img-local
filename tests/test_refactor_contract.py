"""Регрессии для краевых случаев, затронутых рефакторингом."""

from __future__ import annotations

import requests

from helpers import URL, FakeResponse, FakeSession


def make_downloader(script, tmp_path, session=None, proxy_label=None):
    return script.Downloader(
        tmp_path / "media",
        tmp_path,
        session or FakeSession({URL: FakeResponse()}),
        proxy_label,
    )


def test_all_reference_uses_are_inlined_and_definition_is_removed(
    script, tmp_path
):
    text = f"![a][pic]\n![b][pic]\n\n[pic]: {URL}\n"
    downloader = make_downloader(script, tmp_path)

    result = script.rewrite(text, downloader)

    local = f"media/{script.filename_for_url(URL, '.png')}"
    assert result.text.count(f"![a]({local})") == 1
    assert result.text.count(f"![b]({local})") == 1
    assert "[pic]:" not in result.text
    assert result.found_urls == frozenset({URL})
    assert downloader.downloaded == 1


def test_srcset_keeps_failed_candidate_and_rewrites_the_other(
    script, tmp_path
):
    failed_url = "http://example.com/broken.png"
    session = FakeSession(
        {
            URL: FakeResponse(),
            failed_url: requests.ConnectionError("boom"),
        }
    )
    downloader = make_downloader(script, tmp_path, session)
    text = f'<img srcset="{URL} 1x, {failed_url} 2x">\n'

    result = script.rewrite(text, downloader)

    local = f"media/{script.filename_for_url(URL, '.png')}"
    assert result.text == f'<img srcset="{local} 1x, {failed_url} 2x">\n'
    assert result.found_urls == frozenset({URL, failed_url})
    assert downloader.failed == 1


def test_save_error_does_not_add_proxy_hint(
    script, tmp_path, monkeypatch, capsys
):
    url = URL
    downloader = make_downloader(
        script,
        tmp_path,
        FakeSession({url: FakeResponse()}),
        proxy_label="socks5://127.0.0.1:3066",
    )

    def fail_write(media_dir, destination, data):
        raise OSError("disk full")

    monkeypatch.setattr(script, "store_download", fail_write)

    assert downloader.localize(url) == url
    output = capsys.readouterr().err
    assert "Failed to save" in output
    assert "socks5://127.0.0.1:3066" not in output
