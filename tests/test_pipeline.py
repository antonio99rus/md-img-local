from __future__ import annotations

import dataclasses
from pathlib import Path

import pytest
import requests

from helpers import URL, FakeResponse, FakeSession


def make_downloader(script, tmp_path: Path, session: FakeSession):
    return script.Downloader(tmp_path / "media", tmp_path, session)


def test_rewrite_returns_text_and_canonical_urls(script, tmp_path):
    session = FakeSession({URL: FakeResponse()})
    downloader = make_downloader(script, tmp_path, session)

    result = script.rewrite(
        f"![a]({URL})\n![b]({URL}#fragment)\n", downloader
    )

    assert result.found_urls == frozenset({URL})
    assert "media/" in result.text
    assert result.text.count("media/") == 2
    assert downloader.downloaded == 1


def test_rewrite_keeps_failed_links(script, tmp_path):
    original = f"![a]({URL})\n"
    session = FakeSession({URL: requests.ConnectionError("boom")})
    downloader = make_downloader(script, tmp_path, session)

    result = script.rewrite(original, downloader)

    assert result.text == original
    assert result.found_urls == frozenset({URL})
    assert downloader.failed == 1


def test_rewrite_does_not_touch_fenced_code(script, tmp_path):
    original = f"```\n![a]({URL})\n```\n"
    session = FakeSession({URL: FakeResponse()})
    downloader = make_downloader(script, tmp_path, session)

    result = script.rewrite(original, downloader)

    assert result.text == original
    assert result.found_urls == frozenset()
    assert session.calls == []


def test_rewrite_result_is_frozen(script):
    result = script.RewriteResult(text="x", found_urls=frozenset())

    with pytest.raises(dataclasses.FrozenInstanceError):
        result.text = "y"


def test_run_report_exit_code(script):
    failed = script.RunReport(
        path=Path("note.md"), found=1, downloaded=0, failed=1
    )
    ok = script.RunReport(
        path=Path("note.md"), found=1, downloaded=1, failed=0
    )

    assert failed.exit_code == 1
    assert ok.exit_code == 0


def test_report_result_prints_summary(script, capsys):
    script.report_result(
        script.RunReport(
            path=Path("note.md"), found=3, downloaded=2, failed=1
        )
    )

    output = capsys.readouterr().out
    assert "Result: note.md" in output
    assert "Unique images found: 3" in output
    assert "Downloaded: 2" in output
    assert "Errors: 1" in output


def test_parser_options_match_language_prescan(script):
    parser = script.build_parser()
    options = {
        option
        for action in parser._actions
        for option in action.option_strings
        if option.startswith("--")
    }

    assert options == set(script.LONG_OPTIONS)
