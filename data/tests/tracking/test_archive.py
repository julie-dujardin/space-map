"""Sealing days, and folding them into months and years.

Dates are fixed rather than relative to now: the whole point of the module is
what it considers finished, so "today" is an input here.
"""

import gzip
import json
import tarfile
from datetime import date

import pytest

from space_map_data.tracking import archive

POLL = {"t": "2026-09-17T08:44:22+00:00", "xml": "<dsn/>"}


@pytest.fixture
def dsn_dir(tmp_path):
    root = tmp_path / "dsn"
    (root / "raw").mkdir(parents=True)
    (root / "observations").mkdir(parents=True)
    (root / "snapshots" / "VGR1").mkdir(parents=True)
    return root


@pytest.fixture
def bot_dir(tmp_path):
    root = tmp_path / "bot"
    (root / "events").mkdir(parents=True)
    return root


@pytest.fixture
def estrack_dir(tmp_path):
    root = tmp_path / "estrack"
    (root / "live").mkdir(parents=True)
    (root / "months").mkdir(parents=True)
    return root


def _log(directory, day: str, record: dict) -> None:
    packed = gzip.compress((json.dumps(record) + "\n").encode())
    (directory / f"{day}.jsonl.gz").write_bytes(packed)


def _run(tmp_path, dsn_dir, estrack_dir, today: date, bot_dir=None):
    return archive.run(
        root=tmp_path / "archive",
        dsn_dir=dsn_dir,
        estrack_dir=estrack_dir,
        bot_dir=bot_dir or tmp_path / "bot",
        today=today,
    )


class TestSealingADay:
    """A day is archived once nothing can still be written to it."""

    def test_a_settled_day_is_copied_out_decompressed(
        self, tmp_path, dsn_dir, estrack_dir
    ):
        _log(dsn_dir / "raw", "2026-09-17", POLL)
        _run(tmp_path, dsn_dir, estrack_dir, date(2026, 9, 20))
        day = tmp_path / "archive" / "data" / "2026" / "09" / "17"
        assert json.loads((day / "dsn" / "raw.jsonl").read_text()) == POLL

    def test_a_day_that_only_just_ended_is_left_alone(
        self, tmp_path, dsn_dir, estrack_dir
    ):
        _log(dsn_dir / "raw", "2026-09-17", POLL)
        assert _run(tmp_path, dsn_dir, estrack_dir, date(2026, 9, 18)) == []

    def test_sealing_twice_changes_nothing(self, tmp_path, dsn_dir, estrack_dir):
        _log(dsn_dir / "raw", "2026-09-17", POLL)
        assert _run(tmp_path, dsn_dir, estrack_dir, date(2026, 9, 20)) != []
        assert _run(tmp_path, dsn_dir, estrack_dir, date(2026, 9, 20)) == []

    def test_contacts_are_filed_under_the_day_they_ended(
        self, tmp_path, dsn_dir, estrack_dir
    ):
        _log(dsn_dir / "raw", "2026-09-17", POLL)
        (dsn_dir / "contacts.jsonl").write_text(
            json.dumps({"code": "VGR1", "end": "2026-09-17T09:00:00+00:00"})
            + "\n"
            + json.dumps({"code": "MEX", "end": "2026-09-18T09:00:00+00:00"})
            + "\n"
        )
        _run(tmp_path, dsn_dir, estrack_dir, date(2026, 9, 20))
        day = tmp_path / "archive" / "data" / "2026" / "09" / "17"
        (line,) = (day / "dsn" / "contacts.jsonl").read_text().splitlines()
        assert json.loads(line)["code"] == "VGR1"

    def test_the_dictionary_of_the_day_travels_with_it(
        self, tmp_path, dsn_dir, estrack_dir
    ):
        _log(dsn_dir / "raw", "2026-09-17", POLL)
        (dsn_dir / "config-20260917T123002Z.xml").write_text("<config/>")
        (dsn_dir / "snapshots" / "VGR1" / "20260917T124500Z.xml").write_text("<s/>")
        _run(tmp_path, dsn_dir, estrack_dir, date(2026, 9, 20))
        day = tmp_path / "archive" / "data" / "2026" / "09" / "17" / "dsn"
        assert (day / "config-20260917T123002Z.xml").exists()
        assert (day / "snapshots" / "VGR1" / "20260917T124500Z.xml").exists()

    def test_the_month_volumes_sit_beside_the_days(
        self, tmp_path, dsn_dir, estrack_dir
    ):
        _log(estrack_dir / "live", "2026-09-17", {"live_missions": []})
        (estrack_dir / "months" / "2026-09.json").write_text('{"month": "2026-09"}')
        _run(tmp_path, dsn_dir, estrack_dir, date(2026, 9, 20))
        month = tmp_path / "archive" / "data" / "2026" / "09"
        assert json.loads((month / "estrack-volume.json").read_text())


