from __future__ import annotations

import codecs
from pathlib import Path

import pytest
import requests

from helpers import URL


def write_md(tmp_path: Path, text: str) -> Path:
    path = tmp_path / "note.md"
    path.write_text(text, encoding="utf-8")
    return path


def test_fenced_code_is_not_rewritten(run_main, tmp_path, fake_session):
    source = f"```\n![a]({URL})\n```\n"
    path = write_md(tmp_path, source)

    run_main(path)

    assert path.read_text(encoding="utf-8") == source


def test_fenced_code_with_info_string_is_not_rewritten(
    run_main, tmp_path, fake_session
):
    source = f"```markdown\n![a]({URL})\n```\n"
    path = write_md(tmp_path, source)

    run_main(path)

    assert path.read_text(encoding="utf-8") == source


def test_tilde_fence_is_not_rewritten(run_main, tmp_path, fake_session):
    source = f"~~~\n![a]({URL})\n~~~\n"
    path = write_md(tmp_path, source)

    run_main(path)

    assert path.read_text(encoding="utf-8") == source


def test_unclosed_fence_is_not_rewritten(run_main, tmp_path, fake_session):
    source = f"```\n![a]({URL})\n"
    path = write_md(tmp_path, source)

    run_main(path)

    assert path.read_text(encoding="utf-8") == source


def test_inline_code_is_not_rewritten(run_main, tmp_path, fake_session):
    source = f"`![a]({URL})`\n"
    path = write_md(tmp_path, source)

    run_main(path)

    assert path.read_text(encoding="utf-8") == source


def test_double_backtick_inline_code_is_not_rewritten(
    run_main, tmp_path, fake_session
):
    source = f"``![a]({URL})``\n"
    path = write_md(tmp_path, source)

    run_main(path)

    assert path.read_text(encoding="utf-8") == source


def test_html_comment_is_not_rewritten(run_main, tmp_path, fake_session):
    source = f'<!-- <img src="{URL}" alt="x"> -->\n'
    path = write_md(tmp_path, source)

    run_main(path)

    assert path.read_text(encoding="utf-8") == source


def test_nested_inline_code_and_html_comment_is_untouched(
    run_main, tmp_path, fake_session
):
    source = f'`<!-- <img src="{URL}" alt="x"> -->`\n'
    path = write_md(tmp_path, source)

    run_main(path)

    assert path.read_text(encoding="utf-8") == source


def test_escaped_image_syntax_is_not_rewritten(run_main, tmp_path, fake_session):
    source = f"\\![a]({URL})\n"
    path = write_md(tmp_path, source)

    run_main(path)

    assert path.read_text(encoding="utf-8") == source


def test_reference_definition_inside_fence_is_untouched(
    run_main, tmp_path, fake_session
):
    source = f"```\n[pic]: {URL}\n```\n\n![a][pic]\n"
    path = write_md(tmp_path, source)

    run_main(path)

    assert path.read_text(encoding="utf-8") == source
    assert fake_session.calls == []


def test_reference_definition_after_fence_is_still_resolved(
    run_main, tmp_path, fake_session
):
    source = f"```\ncode\n```\n[pic]: {URL}\n\n![a][pic]\n"
    path = write_md(tmp_path, source)

    run_main(path)

    text = path.read_text(encoding="utf-8")
    assert "```\ncode\n```\n" in text
    assert "![a](media/" in text
    assert "[pic]:" not in text
    assert len(fake_session.calls) == 1


def test_text_outside_fence_is_still_rewritten(
    run_main, tmp_path, fake_session
):
    source = f"```\n![a]({URL})\n```\n\n![b]({URL})\n"
    path = write_md(tmp_path, source)

    run_main(path)

    text = path.read_text(encoding="utf-8")
    assert f"```\n![a]({URL})\n```\n" in text
    assert "![b](media/" in text
    assert len(fake_session.calls) == 1


@pytest.mark.xfail(
    strict=True,
    reason="indented code blocks require a real Markdown parser",
)
def test_indented_code_is_not_rewritten(run_main, tmp_path, fake_session):
    source = f"    ![a]({URL})\n"
    path = write_md(tmp_path, source)

    run_main(path)

    assert path.read_text(encoding="utf-8") == source


def test_fence_inside_blockquote_is_not_rewritten(
    run_main, tmp_path, fake_session
):
    source = f"> ```\n> ![a]({URL})\n> ```\n"
    path = write_md(tmp_path, source)

    run_main(path)

    assert path.read_text(encoding="utf-8") == source


def test_markdown_path_with_spaces_is_escaped(run_main, tmp_path, fake_session):
    media = tmp_path / "my images"
    path = write_md(tmp_path, f"![a]({URL})\n")

    run_main(path, f"--media={media}")

    text = path.read_text(encoding="utf-8")
    assert "](my images/" not in text
    assert "](my%20images/" in text


def test_html_src_with_spaces_is_escaped(run_main, tmp_path, fake_session):
    media = tmp_path / "my images"
    path = write_md(tmp_path, f'<img src="{URL}" alt="x">\n')

    run_main(path, f"--media={media}")

    text = path.read_text(encoding="utf-8")
    assert 'src="my images/' not in text
    assert 'src="my%20images/' in text


def test_reference_path_with_spaces_is_escaped(run_main, tmp_path, fake_session):
    media = tmp_path / "my images"
    path = write_md(tmp_path, f"![a][pic]\n\n[pic]: {URL}\n")

    run_main(path, f"--media={media}")

    text = path.read_text(encoding="utf-8")
    assert "![a](my%20images/" in text
    assert "[pic]:" not in text


