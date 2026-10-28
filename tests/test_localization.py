from __future__ import annotations

import sys
from string import Formatter

import pytest

from helpers import URL


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("ru", "ru"),
        ("RU", "ru"),
        ("ru_RU.UTF-8", "ru"),
        ("ru-RU", "ru"),
        ("Russian_Russia", "ru"),
        ("en", "en"),
        ("en_US.UTF-8", "en"),
        ("English_United States", "en"),
        ("ru:en", "ru"),
        ("", None),
        ("C", None),
        ("POSIX", None),
        ("fr_FR.UTF-8", None),
        (None, None),
    ],
)
def test_normalize_language(script, value, expected):
    assert script.normalize_language(value) == expected


def test_detect_language_reads_locale_environment(script):
    assert script.detect_language(env={"LANG": "ru_RU.UTF-8"}) == "ru"
    assert script.detect_language(env={"LANG": "en_US.UTF-8"}) == "en"


def test_detect_language_respects_environment_priority(script):
    assert (
        script.detect_language(env={"LC_ALL": "ru_RU.UTF-8", "LANG": "en_US.UTF-8"})
        == "ru"
    )
    assert (
        script.detect_language(
            env={"MD_IMG_LOCAL_LANG": "ru", "LANG": "en_US.UTF-8"}
        )
        == "ru"
    )


def test_detect_language_ignores_invalid_custom_value(script):
    assert (
        script.detect_language(
            env={"MD_IMG_LOCAL_LANG": "de", "LANG": "ru_RU.UTF-8"}
        )
        == "ru"
    )


def test_detect_language_falls_back_to_english_for_unknown_locale(script):
    assert script.detect_language(env={"LANG": "fr_FR.UTF-8"}) == "en"
    assert script.detect_language(env={"LANG": "C"}) == "en"


def test_detect_language_override_wins(script):
    assert script.detect_language("ru", env={"LANG": "en_US.UTF-8"}) == "ru"
    assert script.detect_language("en", env={"LANG": "ru_RU.UTF-8"}) == "en"


def test_detect_language_uses_os_locale(script, monkeypatch):
    monkeypatch.setattr(script.locale, "getlocale", lambda: ("ru_RU", "UTF-8"))
    assert script.detect_language(env={}) == "ru"

    monkeypatch.setattr(script.locale, "getlocale", lambda: (None, None))
    monkeypatch.setattr(script, "_windows_ui_language", lambda: "ru")
    assert script.detect_language(env={}) == "ru"

    monkeypatch.setattr(script, "_windows_ui_language", lambda: None)
    assert script.detect_language(env={}) == "en"


def test_detect_language_survives_broken_locale(script, monkeypatch):
    def broken_getlocale():
        raise ValueError("unknown locale")

    monkeypatch.setattr(script.locale, "getlocale", broken_getlocale)
    monkeypatch.setattr(script, "_windows_ui_language", lambda: "ru")
    assert script.detect_language(env={}) == "ru"


@pytest.mark.parametrize(
    ("language_id", "expected"),
    [
        (0x19, "ru"),
        (0x0419, "ru"),
        (0x09, "en"),
        (0x0409, "en"),
        (0x07, None),
        (0x041F, None),
    ],
)
def test_language_from_language_id(script, language_id, expected):
    assert script._language_from_language_id(language_id) == expected


@pytest.mark.skipif(sys.platform != "win32", reason="Windows only")
def test_windows_ui_language_returns_supported_code(script):
    assert script._windows_ui_language() in (None, "ru", "en")


def test_catalogs_have_same_keys(script):
    assert set(script.MESSAGES["en"]) == set(script.MESSAGES["ru"])


def test_catalog_placeholders_match(script):
    formatter = Formatter()

    def fields(template: str) -> set[str]:
        return {name for _, name, _, _ in formatter.parse(template) if name}

    for key, english in script.MESSAGES["en"].items():
        russian = script.MESSAGES["ru"][key]
        assert fields(english) == fields(russian), key


def test_english_catalog_has_no_cyrillic(script):
    for key, template in script.MESSAGES["en"].items():
        assert not any("а" <= char.lower() <= "я" or char == "ё" for char in template), key


