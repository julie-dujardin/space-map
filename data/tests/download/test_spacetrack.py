"""Unit tests for the Space-Track GP downloader."""

import json
from datetime import date, datetime, timezone

import httpx
import pytest

from space_map_data.download.downloader import DownloadError
from space_map_data.download.providers.objects import spacetrack
from space_map_data.download.providers.objects.spacetrack import (
    _DAYS_SIDECAR,
    SpaceTrackDownloader,
    _completed_year_mondays,
)

_GP_HEADER = (
    "OBJECT_NAME,OBJECT_ID,EPOCH,MEAN_MOTION,ECCENTRICITY,INCLINATION,"
    "RA_OF_ASC_NODE,ARG_OF_PERICENTER,MEAN_ANOMALY,NORAD_CAT_ID,ELEMENT_SET_NO,"
    "REV_AT_EPOCH,BSTAR,MEAN_MOTION_DOT,MEAN_MOTION_DDOT"
)


def _row(name: str, epoch: str, norad: int) -> str:
    return (
        f"{name},1958-002B,{epoch},10.85997349,0.18354928,34.2465,326.7899,"
        f"120.2934,259.1949,{norad},999,44284,0.00040821,3.03e-06,0.0"
    )


_GP_CSV = _GP_HEADER + "\r\n" + _row("VANGUARD 1", "2026-06-13T03:35:44", 5) + "\r\n"

# gp_history window for the week of Mon 2026-01-05 (midpoint Thu 2026-01-08 12:00):
# NORAD 5 appears twice; the row nearer the midpoint must win.
_HISTORY_CSV = "\r\n".join(
    [
        _GP_HEADER,
        _row("SAT5-FAR", "2026-01-07T00:00:00", 5),
        _row("SAT5-NEAR", "2026-01-08T13:00:00", 5),
        _row("SAT11", "2026-01-09T06:00:00", 11),
    ]
)


# A snapshot left by the old three-day scheme: SAT99 came from its follow-up (no
# bulk day has it), SAT5 from a day further out than the top-up will reach.
_LEGACY_CSV = "\r\n".join(
    [
        _GP_HEADER,
        _row("SAT99", "2026-01-08T12:30:00", 99),
        _row("SAT5-STORED", "2026-01-06T00:00:00", 5),
    ]
)


def _seed_week(out_dir, monday, body: str, offsets: list[int] | None = None):
    """Write a stored snapshot, with a day sidecar only when ``offsets`` is given."""
    day_dir = (
        out_dir / f"{monday.year:04d}" / f"{monday.month:02d}" / f"{monday.day:02d}"
    )
    day_dir.mkdir(parents=True)
    (day_dir / "gp-active.csv").write_text(body)
    if offsets is not None:
        (day_dir / _DAYS_SIDECAR).write_text(json.dumps({"day_offsets": offsets}))
    return day_dir


class _Resp:
    def __init__(self, text: str = "", status_code: int = 200) -> None:
        self.text = text
        self.status_code = status_code

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise httpx.HTTPStatusError("err", request=None, response=None)  # type: ignore[arg-type]


class _Client:
    """httpx.Client stand-in that routes gp / gp_history and records URLs."""

    def __init__(
        self,
        login: _Resp,
        gp: _Resp,
        history: _Resp | None = None,
    ) -> None:
        self._login, self._gp, self._history = login, gp, history
        self.gp_url: str | None = None
        self.history_urls: list[str] = []

    def post(self, url: str, data: dict) -> _Resp:
        return self._login

    def get(self, url: str) -> _Resp:
        if "gp_history" in url:
            self.history_urls.append(url)
            return self._history or _Resp(_HISTORY_CSV)
        self.gp_url = url
        return self._gp


@pytest.fixture
def out_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(spacetrack, "SOURCES_POSITION_DIR", tmp_path)
    monkeypatch.setattr(spacetrack.time, "sleep", lambda *_: None)
    monkeypatch.setenv("SPACETRACK_IDENTITY", "u")
    monkeypatch.setenv("SPACETRACK_PASSWORD", "p")
    return tmp_path / "spacetrack" / "current"


def test_missing_credentials_raises(out_dir, monkeypatch):
    monkeypatch.delenv("SPACETRACK_IDENTITY", raising=False)
    dl = SpaceTrackDownloader(_Client(_Resp(), _Resp(_GP_CSV)))  # type: ignore[arg-type]
    with pytest.raises(DownloadError, match="SPACETRACK_IDENTITY"):
        dl.download()


