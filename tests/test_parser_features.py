from __future__ import annotations

from pathlib import Path

from helpers import URL, FakeResponse


def write_md(tmp_path: Path, text: str) -> Path:
    path = tmp_path / "note.md"
    path.write_text(text, encoding="utf-8")
    return path


def local_name(script, url: str = URL, extension: str = ".png") -> str:
    return f"media/{script.filename_for_url(url, extension)}"


def respond(fake_session, *urls: str) -> None:
    for url in urls:
        fake_session.responses[url] = FakeResponse()


def test_protocol_relative_inline_url_uses_https(
    script, run_main, tmp_path, fake_session
):
    remote = "https://example.com/rel.png"
    respond(fake_session, remote)
    path = write_md(tmp_path, "![a](//example.com/rel.png)\n")

    run_main(path)

    assert f"![a]({local_name(script, remote)})" in path.read_text(encoding="utf-8")
    assert fake_session.calls[0][0] == remote


def test_protocol_relative_html_src_uses_https(
    script, run_main, tmp_path, fake_session
):
    remote = "https://example.com/rel.png"
    respond(fake_session, remote)
    path = write_md(tmp_path, '<img src="//example.com/rel.png" alt="x">\n')

    run_main(path)

    assert (
        f'<img src="{local_name(script, remote)}" alt="x">'
        in path.read_text(encoding="utf-8")
    )


def test_html_src_without_quotes_is_rewritten(
    script, run_main, tmp_path, fake_session
):
    path = write_md(tmp_path, f"<img src={URL} alt=x>\n")

    run_main(path)

    expected = f"<img src={local_name(script)} alt=x>"
    assert expected in path.read_text(encoding="utf-8")


def test_html_srcset_candidates_are_rewritten(
    script, run_main, tmp_path, fake_session, capsys
):
    first = "http://example.com/a.png"
    second = "http://example.com/b.png"
    respond(fake_session, first, second)
    path = write_md(
        tmp_path,
        f'<img srcset="{first} 1x, {second} 2x" alt="x">\n',
    )

    run_main(path)

    expected = (
        f'<img srcset="{local_name(script, first)} 1x, '
        f'{local_name(script, second)} 2x" alt="x">'
    )
    assert expected in path.read_text(encoding="utf-8")
    assert len(fake_session.calls) == 2
    assert "Unique images found: 2" in capsys.readouterr().out


def test_source_srcset_is_rewritten(
    script, run_main, tmp_path, fake_session
):
    remote = "http://example.com/source.png"
    respond(fake_session, remote)
    path = write_md(tmp_path, f"<source srcset='{remote} 480w'>\n")

    run_main(path)

    assert (
        f"<source srcset='{local_name(script, remote)} 480w'>"
        in path.read_text(encoding="utf-8")
    )


def test_unquoted_srcset_is_rewritten(
    script, run_main, tmp_path, fake_session
):
    remote = "http://example.com/unquoted.png"
    respond(fake_session, remote)
    path = write_md(tmp_path, f"<img srcset={remote}>\n")

    run_main(path)

    assert (
        f"<img srcset={local_name(script, remote)}>"
        in path.read_text(encoding="utf-8")
    )


def test_srcset_protocol_relative_candidate_uses_https(
    script, run_main, tmp_path, fake_session
):
    remote = "https://example.com/set.png"
    respond(fake_session, remote)
    path = write_md(tmp_path, '<img srcset="//example.com/set.png 1x">\n')

    run_main(path)

    assert (
        f'<img srcset="{local_name(script, remote)} 1x">'
        in path.read_text(encoding="utf-8")
    )


def test_unquoted_src_and_quoted_srcset_are_both_rewritten(
    script, run_main, tmp_path, fake_session
):
    source_url = "http://example.com/source.png"
    set_url = "http://example.com/set.png"
    respond(fake_session, source_url, set_url)
    path = write_md(
        tmp_path,
        f'<img src={source_url} srcset="{set_url} 2x">\n',
    )

    run_main(path)

    expected = (
        f'<img src={local_name(script, source_url)} '
        f'srcset="{local_name(script, set_url)} 2x">'
    )
    assert expected in path.read_text(encoding="utf-8")


