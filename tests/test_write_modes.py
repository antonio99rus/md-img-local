from __future__ import annotations

import os
import stat
import sys
from pathlib import Path

import pytest

from helpers import URL


def write_md(tmp_path: Path, text: str) -> Path:
    path = tmp_path / "note.md"
    path.write_text(text, encoding="utf-8")
    return path


def temp_files(directory: Path) -> list[Path]:
    return [item for item in directory.iterdir() if item.suffix == ".tmp"]


def test_in_place_write_mode_is_default(run_main, tmp_path, fake_session):
    path = write_md(tmp_path, f"![a]({URL})\n")
    inode = path.stat().st_ino

    run_main(path)

    assert path.stat().st_ino == inode
    assert "media/" in path.read_text(encoding="utf-8")


def test_in_place_write_mode_keeps_hardlink(run_main, tmp_path, fake_session):
    path = write_md(tmp_path, f"![a]({URL})\n")
    link = tmp_path / "link.md"
    os.link(path, link)
    inode = path.stat().st_ino

    run_main(path, "--write-mode=in-place")

    assert path.stat().st_ino == inode
    assert link.stat().st_ino == inode
    assert "media/" in link.read_text(encoding="utf-8")


def test_atomic_write_mode_replaces_inode(run_main, tmp_path, fake_session):
    path = write_md(tmp_path, f"![a]({URL})\n")
    inode = path.stat().st_ino

    run_main(path, "--write-mode=atomic")

    assert path.stat().st_ino != inode
    assert "media/" in path.read_text(encoding="utf-8")


def test_atomic_write_mode_breaks_hardlink(run_main, tmp_path, fake_session):
    original = f"![a]({URL})\n"
    path = write_md(tmp_path, original)
    link = tmp_path / "link.md"
    os.link(path, link)

    run_main(path, "--write-mode=atomic")

    assert "media/" in path.read_text(encoding="utf-8")
    assert link.read_text(encoding="utf-8") == original


def test_atomic_write_mode_leaves_no_temp_files(
    run_main, tmp_path, fake_session
):
    path = write_md(tmp_path, f"![a]({URL})\n")

    run_main(path, "--write-mode=atomic")

    assert temp_files(tmp_path) == []


def test_atomic_write_mode_keeps_source_on_failure(
    script, monkeypatch, run_main, tmp_path, fake_session
):
    original = f"![a]({URL})\n"
    path = write_md(tmp_path, original)

    def broken_replace(source, destination):
        raise OSError("replace failed")

    monkeypatch.setattr(script.os, "replace", broken_replace)

    with pytest.raises(OSError):
        run_main(path, "--write-mode=atomic")

    assert path.read_text(encoding="utf-8") == original
    assert temp_files(tmp_path) == []


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX permissions")
def test_atomic_write_mode_preserves_permissions(
    run_main, tmp_path, fake_session
):
    path = write_md(tmp_path, f"![a]({URL})\n")
    os.chmod(path, 0o600)

    run_main(path, "--write-mode=atomic")

    assert stat.S_IMODE(path.stat().st_mode) == 0o600


def test_unknown_write_mode_is_rejected(run_main, tmp_path, capsys):
    path = write_md(tmp_path, f"![a]({URL})\n")

    with pytest.raises(SystemExit) as error:
        run_main(path, "--write-mode=rewrite")

    assert error.value.code == 2
    assert "write-mode" in capsys.readouterr().err