def test_all_languages_cover_required_messages(script):
    required = {
        "description",
        "help_markdown",
        "help_media",
        "help_no_backup",
        "help_proxy",
        "help_lang",
        "help_version",
        "help_flag",
        "usage_prefix",
        "positional_title",
        "options_title",
        "error_prefix",
        "file_not_found",
        "proxy_spaces",
        "proxy_unsupported",
        "proxy_invalid",
        "proxy_no_host",
        "proxy_no_port",
        "proxy_only_scheme_host_port",
        "socks_missing",
        "proxy_banner",
        "backup",
        "downloaded_file",
        "download_failed",
        "save_failed",
        "proxy_hint",
        "result",
        "found",
        "downloaded",
        "failed",
    }
    for language in script.LANGUAGES:
        assert required <= set(script.MESSAGES[language]), language


def test_tr_falls_back_to_english(script, monkeypatch):
    monkeypatch.delitem(script.MESSAGES["ru"], "result")
    script.set_language("ru")

    assert script.tr("result", path="note.md") == "\nResult: note.md"


def test_tr_returns_key_for_unknown_message(script):
    assert script.tr("no_such_key") == "no_such_key"


def test_set_language_rejects_unknown(script):
    with pytest.raises(ValueError, match="unsupported language"):
        script.set_language("de")


@pytest.mark.parametrize(
    ("argv", "expected"),
    [
        (["--lang", "ru"], "ru"),
        (["--lang=ru", "note.md"], "ru"),
        (["note.md", "--lang=en"], "en"),
        (["note.md"], None),
        (["--lang"], None),
        (["--", "--lang", "ru"], None),
        (["-h"], None),
    ],
)
def test_language_from_argv(script, argv, expected):
    assert script.language_from_argv(argv) == expected


def test_report_in_english(script, run_main, tmp_path, fake_session, capsys):
    path = tmp_path / "note.md"
    path.write_text(f"![a]({URL})\n", encoding="utf-8")

    run_main(path)

    output = capsys.readouterr().out
    assert "Result: " in output
    assert "Unique images found: 1" in output
    assert "Downloaded: 1" in output
    assert "Errors: 0" in output


def test_report_in_russian(script, run_main, tmp_path, fake_session, capsys, monkeypatch):
    monkeypatch.setenv("MD_IMG_LOCAL_LANG", "ru")
    path = tmp_path / "note.md"
    path.write_text(f"![a]({URL})\n", encoding="utf-8")

    run_main(path)

    output = capsys.readouterr().out
    assert "Результат: " in output
    assert "Найдено уникальных изображений: 1" in output
    assert "Скачано: 1" in output
    assert "Ошибок: 0" in output
    assert "Downloaded:" not in output


def test_lang_argument_switches_report_language(
    script, run_main, tmp_path, fake_session, capsys
):
    path = tmp_path / "note.md"
    path.write_text(f"![a]({URL})\n", encoding="utf-8")

    run_main(path, "--lang=ru")

    output = capsys.readouterr().out
    assert "Скачано: 1" in output
    assert "Downloaded:" not in output


def test_proxy_error_is_localized(
    script, run_main, tmp_path, fake_session, capsys, monkeypatch
):
    monkeypatch.setenv("MD_IMG_LOCAL_LANG", "ru")
    path = tmp_path / "note.md"
    path.write_text(f"![a]({URL})\n", encoding="utf-8")

    with pytest.raises(SystemExit) as error:
        run_main(path, "--proxy=ftp://127.0.0.1:1080")

    stderr = capsys.readouterr().err
    assert error.value.code == 2
    assert "ошибка:" in stderr
    assert "неподдерживаемый" in stderr


def test_help_is_localized_in_process(
    script, run_main, capsys, monkeypatch
):
    monkeypatch.setenv("MD_IMG_LOCAL_LANG", "ru")

    with pytest.raises(SystemExit) as error:
        run_main("--help")

    output = capsys.readouterr().out
    assert error.value.code == 0
    assert "использование:" in output
    assert "позиционные аргументы:" in output
    assert "параметры:" in output