def test_local_srcset_is_untouched(script, run_main, tmp_path, fake_session):
    source = '<img srcset="media/a.png 1x, ./b.png 2x">\n'
    path = write_md(tmp_path, source)

    run_main(path)

    assert path.read_text(encoding="utf-8") == source
    assert fake_session.calls == []


def test_srcset_url_with_comma_is_rewritten(
    script, run_main, tmp_path, fake_session
):
    first = "http://example.com/a,b.png"
    second = "http://example.com/c.png"
    respond(fake_session, first, second)
    path = write_md(tmp_path, f'<img srcset="{first} 1x, {second} 2x">\n')

    run_main(path)

    expected = (
        f'<img srcset="{local_name(script, first)} 1x, '
        f'{local_name(script, second)} 2x">'
    )
    assert expected in path.read_text(encoding="utf-8")


def test_srcset_keeps_original_spacing(
    script, run_main, tmp_path, fake_session
):
    first = "http://example.com/one.png"
    second = "http://example.com/two.png"
    respond(fake_session, first, second)
    path = write_md(
        tmp_path,
        f'<img srcset="  {first}   1x ,{second}    2x  ">\n',
    )

    run_main(path)

    expected = (
        f'<img srcset="  {local_name(script, first)}   1x ,'
        f'{local_name(script, second)}    2x  ">'
    )
    assert expected in path.read_text(encoding="utf-8")


def test_srcset_data_url_with_comma_is_untouched(
    script, run_main, tmp_path, fake_session
):
    data_url = "data:image/png;base64,AAAA"
    remote = "http://example.com/b.png"
    respond(fake_session, remote)
    path = write_md(
        tmp_path, f'<img srcset="{data_url} 1x, {remote} 2x">\n'
    )

    run_main(path)

    expected = (
        f'<img srcset="{data_url} 1x, '
        f'{local_name(script, remote)} 2x">'
    )
    assert expected in path.read_text(encoding="utf-8")


def test_source_src_inside_picture_is_rewritten(
    script, run_main, tmp_path, fake_session
):
    remote = "http://example.com/source.png"
    respond(fake_session, remote)
    path = write_md(
        tmp_path,
        f'<picture><source src="{remote}" type="image/png"></picture>\n',
    )

    run_main(path)

    expected = (
        f'<picture><source src="{local_name(script, remote)}" '
        'type="image/png"></picture>'
    )
    assert expected in path.read_text(encoding="utf-8")


def test_source_src_outside_picture_is_untouched(
    script, run_main, tmp_path, fake_session
):
    source = f'<source src="{URL}">\n'
    path = write_md(tmp_path, source)

    run_main(path)

    assert path.read_text(encoding="utf-8") == source
    assert fake_session.calls == []


def test_first_reference_definition_wins(
    script, run_main, tmp_path, fake_session, capsys
):
    first = "http://example.com/first.png"
    second = "http://example.com/second.png"
    respond(fake_session, first)
    path = write_md(
        tmp_path,
        f"![a][pic]\n\n[pic]: {first}\n[pic]: {second}\n",
    )

    run_main(path)

    text = path.read_text(encoding="utf-8")
    assert f"![a]({local_name(script, first)})" in text
    assert second not in [url for url, _ in fake_session.calls]
    assert "[pic]:" not in text
    assert "Errors: 0" in capsys.readouterr().out


def test_reference_title_is_preserved_when_inlined(
    script, run_main, tmp_path, fake_session
):
    path = write_md(tmp_path, f'![a][pic]\n\n[pic]: {URL} "Title"\n')

    run_main(path)

    expected = f'![a]({local_name(script)} "Title")'
    assert expected in path.read_text(encoding="utf-8")


def test_first_reference_title_wins(script, run_main, tmp_path, fake_session):
    first = "http://example.com/first.png"
    second = "http://example.com/second.png"
    respond(fake_session, first)
    path = write_md(
        tmp_path,
        f'![a][pic]\n\n[pic]: {first} "First"\n[pic]: {second} "Second"\n',
    )

    run_main(path)

    text = path.read_text(encoding="utf-8")
    assert f'![a]({local_name(script, first)} "First")' in text
    assert "Second" not in text
