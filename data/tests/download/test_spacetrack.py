"""Unit tests for the Space-Track GP downloader."""

from datetime import date, datetime, timezone

import httpx
import pytest

from space_map_data.download.downloader import DownloadError
from space_map_data.download.providers.objects import spacetrack
from space_map_data.download.providers.objects.spacetrack import (
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
# A NORAD-list follow-up reply carrying a sat the bulk day missed.
_FOLLOWUP_CSV = _GP_HEADER + "\r\n" + _row("SAT42", "2026-01-08T10:00:00", 42) + "\r\n"


class _Resp:
    def __init__(self, text: str = "", status_code: int = 200) -> None:
        self.text = text
        self.status_code = status_code

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise httpx.HTTPStatusError("err", request=None, response=None)  # type: ignore[arg-type]


class _Client:
    """httpx.Client stand-in that routes gp / gp_history / follow-up and records URLs."""

    def __init__(
        self,
        login: _Resp,
        gp: _Resp,
        history: _Resp | None = None,
        followup: _Resp | None = None,
    ) -> None:
        self._login, self._gp, self._history = login, gp, history
        self._followup = followup
        self.gp_url: str | None = None
        self.history_urls: list[str] = []

    def post(self, url: str, data: dict) -> _Resp:
        return self._login

    def get(self, url: str) -> _Resp:
        if "gp_history" in url:
            self.history_urls.append(url)
            if "NORAD_CAT_ID/" in url:  # follow-up (NORAD-bounded) query
                return self._followup or _Resp(_FOLLOWUP_CSV)
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
    # First Monday of 2026 is Jan 5. With today = Jan 20, weeks of Jan 5 and
    # Jan 12 have fully elapsed (Mon+7 <= today); Jan 19's has not.
    assert _completed_year_mondays(date(2026, 1, 20)) == [
        date(2026, 1, 5),
        date(2026, 1, 12),
    ]
    # Nothing completed yet in the first days of the year.
    assert _completed_year_mondays(date(2026, 1, 3)) == []


def test_fetch_week_keeps_row_nearest_midpoint(out_dir):
    client = _Client(_Resp('""'), _Resp(_GP_CSV), _Resp(_HISTORY_CSV))
    dl = SpaceTrackDownloader(client)  # type: ignore[arg-type]
    # Both live sats are covered by the bulk days → no follow-up.
    dl._fetch_week(date(2026, 1, 5), {"5": "", "11": ""})

    written = (out_dir / "2026" / "01" / "05" / "gp-active.csv").read_text()
    assert "SAT5-NEAR" in written and "SAT5-FAR" not in written  # nearest midpoint wins
    assert "SAT11" in written
    # Three full-catalogue bulk days (Tue/Thu/Sat), no NORAD-bounded follow-up.
    assert len(client.history_urls) == 3
    assert all("epoch/" in u and "NORAD_CAT_ID/" not in u for u in client.history_urls)


def test_fetch_week_follows_up_missing_sats(out_dir):
    client = _Client(
        _Resp('""'), _Resp(_GP_CSV), _Resp(_HISTORY_CSV), _Resp(_FOLLOWUP_CSV)
    )
    dl = SpaceTrackDownloader(client)  # type: ignore[arg-type]
    # NORAD 42 is on-orbit (launched long ago) but absent from the bulk days.
    dl._fetch_week(date(2026, 1, 5), {"5": "", "11": "", "42": "2000-01-01"})

    written = (out_dir / "2026" / "01" / "05" / "gp-active.csv").read_text()
    assert "SAT42" in written  # filled by the follow-up
    assert len(client.history_urls) == 4  # three bulk days + one follow-up chunk
    # Follow-up is NORAD-bounded over the wider ±7-day window.
    assert "NORAD_CAT_ID/42/epoch/2026-01-01--2026-01-15" in client.history_urls[-1]


def test_fetch_week_skips_not_yet_launched(out_dir):
    client = _Client(_Resp('""'), _Resp(_GP_CSV), _Resp(_HISTORY_CSV))
    dl = SpaceTrackDownloader(client)  # type: ignore[arg-type]
    # NORAD 42 launches after the week → not chased, so no follow-up request.
    dl._fetch_week(date(2026, 1, 5), {"5": "", "42": "2026-03-01"})
    assert len(client.history_urls) == 3  # bulk days only


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
        dl._fetch_week(date(2026, 1, 5), {})


def test_backfill_stops_on_first_error(out_dir):
    client = _Client(_Resp('""'), _Resp(_GP_CSV), _Resp("", 500))
    dl = SpaceTrackDownloader(client)  # type: ignore[arg-type]
    # today = Mon 2026-02-02 → 4 completed weeks, all missing.
    fetched, remaining = dl._backfill_weeks(date(2026, 2, 2), {})
    assert (fetched, remaining) == (0, 4)
    assert len(client.history_urls) == 1  # bailed after the first failure


def test_backfill_caps_and_skips_existing(out_dir):
    client = _Client(_Resp('""'), _Resp(_GP_CSV), _Resp(_HISTORY_CSV))
    dl = SpaceTrackDownloader(client)  # type: ignore[arg-type]
    dl.MAX_BACKFILL_WEEKS_PER_RUN = 2

    # today = Mon 2026-02-02 → completed weeks: Jan 5, 12, 19, 26. Pre-seed Jan 12.
    seeded = out_dir / "2026" / "01" / "12"
    seeded.mkdir(parents=True)
    (seeded / "gp-active.csv").write_text("seeded")

    fetched, remaining = dl._backfill_weeks(date(2026, 2, 2), {})

    assert (fetched, remaining) == (2, 1)
    assert len(client.history_urls) == 6  # 2 weeks × 3 bulk days, no follow-up
    assert (out_dir / "2026" / "01" / "05" / "gp-active.csv").exists()
    assert (out_dir / "2026" / "01" / "19" / "gp-active.csv").exists()
    assert not (out_dir / "2026" / "01" / "26" / "gp-active.csv").exists()  # deferred
    assert (seeded / "gp-active.csv").read_text() == "seeded"  # untouched