class TestTheBotsRecord:
    """A source that arrives late has to be able to fill a day already sealed."""

    def test_years_of_backfill_are_sealed_and_rolled_up_in_one_pass(
        self, tmp_path, dsn_dir, estrack_dir, bot_dir
    ):
        _log(bot_dir / "events", "2024-12-06", {"t": "2024-12-06", "c": "MVN"})
        _run(tmp_path, dsn_dir, estrack_dir, date(2026, 9, 20), bot_dir)
        with tarfile.open(tmp_path / "archive" / "data" / "2024.tar.gz") as tar:
            assert "12/06/dsn-bot/events.jsonl" in tar.getnames()

    def test_a_backfill_fills_a_day_that_was_already_sealed(
        self, tmp_path, dsn_dir, estrack_dir, bot_dir
    ):
        _log(dsn_dir / "raw", "2026-09-17", POLL)
        _run(tmp_path, dsn_dir, estrack_dir, date(2026, 9, 20), bot_dir)
        _log(bot_dir / "events", "2026-09-17", {"t": "2026-09-17", "c": "VGR1"})
        assert _run(tmp_path, dsn_dir, estrack_dir, date(2026, 9, 20), bot_dir) != []
        day = tmp_path / "archive" / "data" / "2026" / "09" / "17"
        assert (day / "dsn-bot" / "events.jsonl").exists()
        assert (day / "dsn" / "raw.jsonl").exists()


class TestRollingUp:
    """Whole periods are replaced by one archive, named for what they replace."""

    def test_a_complete_month_becomes_one_gzip_of_its_days(
        self, tmp_path, dsn_dir, estrack_dir
    ):
        for day in ("2026-09-17", "2026-09-18"):
            _log(dsn_dir / "raw", day, POLL)
        _run(tmp_path, dsn_dir, estrack_dir, date(2026, 10, 5))
        year = tmp_path / "archive" / "data" / "2026"
        assert not (year / "09").exists()
        with tarfile.open(year / "09.tar.gz") as tar:
            assert "17/dsn/raw.jsonl" in tar.getnames()
            assert "18/dsn/raw.jsonl" in tar.getnames()

    def test_a_month_still_running_stays_a_directory(
        self, tmp_path, dsn_dir, estrack_dir
    ):
        _log(dsn_dir / "raw", "2026-09-17", POLL)
        _run(tmp_path, dsn_dir, estrack_dir, date(2026, 9, 25))
        assert (tmp_path / "archive" / "data" / "2026" / "09" / "17").is_dir()

    def test_a_packed_period_is_never_sealed_again(
        self, tmp_path, dsn_dir, estrack_dir, bot_dir
    ):
        _log(bot_dir / "events", "2025-03-30", {"t": "2025-03-30", "c": "LTB"})
        _log(dsn_dir / "raw", "2026-09-17", POLL)
        assert _run(tmp_path, dsn_dir, estrack_dir, date(2026, 9, 20), bot_dir) != []
        packed = tmp_path / "archive" / "data" / "2025.tar.gz"
        before = packed.read_bytes()
        assert _run(tmp_path, dsn_dir, estrack_dir, date(2026, 9, 20), bot_dir) == []
        assert packed.read_bytes() == before

    def test_a_complete_year_becomes_one_gzip_of_its_months(
        self, tmp_path, dsn_dir, estrack_dir
    ):
        _log(dsn_dir / "raw", "2026-09-17", POLL)
        _log(dsn_dir / "raw", "2026-10-25", POLL)
        _run(tmp_path, dsn_dir, estrack_dir, date(2027, 1, 10))
        data = tmp_path / "archive" / "data"
        assert not (data / "2026").exists()
        with tarfile.open(data / "2026.tar.gz") as tar:
            assert "10/25/dsn/raw.jsonl" in tar.getnames()
            assert "09/17/dsn/raw.jsonl" in tar.getnames()
