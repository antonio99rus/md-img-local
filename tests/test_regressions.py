from __future__ import annotations

from pathlib import Path

import pytest
import requests

from helpers import URL


def write_md(tmp_path: Path, text: str) -> Path:
    path = tmp_path / "note.md"
    path.write_text(text, encoding="utf-8")
    return path


@pytest.mark.xfail(strict=True, reason="regex rewrites fenced code blocks")
def test_fenced_code_is_not_rewritten(run_main, tmp_path, fake_session):
    source = f"```\n![a]({URL})\n```\n"
    path = write_md(tmp_path, source)

    run_main(path)

    assert path.read_text(encoding="utf-8") == source


@pytest.mark.xfail(strict=True, reason="regex rewrites inline code")
def test_inline_code_is_not_rewritten(run_main, tmp_path, fake_session):
    source = f"`![a]({URL})`\n"
    path = write_md(tmp_path, source)

    run_main(path)

    assert path.read_text(encoding="utf-8") == source


@pytest.mark.xfail(strict=True, reason="regex rewrites HTML comments")
def test_html_comment_is_not_rewritten(run_main, tmp_path, fake_session):
    source = f'<!-- <img src="{URL}" alt="x"> -->\n'
    path = write_md(tmp_path, source)

    run_main(path)

    assert path.read_text(encoding="utf-8") == source


@pytest.mark.xfail(strict=True, reason="escaped image syntax is still an image for regex")
def test_escaped_image_syntax_is_not_rewritten(run_main, tmp_path, fake_session):
    source = f"\\![a]({URL})\n"
    path = write_md(tmp_path, source)

    run_main(path)

    assert path.read_text(encoding="utf-8") == source


@pytest.mark.xfail(strict=True, reason="relative path with spaces is not escaped")
def test_markdown_path_with_spaces_is_escaped(run_main, tmp_path, fake_session):
    media = tmp_path / "my images"
    path = write_md(tmp_path, f"![a]({URL})\n")

    run_main(path, f"--media={media}")

    text = path.read_text(encoding="utf-8")
    assert "](my images/" not in text


@pytest.mark.xfail(strict=True, reason="HTML src with spaces is not escaped")
def test_html_src_with_spaces_is_escaped(run_main, tmp_path, fake_session):
    media = tmp_path / "my images"
    path = write_md(tmp_path, f'<img src="{URL}" alt="x">\n')

    run_main(path, f"--media={media}")

    text = path.read_text(encoding="utf-8")
    assert 'src="my images/' not in text


@pytest.mark.xfail(strict=True, reason="cp1251 input raises UnicodeDecodeError")
def test_cp1251_file_reports_clean_error(run_main, tmp_path, capsys):
    path = tmp_path / "note.md"
    path.write_bytes("привет".encode("cp1251"))

    with pytest.raises(SystemExit) as error:
        run_main(path)

    assert error.value.code == 2
    assert "Traceback" not in capsys.readouterr().err


@pytest.mark.xfail(strict=True, reason="failures do not affect the exit code")
def test_exit_code_is_nonzero_when_downloads_fail(
    run_main, tmp_path, fake_session
):
    fake_session.responses[URL] = requests.ConnectionError("boom")
    path = write_md(tmp_path, f"![a]({URL})\n")

    with pytest.raises(SystemExit) as error:
        run_main(path)

    assert error.value.code == 1


@pytest.mark.xfail(strict=True, reason="media path that is a file raises FileExistsError")
def test_media_path_that_is_a_file_reports_clean_error(
    run_main, tmp_path, capsys
):
    path = write_md(tmp_path, f"![a]({URL})\n")
    media = tmp_path / "media"
    media.write_text("not a directory", encoding="utf-8")

    with pytest.raises(SystemExit) as error:
        run_main(path, f"--media={media}")

    assert error.value.code == 2
    assert "media" in capsys.readouterr().err.lower()


@pytest.mark.xfail(strict=True, reason="unsupported proxy error prints raw credentials")
def test_proxy_password_not_leaked_on_invalid_scheme(
    run_main, tmp_path, capsys
):
    path = write_md(tmp_path, f"![a]({URL})\n")

    with pytest.raises(SystemExit) as error:
        run_main(path, "--proxy=ftp://user:secret@127.0.0.1:3128")

    assert error.value.code == 2
    assert "secret" not in capsys.readouterr().err
