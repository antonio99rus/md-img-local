from __future__ import annotations

import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
README_RU = ROOT / "README.md"
README_EN = ROOT / "README-EN-US.md"
FLAGS = ("--media", "--no-backup", "--proxy", "--lang")


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_readmes_exist_and_cross_link():
    assert README_RU.is_file()
    assert README_EN.is_file()
    assert "README-EN-US.md" in read(README_RU)
    assert "README.md" in read(README_EN)


def test_readmes_document_same_flags():
    russian = read(README_RU)
    english = read(README_EN)
    for flag in FLAGS:
        assert flag in russian, flag
        assert flag in english, flag


def test_readmes_are_in_expected_languages():
    assert "Установка" in read(README_RU)
    assert "Installation" in read(README_EN)
    assert "Установка" not in read(README_EN)


def test_pyproject_uses_english_readme(script):
    project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    assert project["project"]["readme"] == "README-EN-US.md"
    assert project["project"]["version"] == script.VERSION
