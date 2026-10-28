from __future__ import annotations

from pathlib import Path

import pytest
import requests

from helpers import URL, FakeResponse


def write_md(tmp_path: Path, text: str, name: str = "note.md") -> Path:
    path = tmp_path / name
    path.write_text(text, encoding="utf-8")
    return path


def local_name(script, url: str = URL, extension: str = ".png") -> str:
    return f"media/{script.filename_for_url(url, extension)}"


def test_inline_html_and_dedupe(script, run_main, tmp_path, fake_session):
    path = write_md(
        tmp_path,
        f'![alt]({URL} "title")\n'
        f"![other]({URL})\n"
        f'<img src=\'{URL}\' alt="x">\n'
        f"![angle](<{URL}> \"t2\")\n",
    )
    expected = local_name(script)

    run_main(path)

    text = path.read_text(encoding="utf-8")
    assert f'![alt]({expected} "title")' in text
    assert f"![other]({expected})" in text
    assert f'<img src=\'{expected}\' alt="x">' in text
    assert f'![angle]({expected} "t2")' in text
    assert len(fake_session.calls) == 1
    assert fake_session.closed is True


def test_reference_style_is_inlined(script, run_main, tmp_path, fake_session):
    path = write_md(
        tmp_path,
        f"![a][pic]\n\n[pic]: {URL}\n[unused]: http://example.com/other.png\n",
    )
    expected = local_name(script)

    run_main(path)

    text = path.read_text(encoding="utf-8")
    assert f"![a]({expected})" in text
    assert "[pic]:" not in text
    assert "[unused]: http://example.com/other.png" in text
    assert len(fake_session.calls) == 1
    assert fake_session.calls[0][0] == URL


def test_reference_definition_kept_if_still_used(script, run_main, tmp_path, fake_session):
    path = write_md(
        tmp_path,
        f"![a][pic]\n\nСм. [pic].\n\n[pic]: {URL}\n",
    )

    run_main(path)

    text = path.read_text(encoding="utf-8")
    # Картинка заменена на inline, но определение остаётся, так как на него есть ссылка.
    assert f"![a]({local_name(script)})" in text
    assert f"[pic]: {URL}" in text


def test_local_links_untouched(script, run_main, tmp_path, fake_session):
    baseline = (
        "![a](media/local.png)\n"
        "![b](./pic.png)\n"
        "![c](ftp://example.com/img.png)\n"
        '<img src="media/local.png">\n'
    )
    path = write_md(tmp_path, baseline)
    fake_session.responses[URL] = FakeResponse()

    run_main(path)

    assert path.read_text(encoding="utf-8") == baseline
    assert fake_session.calls == []


def test_html_with_local_src_untouched(script, run_main, tmp_path, fake_session):
    baseline = '<img src="./local.png" alt="x">\n'
    path = write_md(tmp_path, baseline)

    run_main(path)

    assert path.read_text(encoding="utf-8") == baseline
    assert fake_session.calls == []


def test_html_failed_download_keeps_tag(
    script, run_main, tmp_path, fake_session, capsys
):
    fake_session.responses[URL] = requests.ConnectionError("boom")
    baseline = f'<img src="{URL}" alt="x">\n'
    path = write_md(tmp_path, baseline)

    run_main(path)

    assert path.read_text(encoding="utf-8") == baseline
    assert "Errors: 1" in capsys.readouterr().out


def test_reference_with_local_url_untouched(script, run_main, tmp_path, fake_session):
    baseline = "![a][local]\n\n[local]: media/local.png\n"
    path = write_md(tmp_path, baseline)

    run_main(path)

    assert path.read_text(encoding="utf-8") == baseline
    assert fake_session.calls == []