def test_login_failure_raises(out_dir):
    client = _Client(_Resp('{"Login":"Failed"}'), _Resp(_GP_CSV))
    dl = SpaceTrackDownloader(client)  # type: ignore[arg-type]
    with pytest.raises(DownloadError, match="login failed"):
        dl.download()


def test_download_writes_catalogue_and_metadata(out_dir):
    # A successful Space-Track login returns an empty-string body (`""`).
    client = _Client(_Resp('""'), _Resp(_GP_CSV))
    dl = SpaceTrackDownloader(client)  # type: ignore[arg-type]
    dl.MAX_BACKFILL_WEEKS_PER_RUN = 0  # isolate the daily path
    dl.download()

    today = datetime.now(timezone.utc).date()
    day_dir = out_dir / f"{today.year:04d}" / f"{today.month:02d}" / f"{today.day:02d}"
    written = (day_dir / "gp-active.csv").read_text()
    assert "NORAD_CAT_ID" in written
    assert "VANGUARD 1" in written
    # Daily query is scoped to non-decayed recent elements.
    assert client.gp_url is not None and "decay_date/null-val" in client.gp_url


def test_unexpected_gp_response_raises(out_dir):
    client = _Client(_Resp(), _Resp("<html>login</html>"))
    dl = SpaceTrackDownloader(client)  # type: ignore[arg-type]
    dl.MAX_BACKFILL_WEEKS_PER_RUN = 0
    with pytest.raises(DownloadError, match="Unexpected GP response"):
        dl.download()


def test_completed_year_mondays():
    # Jan 5 and Jan 12's weeks have fully elapsed by Jan 20; Jan 19's has not.
    assert _completed_year_mondays(date(2026, 1, 20)) == [
        date(2026, 1, 5),
        date(2026, 1, 12),
    ]
    # Nothing completed yet in the first days of the year.
    assert _completed_year_mondays(date(2026, 1, 3)) == []


def test_fetch_week_keeps_row_nearest_midpoint(out_dir):
    client = _Client(_Resp('""'), _Resp(_GP_CSV), _Resp(_HISTORY_CSV))
    dl = SpaceTrackDownloader(client)  # type: ignore[arg-type]
    dl._fetch_week(date(2026, 1, 5))

    written = (out_dir / "2026" / "01" / "05" / "gp-active.csv").read_text()
    assert "SAT5-NEAR" in written and "SAT5-FAR" not in written  # nearest midpoint wins
    assert "SAT11" in written


def test_fetch_week_pulls_every_day_of_the_week(out_dir):
    client = _Client(_Resp('""'), _Resp(_GP_CSV), _Resp(_HISTORY_CSV))
    dl = SpaceTrackDownloader(client)  # type: ignore[arg-type]
    dl._fetch_week(date(2026, 1, 5))

    # One full-catalogue day per day of the week, each a single-day window and
    # none NORAD-bounded — a long NORAD list in the URL is what Space-Track 403s.
    assert len(client.history_urls) == 7
    assert all("NORAD_CAT_ID/" not in u for u in client.history_urls)
    assert "epoch/2026-01-05--2026-01-06" in client.history_urls[0]
    assert "epoch/2026-01-11--2026-01-12" in client.history_urls[-1]


def test_fetch_week_tops_up_a_legacy_snapshot(out_dir):
    client = _Client(_Resp('""'), _Resp(_GP_CSV), _Resp(_HISTORY_CSV))
    dl = SpaceTrackDownloader(client)  # type: ignore[arg-type]
    # No sidecar → written by the three-day scheme, which pulled Tue/Thu/Sat.
    day_dir = _seed_week(out_dir, date(2026, 1, 5), _LEGACY_CSV)

    dl._fetch_week(date(2026, 1, 5))

    # Only the four days that scheme never fetched are paid for.
    assert len(client.history_urls) == 4
    assert [u.split("epoch/")[1][:10] for u in client.history_urls] == [
        "2026-01-05",
        "2026-01-07",
        "2026-01-09",
        "2026-01-11",
    ]
    written = (day_dir / "gp-active.csv").read_text()
    # A stored row no fetched day supplies survives the top-up...
    assert "SAT99" in written
    # ...while one the top-up beats on distance to the midpoint is replaced.
    assert "SAT5-NEAR" in written and "SAT5-STORED" not in written
    # The week is now complete, so a later run leaves it alone.
    assert dl._covered_offsets(date(2026, 1, 5)) == frozenset(range(7))