def test_relative_path_for_markdown_escapes_special_characters(script, tmp_path):
    destination = tmp_path / "my images (1)" / "a#b.png"

    result = script.relative_path_for_markdown(destination, tmp_path)

    assert result == "my%20images%20%281%29/a%23b.png"


def test_lf_line_endings_are_preserved(run_main, tmp_path, fake_session):
    source = f"![a]({URL})\n\nтекст\n"
    path = tmp_path / "note.md"
    path.write_bytes(source.encode("utf-8"))

    run_main(path)

    data = path.read_bytes()
    assert b"\r" not in data
    assert data.endswith(b"\n")
    assert b"media/" in data


def test_crlf_line_endings_are_preserved(run_main, tmp_path, fake_session):
    source = f"![a]({URL})\r\n\r\nтекст\r\n"
    path = tmp_path / "note.md"
    path.write_bytes(source.encode("utf-8"))

    run_main(path)

    data = path.read_bytes()
    assert b"\r\n\r\n" in data
    assert b"\n" not in data.replace(b"\r\n", b"")
    assert b"media/" in data


def test_missing_final_newline_is_preserved(run_main, tmp_path, fake_session):
    path = tmp_path / "note.md"
    path.write_bytes(f"![a]({URL})".encode())

    run_main(path)

    data = path.read_bytes()
    assert b"media/" in data
    assert not data.endswith(b"\n")


def test_utf8_bom_is_preserved(run_main, tmp_path, fake_session):
    source = f"![a]({URL})\n"
    path = tmp_path / "note.md"
    path.write_bytes(codecs.BOM_UTF8 + source.encode("utf-8"))

    run_main(path)

    data = path.read_bytes()
    assert data.startswith(codecs.BOM_UTF8)
    assert b"media/" in data[len(codecs.BOM_UTF8):]


@pytest.mark.parametrize("encoding", ["utf-16-le", "utf-16-be"])
def test_utf16_file_is_rewritten_in_same_encoding(
    run_main, tmp_path, fake_session, encoding
):
    bom = (
        codecs.BOM_UTF16_LE
        if encoding == "utf-16-le"
        else codecs.BOM_UTF16_BE
    )
    source = f"![a]({URL})\n\nпривет\n"
    path = tmp_path / "note.md"
    path.write_bytes(bom + source.encode(encoding))

    run_main(path)

    data = path.read_bytes()
    assert data.startswith(bom)
    text = data[len(bom):].decode(encoding)
    assert "media/" in text
    assert "привет" in text
    assert "\n\n" in text


@pytest.mark.parametrize("encoding", ["utf-32-le", "utf-32-be"])
def test_utf32_file_is_rewritten_in_same_encoding(
    run_main, tmp_path, fake_session, encoding
):
    bom = (
        codecs.BOM_UTF32_LE
        if encoding == "utf-32-le"
        else codecs.BOM_UTF32_BE
    )
    source = f"![a]({URL})\n\nпривет\n"
    path = tmp_path / "note.md"
    path.write_bytes(bom + source.encode(encoding))

    run_main(path)

    data = path.read_bytes()
    assert data.startswith(bom)
    text = data[len(bom):].decode(encoding)
    assert "media/" in text
    assert "привет" in text


@pytest.mark.parametrize(
    ("encoding", "bom"),
    [
        ("utf-8", b""),
        ("utf-8", codecs.BOM_UTF8),
        ("utf-16-le", codecs.BOM_UTF16_LE),
        ("utf-16-be", codecs.BOM_UTF16_BE),
        ("utf-32-le", codecs.BOM_UTF32_LE),
        ("utf-32-be", codecs.BOM_UTF32_BE),
    ],
)
def test_decode_encode_markdown_round_trip(script, encoding, bom):
    text = "строка с картинкой\nвторая строка"
    data = bom + text.encode(encoding)

    decoded, actual_encoding, actual_bom = script.decode_markdown(data)

    assert decoded == text
    assert actual_encoding == encoding
    assert actual_bom == bom
    assert script.encode_markdown(decoded, actual_encoding, actual_bom) == data


def test_cp1251_file_reports_clean_error(run_main, tmp_path, capsys):
    path = tmp_path / "note.md"
    path.write_bytes("привет".encode("cp1251"))

    with pytest.raises(SystemExit) as error:
        run_main(path)

    assert error.value.code == 2
    assert "Traceback" not in capsys.readouterr().err
    assert not (tmp_path / "note.md.orig").exists()


def test_exit_code_is_zero_on_success(run_main, tmp_path, fake_session):
    path = write_md(tmp_path, f"![a]({URL})\n")

    assert run_main(path) == 0


def test_exit_code_is_nonzero_when_downloads_fail(
    run_main, tmp_path, fake_session
):
    fake_session.responses[URL] = requests.ConnectionError("boom")
    path = write_md(tmp_path, f"![a]({URL})\n")

    assert run_main(path) == 1


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


def test_proxy_password_not_leaked_on_invalid_scheme(
    run_main, tmp_path, capsys
):
    path = write_md(tmp_path, f"![a]({URL})\n")

    with pytest.raises(SystemExit) as error:
        run_main(path, "--proxy=ftp://user:secret@127.0.0.1:3128")

    assert error.value.code == 2
    assert "secret" not in capsys.readouterr().err
