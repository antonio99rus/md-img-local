from __future__ import annotations

import os
from pathlib import Path

import pytest

from helpers import PNG_BYTES, FakeResponse, FakeSession

URL = "http://example.com/pic.png"


def make_downloader(script, tmp_path: Path, session: FakeSession):
    media_dir = tmp_path / "media"
    media_dir.mkdir(parents=True, exist_ok=True)
    return script.Downloader(media_dir, tmp_path, session)


def media_files(tmp_path: Path) -> list[Path]:
    return list((tmp_path / "media").iterdir())


def test_download_is_streamed(script, tmp_path):
    session = FakeSession({URL: FakeResponse()})
    make_downloader(script, tmp_path, session).localize(URL)

    _, kwargs = session.calls[0]
    assert kwargs["stream"] is True


def test_response_is_closed(script, tmp_path):
    response = FakeResponse()
    session = FakeSession({URL: response})

    make_downloader(script, tmp_path, session).localize(URL)

    assert response.closed is True


@pytest.mark.parametrize(
    "content_type",
    ["text/html", "application/zip", "image/svg+xml", "application/octet-stream"],
)
def test_non_image_content_type_is_rejected(
    script, tmp_path, capsys, content_type
):
    url = "http://example.com/download"
    session = FakeSession(
        {url: FakeResponse(headers={"Content-Type": content_type})}
    )
    downloader = make_downloader(script, tmp_path, session)

    result = downloader.localize(url)

    assert result == url
    assert downloader.failed == 1
    assert "not an allowed image type" in capsys.readouterr().out
    assert media_files(tmp_path) == []


def test_image_content_type_is_accepted(script, tmp_path):
    url = "http://example.com/download"
    session = FakeSession(
        {url: FakeResponse(headers={"Content-Type": "image/PNG; charset=binary"})}
    )

    result = make_downloader(script, tmp_path, session).localize(url)

    assert result.startswith("media/")
    assert (tmp_path / result).read_bytes() == PNG_BYTES


def test_declared_oversize_is_rejected_before_reading(
    script, tmp_path, capsys, monkeypatch
):
    monkeypatch.setattr(script, "MAX_DOWNLOAD_BYTES", 100)
    session = FakeSession(
        {
            URL: FakeResponse(
                headers={
                    "Content-Type": "image/png",
                    "Content-Length": "1000",
                }
            )
        }
    )
    downloader = make_downloader(script, tmp_path, session)

    result = downloader.localize(URL)

    assert result == URL
    assert downloader.failed == 1
    assert "too large" in capsys.readouterr().out
    assert media_files(tmp_path) == []


def test_streamed_oversize_is_rejected(
    script, tmp_path, capsys, monkeypatch
):
    monkeypatch.setattr(script, "MAX_DOWNLOAD_BYTES", 100)
    session = FakeSession({URL: FakeResponse(content=b"x" * 200)})
    downloader = make_downloader(script, tmp_path, session)

    result = downloader.localize(URL)

    assert result == URL
    assert downloader.failed == 1
    assert "too large" in capsys.readouterr().out
    assert media_files(tmp_path) == []


def test_body_exactly_at_limit_is_accepted(script, tmp_path, monkeypatch):
    monkeypatch.setattr(script, "MAX_DOWNLOAD_BYTES", len(PNG_BYTES))
    session = FakeSession({URL: FakeResponse()})

    result = make_downloader(script, tmp_path, session).localize(URL)

    assert (tmp_path / result).read_bytes() == PNG_BYTES


def test_invalid_content_length_is_ignored(script, tmp_path):
    session = FakeSession(
        {
            URL: FakeResponse(
                headers={
                    "Content-Type": "image/png",
                    "Content-Length": "not-a-number",
                }
            )
        }
    )

    result = make_downloader(script, tmp_path, session).localize(URL)

    assert (tmp_path / result).read_bytes() == PNG_BYTES


def test_successful_download_leaves_no_partial_files(script, tmp_path):
    session = FakeSession({URL: FakeResponse()})

    make_downloader(script, tmp_path, session).localize(URL)

    files = media_files(tmp_path)
    assert len(files) == 1
    assert files[0].suffix == ".png"
    assert not any(item.suffix == ".part" for item in files)


def test_failed_store_leaves_no_partial_file(
    script, tmp_path, capsys, monkeypatch
):
    session = FakeSession({URL: FakeResponse()})

    def broken_replace(source, destination):
        raise OSError("boom")

    monkeypatch.setattr(script.os, "replace", broken_replace)

    result = make_downloader(script, tmp_path, session).localize(URL)

    assert result == URL
    assert media_files(tmp_path) == []
    assert "Failed to save" in capsys.readouterr().out


def test_symlink_at_destination_is_replaced(script, tmp_path):
    media_dir = tmp_path / "media"
    media_dir.mkdir()
    target = tmp_path / "target.txt"
    target.write_text("keep", encoding="utf-8")
    filename = script.filename_for_url(URL, ".png")
    destination = media_dir / filename
    try:
        os.symlink(target, destination)
    except (OSError, NotImplementedError):
        pytest.skip("symlinks are not available")

    session = FakeSession({URL: FakeResponse()})
    downloader = script.Downloader(media_dir, tmp_path, session)

    downloader.localize(URL)

    assert not destination.is_symlink()
    assert destination.read_bytes() == PNG_BYTES
    assert target.read_text(encoding="utf-8") == "keep"