def test_reference_failed_download_keeps_link(
    script, run_main, tmp_path, fake_session, capsys
):
    fake_session.responses[URL] = requests.ConnectionError("boom")
    baseline = f"![a][pic]\n\n[pic]: {URL}\n"
    path = write_md(tmp_path, baseline)

    run_main(path)

    text = path.read_text(encoding="utf-8")
    assert "![a][pic]" in text
    assert f"[pic]: {URL}" in text
    assert "Errors: 1" in capsys.readouterr().out


def test_failed_download_keeps_link_and_counts_error(
    script, run_main, tmp_path, fake_session, capsys
):
    fake_session.responses[URL] = requests.ConnectionError("boom")
    path = write_md(tmp_path, f"![a]({URL})\n")

    run_main(path)

    text = path.read_text(encoding="utf-8")
    output = capsys.readouterr().out
    assert text == f"![a]({URL})\n"
    assert "Errors: 1" in output
    assert "[ERROR]" in output


def test_backup_created_by_default(script, run_main, tmp_path, fake_session):
    original = f"![a]({URL})\n"
    path = write_md(tmp_path, original)

    run_main(path)

    backup = path.with_name(f"{path.name}.orig")
    assert backup.read_text(encoding="utf-8") == original
    assert path.read_text(encoding="utf-8") != original


def test_no_backup_flag(script, run_main, tmp_path, fake_session):
    path = write_md(tmp_path, f"![a]({URL})\n")

    run_main(path, "--no-backup")

    assert not path.with_name(f"{path.name}.orig").exists()
    assert local_name(script) in path.read_text(encoding="utf-8")


def test_custom_media_dir(script, run_main, tmp_path, fake_session):
    notes = tmp_path / "notes"
    notes.mkdir()
    path = write_md(notes, f"![a]({URL})\n")
    media = tmp_path / "assets"

    run_main(path, f"--media={media}")

    name = script.filename_for_url(URL, ".png")
    assert (media / name).is_file()
    assert f"![a](../assets/{name})" in path.read_text(encoding="utf-8")


def test_missing_markdown_file(script, run_main, tmp_path, fake_session, capsys):
    with pytest.raises(SystemExit) as error:
        run_main(tmp_path / "nope.md")

    assert error.value.code == 2
    assert "file not found" in capsys.readouterr().err


def test_invalid_proxy_fails_before_any_work(
    script, run_main, tmp_path, fake_session, capsys
):
    original = f"![a]({URL})\n"
    path = write_md(tmp_path, original)

    with pytest.raises(SystemExit) as error:
        run_main(path, "--proxy=ftp://127.0.0.1:1080")

    assert error.value.code == 2
    assert "unsupported" in capsys.readouterr().err
    assert path.read_text(encoding="utf-8") == original
    assert not path.with_name(f"{path.name}.orig").exists()
    assert fake_session.proxies == []


def test_proxy_is_passed_to_session_and_masked(script, run_main, tmp_path, fake_session, capsys):
    path = write_md(tmp_path, f"![a]({URL})\n")

    run_main(path, "--proxy=socks5://user:secret@127.0.0.1:3066")

    output = capsys.readouterr().out
    assert fake_session.proxies == ["socks5://user:secret@127.0.0.1:3066"]
    assert "[PROXY] socks5://user:***@127.0.0.1:3066" in output
    assert "secret" not in output


def test_blank_proxy_means_no_proxy(script, run_main, tmp_path, fake_session, capsys):
    path = write_md(tmp_path, f"![a]({URL})\n")

    run_main(path, "--proxy=   ")

    output = capsys.readouterr().out
    assert fake_session.proxies == [None]
    assert "[PROXY]" not in output


def test_report_counts(script, run_main, tmp_path, fake_session, capsys):
    other = "http://example.com/second.png"
    fake_session.responses[other] = FakeResponse()
    path = write_md(tmp_path, f"![a]({URL})\n![b]({other})\n![c]({URL})\n")

    run_main(path)

    output = capsys.readouterr().out
    assert "Unique images found: 2" in output
    assert "Downloaded: 2" in output
    assert "Errors: 0" in output
