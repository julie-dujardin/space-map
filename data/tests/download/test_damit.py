"""Checks for the DAMIT download: which export it takes, and that an export
with no tables never replaces a good extract."""

import io
import tarfile
from pathlib import Path

import pytest

from space_map_data.download.downloader import DownloadError
from space_map_data.download.providers.three_d import damit


def _listing(*rows: tuple[str, str]) -> str:
    links = "".join(
        f'<li><a href="/projects/damit/exports/complete/{name}">{name} ({size})</a></li>'
        for name, size in rows
    )
    return f"<ul>{links}</ul>"


def _archive(path: Path, *names: str) -> Path:
    root = "damit-20261001T000303Z"
    with tarfile.open(path, "w:gz") as tar:
        for name in names:
            info = tarfile.TarInfo(f"{root}/{name}")
            info.size = 1
            tar.addfile(info, io.BytesIO(b"x"))
    return path


class TestWholeArchive:
    """The newest export that is not cut short."""

    def test_skips_exports_that_came_out_short(self):
        page = _listing(
            ("damit-20261101T010306Z.tar.gz", "350.66 MB"),
            ("damit-20261031T010302Z.tar.gz", "744.23 MB"),
            ("damit-20261001T000303Z.tar.gz", "1.31 GB"),
            ("damit-20260901T000302Z.tar.gz", "1.32 GB"),
        )
        assert damit.whole_archive(page) == "damit-20261001T000303Z.tar.gz"

    def test_takes_the_newest_when_it_is_whole(self):
        page = _listing(
            ("damit-20261101T010306Z.tar.gz", "1.31 GB"),
            ("damit-20261001T000303Z.tar.gz", "1.32 GB"),
        )
        assert damit.whole_archive(page) == "damit-20261101T010306Z.tar.gz"

    def test_page_without_exports_is_an_error(self):
        with pytest.raises(DownloadError):
            damit.whole_archive("<ul></ul>")


class TestExtract:
    """The extract in place goes only for an export that has its tables."""

    @pytest.fixture
    def extract_dir(self, tmp_path, monkeypatch) -> Path:
        path = tmp_path / "damit"
        path.mkdir()
        (path / "old.txt").write_text("old")
        monkeypatch.setattr(damit, "EXTRACT_DIR", path)
        return path

    def _downloader(self) -> damit.DAMITDownloader:
        return damit.DAMITDownloader.__new__(damit.DAMITDownloader)

    def test_export_with_tables_replaces_the_extract(self, extract_dir, tmp_path):
        archive = _archive(
            tmp_path / "whole.tar.gz",
            "tables/asteroids.csv",
            "tables/asteroid_models.csv",
            "files/asteroid_1/model_1/shape.txt",
        )
        self._downloader()._extract(archive)
        assert damit.has_tables(extract_dir)
        assert not (extract_dir / "old.txt").exists()
        assert not extract_dir.with_name("damit.new").exists()

    def test_export_without_tables_leaves_the_extract(self, extract_dir, tmp_path):
        archive = _archive(tmp_path / "cut.tar.gz", "files/asteroid_1/lc.txt")
        with pytest.raises(tarfile.TarError):
            self._downloader()._extract(archive)
        assert (extract_dir / "old.txt").read_text() == "old"
        assert not extract_dir.with_name("damit.new").exists()
