from __future__ import annotations

import re
from pathlib import Path

from toml_compat import tomllib

ROOT = Path(__file__).resolve().parents[1]
README_RU = ROOT / "README.md"
README_EN = ROOT / "README-EN-US.md"
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


def runtime_dependencies() -> set[str]:
    project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    names = set()
    for requirement in project["project"]["dependencies"]:
        match = re.match(r"[A-Za-z0-9_.-]+", requirement)
        assert match is not None, requirement
        names.add(match.group(0).lower())
    return names


def test_readmes_exist_and_cross_link():
    assert README_RU.is_file()
    assert README_EN.is_file()
    assert "README-EN-US.md" in read(README_RU)
    assert "README.md" in read(README_EN)


def test_readmes_document_every_cli_option(script):
    options = parser_flags(script)

    for path in (README_RU, README_EN):
        documented = documented_flags(read(path))
        missing = options - documented
        unknown = documented - options
        assert not missing, f"{path.name} does not document: {sorted(missing)}"
        assert not unknown, f"{path.name} documents unknown flags: {sorted(unknown)}"


def test_readmes_list_all_runtime_dependencies():
    requirements = runtime_dependencies()

    for path in (README_RU, README_EN):
        text = read(path).lower()
        for requirement in requirements:
            assert re.search(
                rf"\b{re.escape(requirement)}\b", text
            ), f"{path.name} misses {requirement}"


def test_readmes_do_not_mention_removed_certifi():
    for path in (README_RU, README_EN):
        assert re.search(r"\bcertifi\b", read(path).lower()) is None


def test_readmes_are_in_expected_languages():
    assert "Установка" in read(README_RU)
    assert "Installation" in read(README_EN)
    assert "Установка" not in read(README_EN)


def test_pyproject_uses_english_readme(script):
    project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    assert project["project"]["readme"] == "README-EN-US.md"
    assert project["project"]["version"] == script.VERSION