def test_incomplete_weeks_includes_a_legacy_snapshot(out_dir):
    dl = SpaceTrackDownloader(_Client(_Resp('""'), _Resp(_GP_CSV)))  # type: ignore[arg-type]
    _seed_week(out_dir, date(2026, 1, 5), _LEGACY_CSV)  # legacy, still owed days
    _seed_week(out_dir, date(2026, 1, 12), _LEGACY_CSV, offsets=list(range(7)))

    assert dl._incomplete_weeks(date(2026, 1, 26)) == [
        date(2026, 1, 5),
        date(2026, 1, 19),
    ]


def test_download_skips_daily_when_present(out_dir):
    client = _Client(_Resp('""'), _Resp(_GP_CSV), _Resp(_HISTORY_CSV))
    dl = SpaceTrackDownloader(client)  # type: ignore[arg-type]
    dl.MAX_BACKFILL_WEEKS_PER_RUN = 0
    today = datetime.now(timezone.utc).date()
    daily = out_dir / f"{today.year:04d}" / f"{today.month:02d}" / f"{today.day:02d}"
    daily.mkdir(parents=True)
    (daily / "gp-active.csv").write_text(_GP_CSV)

    dl.download()
    assert client.gp_url is None  # daily fetch skipped, already present


def test_fetch_week_surfaces_error_body(out_dir):
    client = _Client(
        _Resp('""'), _Resp(_GP_CSV), _Resp("Query range out of bounds", 500)
    )
    dl = SpaceTrackDownloader(client)  # type: ignore[arg-type]
    with pytest.raises(DownloadError, match="HTTP 500.*out of bounds"):
        dl._fetch_week(date(2026, 1, 5))


def test_backfill_stops_on_first_error(out_dir):
    client = _Client(_Resp('""'), _Resp(_GP_CSV), _Resp("", 500))
    dl = SpaceTrackDownloader(client)  # type: ignore[arg-type]
    # today = Mon 2026-02-02 → 4 completed weeks, all missing.
    fetched, remaining = dl._backfill_weeks(date(2026, 2, 2))
    assert (fetched, remaining) == (0, 4)
    assert len(client.history_urls) == 1  # bailed after the first failure


def test_backfill_caps_and_skips_existing(out_dir):
    client = _Client(_Resp('""'), _Resp(_GP_CSV), _Resp(_HISTORY_CSV))
    dl = SpaceTrackDownloader(client)  # type: ignore[arg-type]
    dl.MAX_BACKFILL_WEEKS_PER_RUN = 2

    # today = Mon 2026-02-02 → completed weeks: Jan 5, 12, 19, 26. Jan 12 already
    # holds all seven days, so it is not revisited.
    seeded = _seed_week(out_dir, date(2026, 1, 12), "seeded", offsets=list(range(7)))

    fetched, remaining = dl._backfill_weeks(date(2026, 2, 2))

    assert (fetched, remaining) == (2, 1)
    assert len(client.history_urls) == 14  # 2 weeks × 7 days
    assert (out_dir / "2026" / "01" / "05" / "gp-active.csv").exists()
    assert (out_dir / "2026" / "01" / "19" / "gp-active.csv").exists()
    assert not (out_dir / "2026" / "01" / "26" / "gp-active.csv").exists()  # deferred
    assert (seeded / "gp-active.csv").read_text() == "seeded"  # untouched


def test_daily_snapshot_is_not_treated_as_a_partial_week(out_dir):
    """A daily gp pull landing on a Monday must not be topped up as a weekly."""
    client = _Client(_Resp('""'), _Resp(_GP_CSV), _Resp(_HISTORY_CSV))
    dl = SpaceTrackDownloader(client)  # type: ignore[arg-type]
    monday = date(2026, 1, 5)
    day_dir = _seed_week(out_dir, monday, _GP_CSV)
    (day_dir / _DAYS_SIDECAR).write_text(json.dumps({"daily": True}))

    assert dl._covered_offsets(monday) == frozenset(range(7))
    assert monday not in dl._incomplete_weeks(date(2026, 1, 26))


def test_fetch_current_marks_its_snapshot_daily(out_dir):
    client = _Client(_Resp('""'), _Resp(_GP_CSV))
    dl = SpaceTrackDownloader(client)  # type: ignore[arg-type]
    dl.MAX_BACKFILL_WEEKS_PER_RUN = 0
    dl.download()

    today = datetime.now(timezone.utc).date()
    day_dir = out_dir / f"{today.year:04d}" / f"{today.month:02d}" / f"{today.day:02d}"
    assert json.loads((day_dir / _DAYS_SIDECAR).read_text()) == {"daily": True}
