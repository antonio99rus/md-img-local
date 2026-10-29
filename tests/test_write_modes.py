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


def sidecar(path: Path, kind: str) -> Path:
    return path.with_name(f".{path.name}.md-img-{kind}")


def hold_lock(path: Path) -> int:
    flags = os.O_RDWR | getattr(os, "O_BINARY", 0)
    descriptor = os.open(path, flags)
    if sys.platform == "win32":
        import msvcrt

        os.lseek(descriptor, 0x40000000, os.SEEK_SET)
        msvcrt.locking(descriptor, msvcrt.LK_NBLCK, 1)
        os.lseek(descriptor, 0, os.SEEK_SET)
    else:
        import fcntl

        fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
    return descriptor


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
    script, monkeypatch, run_main, tmp_path, fake_session, capsys
):
    original = f"![a]({URL})\n"
    path = write_md(tmp_path, original)

    def broken_replace(source, destination):
        raise OSError("replace failed")

    monkeypatch.setattr(script.os, "replace", broken_replace)

    with pytest.raises(SystemExit) as error:
        run_main(path, "--write-mode=atomic")

    assert error.value.code == 2
    assert "replace failed" in capsys.readouterr().err
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


def test_in_place_removes_journal_and_staged_file(
    run_main, tmp_path, fake_session
):
    path = write_md(tmp_path, f"![a]({URL})\n")

    run_main(path)

    assert not sidecar(path, "journal").exists()
    assert not sidecar(path, "new").exists()
    assert "media/" in path.read_text(encoding="utf-8")


def test_journal_from_previous_run_blocks_write(
    run_main, tmp_path, fake_session, capsys
):
    original = f"![a]({URL})\n"
    path = write_md(tmp_path, original)
    journal = sidecar(path, "journal")
    journal.write_text("{}", encoding="utf-8")

    with pytest.raises(SystemExit) as error:
        run_main(path)

    assert error.value.code == 2
    assert journal.exists()
    assert path.read_text(encoding="utf-8") == original
    assert "journal" in capsys.readouterr().err.lower()


def test_force_discards_stale_journal(run_main, tmp_path, fake_session):
    path = write_md(tmp_path, f"![a]({URL})\n")
    journal = sidecar(path, "journal")
    journal.write_text("{}", encoding="utf-8")
    sidecar(path, "new").write_bytes(b"stale")

    run_main(path, "--force")

    assert not journal.exists()
    assert not sidecar(path, "new").exists()
    assert "media/" in path.read_text(encoding="utf-8")


def test_no_backup_in_place_requires_force(
    run_main, tmp_path, fake_session, capsys
):
    original = f"![a]({URL})\n"
    path = write_md(tmp_path, original)

    with pytest.raises(SystemExit) as error:
        run_main(path, "--no-backup")

    assert error.value.code == 2
    assert "--force" in capsys.readouterr().err
    assert path.read_text(encoding="utf-8") == original


def test_no_backup_with_force_allows_in_place(
    run_main, tmp_path, fake_session
):
    path = write_md(tmp_path, f"![a]({URL})\n")

    run_main(path, "--no-backup", "--force")

    assert "media/" in path.read_text(encoding="utf-8")
    assert not path.with_name(f"{path.name}.orig").exists()


def test_no_backup_is_allowed_for_atomic_mode(
    run_main, tmp_path, fake_session
):
    path = write_md(tmp_path, f"![a]({URL})\n")

    run_main(path, "--no-backup", "--write-mode=atomic")

    assert "media/" in path.read_text(encoding="utf-8")
    assert not path.with_name(f"{path.name}.orig").exists()


def test_concurrent_change_aborts_in_place_write(
    script, monkeypatch, run_main, tmp_path, fake_session, capsys
):
    original = f"![a]({URL})\n"
    path = write_md(tmp_path, original)
    real_write = script._write_file_sync
    raced = False

    def racing_write(target, data):
        nonlocal raced
        real_write(target, data)
        if not raced:
            raced = True
            with open(path, "a", encoding="utf-8") as stream:
                stream.write("external\n")

    monkeypatch.setattr(script, "_write_file_sync", racing_write)

    with pytest.raises(SystemExit) as error:
        run_main(path)

    assert error.value.code == 2
    assert "changed" in capsys.readouterr().err
    assert path.read_text(encoding="utf-8") == original + "external\n"
    assert not sidecar(path, "journal").exists()
    assert not sidecar(path, "new").exists()


def test_failed_verification_restores_backup(
    script, monkeypatch, run_main, tmp_path, fake_session, capsys
):
    original = f"![a]({URL})\n"
    path = write_md(tmp_path, original)

    monkeypatch.setattr(script, "_read_all", lambda descriptor: b"tampered")

    with pytest.raises(SystemExit) as error:
        run_main(path)

    assert error.value.code == 2
    assert "restored" in capsys.readouterr().err
    assert path.read_text(encoding="utf-8") == original
    backup = path.with_name(f"{path.name}.orig")
    assert backup.read_text(encoding="utf-8") == original
    assert not sidecar(path, "journal").exists()
    assert not sidecar(path, "new").exists()


def test_failed_verification_without_backup_reports_damage(
    script, monkeypatch, run_main, tmp_path, fake_session, capsys
):
    original = f"![a]({URL})\n"
    path = write_md(tmp_path, original)

    monkeypatch.setattr(script, "_read_all", lambda descriptor: b"tampered")

    with pytest.raises(SystemExit) as error:
        run_main(path, "--no-backup", "--force")

    assert error.value.code == 2
    assert "no backup" in capsys.readouterr().err.lower()
    assert not sidecar(path, "journal").exists()


def test_locked_file_reports_clean_error(
    run_main, tmp_path, fake_session, capsys
):
    original = f"![a]({URL})\n"
    path = write_md(tmp_path, original)
    descriptor = hold_lock(path)
    try:
        with pytest.raises(SystemExit) as error:
            run_main(path)
    finally:
        os.close(descriptor)

    assert error.value.code == 2
    assert "lock" in capsys.readouterr().err.lower()
    assert path.read_text(encoding="utf-8") == original
