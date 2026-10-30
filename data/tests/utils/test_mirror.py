"""Mirror: the scan finds every selected file, and a sync copies the source."""

import os
from pathlib import Path

import pytest

from space_map_data.utils import mirror


class TestScan:
    """The threaded scan finds the files of every depth and applies the filter."""

    def test_nested_tree(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        # Small batches, so one level spans several stat tasks.
        monkeypatch.setattr(mirror, "_STAT_BATCH", 2)
        files = [
            "top.json",
            "a/1.json",
            "a/source.jpg",
            "a/4.json",
            "a/5.json",
            "a/b/2.json",
            "c/d/e/3.json",
        ]
        for n, rel in enumerate(files):
            path = tmp_path / rel
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b"x" * n)
        (tmp_path / "empty").mkdir()
        os.symlink(tmp_path / "a", tmp_path / "link")

        found = mirror._scan(tmp_path, mirror._not_image_source)

        expected = {}
        for rel in files:
            if not rel.endswith("source.jpg"):
                st = (tmp_path / rel).stat()
                expected[Path(rel)] = (st.st_size, st.st_mtime_ns)
        assert found == expected


class TestSyncTree:
    """A sync makes the mirror equal to the source."""

    def test_file_replaces_directory(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(mirror, "DOWNLOAD_DIR", tmp_path / "src")
        monkeypatch.setattr(mirror, "MIRROR_DIR", tmp_path / "mirror")
        monkeypatch.setattr(mirror, "_synced_roots", [])
        old = tmp_path / "mirror" / "tree" / "x" / "a.json"
        old.parent.mkdir(parents=True)
        old.write_bytes(b"old")
        new = tmp_path / "src" / "tree" / "x"
        new.parent.mkdir(parents=True)
        new.write_bytes(b"new")

        mirror.sync_tree("tree")

        assert (tmp_path / "mirror" / "tree" / "x").read_bytes() == b"new"
