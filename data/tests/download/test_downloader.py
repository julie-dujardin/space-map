"""Unit tests for the base Downloader freshness/staleness gates."""

import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

from space_map_data.download.downloader import Downloader


class _FakeDownloader(Downloader):
    name = "fake"

    def __init__(self, out_dir: Path, max_age: timedelta | None = None) -> None:
        self.out_dir = out_dir
        self.max_age = max_age

    def download(self, limit: int | None = None, **kwargs: object) -> None:
        raise NotImplementedError


def _write_metadata(out_dir: Path, *, age: timedelta, **extra: object) -> None:
    meta: dict[str, object] = {
        "downloaded_at": (datetime.now(timezone.utc) - age).isoformat(),
        **extra,
    }
    (out_dir / "metadata.json").write_text(json.dumps(meta))


def test_complete_flag_trusted_forever_without_max_age(tmp_path):
    _write_metadata(tmp_path, age=timedelta(days=365), complete=True)
    assert _FakeDownloader(tmp_path).is_complete(limit=None)


def test_complete_flag_expires_after_max_age(tmp_path):
    dl = _FakeDownloader(tmp_path, max_age=timedelta(days=7))
    _write_metadata(tmp_path, age=timedelta(days=1), complete=True)
    assert dl.is_complete(limit=None)
    _write_metadata(tmp_path, age=timedelta(days=8), complete=True)
    assert not dl.is_complete(limit=None)


def test_record_count_skip_also_expires(tmp_path):
    dl = _FakeDownloader(tmp_path, max_age=timedelta(days=7))
    _write_metadata(tmp_path, age=timedelta(days=8), record_count=100)
    assert not dl.is_complete(limit=50)


def test_missing_or_bad_downloaded_at_counts_as_stale(tmp_path):
    dl = _FakeDownloader(tmp_path, max_age=timedelta(days=7))
    (tmp_path / "metadata.json").write_text(json.dumps({"complete": True}))
    assert not dl.is_complete(limit=None)
    (tmp_path / "metadata.json").write_text(
        json.dumps({"complete": True, "downloaded_at": "not-a-date"})
    )
    assert not dl.is_complete(limit=None)


def test_is_fresh_by_mtime(tmp_path):
    dl = _FakeDownloader(tmp_path, max_age=timedelta(days=7))
    path = tmp_path / "payload.json"
    assert not dl._is_fresh(path)
    path.write_text("{}")
    assert dl._is_fresh(path)
    old = (datetime.now(timezone.utc) - timedelta(days=8)).timestamp()
    os.utime(path, (old, old))
    assert not dl._is_fresh(path)


def test_is_fresh_ignores_age_without_max_age(tmp_path):
    dl = _FakeDownloader(tmp_path)
    path = tmp_path / "payload.json"
    path.write_text("{}")
    old = (datetime.now(timezone.utc) - timedelta(days=365)).timestamp()
    os.utime(path, (old, old))
    assert dl._is_fresh(path)
