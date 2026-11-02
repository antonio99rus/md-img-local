from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

from toml_compat import tomllib

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "md-img-local.py"


def run_cli(*args: str, lang: str = "en") -> subprocess.CompletedProcess[str]:
    env = dict(
        os.environ,
        PYTHONIOENCODING="utf-8",
        MD_IMG_LOCAL_LANG=lang,
    )
    return subprocess.run(
        [sys.executable, str(SCRIPT), *args],
        capture_output=True,
        text=True,
        encoding="utf-8",
        env=env,
    )


def test_version_flag(script):
    result = run_cli("--version")

    assert result.returncode == 0
    assert script.VERSION in result.stdout


def test_help_mentions_proxy_and_lang():
    result = run_cli("--help")

    assert result.returncode == 0
    assert "--proxy" in result.stdout
    assert "--lang" in result.stdout
    assert "--verbose" in result.stdout
    assert "--user-agent" in result.stdout
    assert "socks5://127.0.0.1:3066" in result.stdout
    assert "usage:" in result.stdout
    assert "options:" in result.stdout


def test_help_is_russian_for_russian_locale():
    result = run_cli("--help", lang="ru")

    assert result.returncode == 0
    assert "использование:" in result.stdout
    assert "параметры:" in result.stdout
    assert "позиционные аргументы:" in result.stdout
    assert "usage:" not in result.stdout


def test_lang_flag_overrides_environment():
    result = run_cli("--help", "--lang=en", lang="ru")

    assert result.returncode == 0
    assert "usage:" in result.stdout
    assert "использование:" not in result.stdout


def test_invalid_lang_is_rejected():
    result = run_cli("--lang=de")

    assert result.returncode == 2
    assert "invalid choice" in result.stderr


def test_missing_argument_exits_with_usage():
    result = run_cli()

    assert result.returncode == 2
    assert "usage:" in result.stderr


def test_version_matches_pyproject(script):
    project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    assert project["project"]["version"] == script.VERSION


def test_failed_download_exits_with_code_1(tmp_path):
    path = tmp_path / "note.md"
    path.write_text(
        "![a](http://127.0.0.1:1/missing.png)\n", encoding="utf-8"
    )

    result = run_cli(str(path))

    assert result.returncode == 1
    assert "Errors: 1" in result.stdout


def test_media_file_exits_with_code_2(tmp_path):
    path = tmp_path / "note.md"
    path.write_text("![a](http://example.com/img.png)\n", encoding="utf-8")
    media = tmp_path / "media"
    media.write_text("not a directory", encoding="utf-8")

    result = run_cli(str(path), f"--media={media}")

    assert result.returncode == 2
    assert "not a directory" in result.stderr


def test_output_is_utf8_without_pythonioencoding():
    env = dict(os.environ, MD_IMG_LOCAL_LANG="ru")
    env.pop("PYTHONIOENCODING", None)

    result = subprocess.run(
        [sys.executable, str(SCRIPT), "--help"],
        capture_output=True,
        env=env,
    )

    assert result.returncode == 0
    assert "использование:" in result.stdout.decode("utf-8")
