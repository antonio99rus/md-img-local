from __future__ import annotations

import re
from pathlib import Path

from toml_compat import tomllib

ROOT = Path(__file__).resolve().parents[1]
README_RU = ROOT / "README.md"
README_EN = ROOT / "README-EN-US.md"
# Флаги, без которых документация заведомо неполна.
CORE_FLAGS = frozenset({"--media", "--no-backup", "--proxy", "--lang"})
CODE_SPAN_RE = re.compile(r"`([^`\n]+)`")
LONG_FLAG_RE = re.compile(r"--[a-z][a-z0-9-]*")


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def documented_flags(text: str) -> set[str]:
    """Длинные флаги, упомянутые в inline-коде README."""
    return {
        flag
        for span in CODE_SPAN_RE.findall(text)
        for flag in LONG_FLAG_RE.findall(span)
    }


def parser_flags(script) -> set[str]:
    parser = script.build_parser()
    return {
        option
        for action in parser._actions
        for option in action.option_strings
        if option.startswith("--")
    }


def test_readmes_exist_and_cross_link():
    assert README_RU.is_file()
    assert README_EN.is_file()
    assert "README-EN-US.md" in read(README_RU)
    assert "README.md" in read(README_EN)


def test_readmes_document_same_flags():
    russian = documented_flags(read(README_RU))
    english = documented_flags(read(README_EN))

    assert CORE_FLAGS <= russian
    assert russian == english


def test_readmes_document_only_existing_options(script):
    options = parser_flags(script)

    for path in (README_RU, README_EN):
        unknown = documented_flags(read(path)) - options
        assert not unknown, f"{path.name} documents unknown flags: {unknown}"


def test_readmes_are_in_expected_languages():
    assert "Установка" in read(README_RU)
    assert "Installation" in read(README_EN)
    assert "Установка" not in read(README_EN)


def test_pyproject_uses_english_readme(script):
    project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    assert project["project"]["readme"] == "README-EN-US.md"
    assert project["project"]["version"] == script.VERSION
