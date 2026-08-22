"""Download GP/TLE elements from Space-Track.

Two products land under a day-tiered tree mirroring the CelesTrak layout, so the
export overlay and ingest catalogue consume them unchanged:

* a daily ``gp`` snapshot (latest element set for every on-orbit object) under
  today's date — the freshest catalogue;
* weekly snapshots for the completed Mondays of the current year, matching the
  historical archive's cadence (one element per satellite, nearest the week's
  midpoint). Each is built from seven full-catalogue ``gp_history`` day pulls,
  one per day of the week, which captures every object that got a TLE that week.
  A snapshot left by an earlier, narrower scheme is topped up with just the days
  it lacks rather than re-pulled. These bridge the gap between the archive
  (which ends with the prior year) and today.

Objects that got no TLE at all in a week (~2-5%, more when tracking gaps) are
not chased with extra queries — the export fills them from neighbouring weekly
snapshots instead, which costs nothing because every week is pulled anyway. See
``export.position.elements.celestrak_source.fill_gaps``.

Credentials come from the environment (``SPACETRACK_IDENTITY`` /
``SPACETRACK_PASSWORD``); the API rejects anonymous access and throttles
``gp_history`` hard, so every history request is paced.
"""

import csv
import json
import logging
import os
import time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import httpx

from space_map_data.constants.providers import PROVIDERS
from space_map_data.download.downloader import DownloadError, Downloader
from space_map_data.utils.paths import SOURCES_POSITION_DIR

logger = logging.getLogger(__name__)

LOGIN_URL = "https://www.space-track.org/ajaxauth/login"
# Latest element set for every non-decayed object updated in the last 30 days —
# the active on-orbit catalogue, matching CelesTrak's GROUP=active but complete.
GP_QUERY = (
    "https://www.space-track.org/basicspacedata/query/class/gp"
    "/decay_date/null-val/epoch/%3Enow-30/orderby/NORAD_CAT_ID%20asc/format/csv"
)
# One full-catalogue day of historical element sets. No decay_date filter (a sat
# on-orbit then but since decayed must still appear) and no orderby (sorting a
# slice of the 220M-row class server-side 500s; we pick the nearest epoch in
# memory). One day at a time on purpose: a single day is ~60 MB and returns fine,
# whereas a multi-day window exceeds Space-Track's response-size cap and 500s.
GP_HISTORY_QUERY = (
    "https://www.space-track.org/basicspacedata/query/class/gp_history"
    "/epoch/{start}--{end}/format/csv"
)
# Week midpoint, in days from the week's Monday 00:00 UTC — the archive anchors
# each weekly snapshot here (Thursday 12:00), and we keep the element nearest it.
_WEEK_MIDPOINT_DAYS = 3.5
# Every day of the week, so the snapshot holds every object that got a TLE at
# all that week. Measured against the 2025 archive: one day alone reaches
# 82-88% of the week's objects, three spread days 95.6%, all seven 100%.
_WEEK_DAYS = 7
# Records how a stored snapshot was built, so a week is topped up rather than
# re-pulled. It cannot be recovered from the CSV: the nearest-midpoint merge
# discards the losing rows, so a fetched day can leave no trace. Daily snapshots
# are marked as such — one landing on a Monday would otherwise look like a
# weekly that is short a few days.
_DAYS_SIDECAR = "gp-active.days.json"
# What a snapshot written before the sidecar holds. Those runs pulled Tue/Thu/Sat
# plus a NORAD-bounded follow-up over the midpoint +-7 days; the follow-up rows
# are kept (they cover satellites no bulk day had), so only the four untouched
# days are still owed.
_LEGACY_DAY_OFFSETS = frozenset({1, 3, 5})
_ALL_DAY_OFFSETS = frozenset(range(_WEEK_DAYS))


class SpaceTrackDownloader(Downloader):
    name = PROVIDERS.SPACETRACK

    # Space-Track caps gp_history at 10 pulls / 15 min (and 30/min, 300/hr
    # overall). 100s between requests holds us to 9 per 15 min whatever the run
    # length, so the per-run cap only bounds wall-clock: 7 requests a week means
    # a 6-week run takes ~70 min.
    MAX_BACKFILL_WEEKS_PER_RUN = 6
    HISTORY_DELAY_S = 100.0

    def __init__(self, client: httpx.Client) -> None:
        self.client = client
        self.out_dir = SOURCES_POSITION_DIR / "spacetrack" / "current"
        self.out_dir.mkdir(parents=True, exist_ok=True)
        self._history_requests = 0  # paces every gp_history call within a run

    def _day_dir(self, day: date) -> Path:
        return self.out_dir / f"{day.year:04d}" / f"{day.month:02d}" / f"{day.day:02d}"

    def _covered_offsets(self, monday: date) -> frozenset[int]:
        """Day offsets the stored snapshot for ``monday`` was built from.

        Empty when no snapshot exists. Snapshots written before the sidecar
        report :data:`_LEGACY_DAY_OFFSETS`.
        """
        day_dir = self._day_dir(monday)
        if not (day_dir / "gp-active.csv").exists():
            return frozenset()
        sidecar = day_dir / _DAYS_SIDECAR
        if sidecar.exists():
            meta = json.loads(sidecar.read_text())
            if meta.get("daily"):
                return _ALL_DAY_OFFSETS  # the live catalogue, not a week to fill
            return frozenset(meta["day_offsets"])
        return _LEGACY_DAY_OFFSETS

    def _login(self) -> None:
        identity = os.environ.get("SPACETRACK_IDENTITY")
        password = os.environ.get("SPACETRACK_PASSWORD")
        if not identity or not password:
            raise DownloadError(
                "SPACETRACK_IDENTITY/SPACETRACK_PASSWORD not set — cannot "
                "authenticate to Space-Track"
            )
        logger.info("Authenticating to Space-Track as %s...", identity)
        resp = self.client.post(
            LOGIN_URL, data={"identity": identity, "password": password}
        )
        resp.raise_for_status()
        # Success returns an empty-string body (``""``); a failure returns a
        # non-empty ``{"Login":"Failed"}``-style payload.
        if resp.text.strip().strip('"'):
            raise DownloadError(f"Space-Track login failed: {resp.text[:120]!r}")

    def download(self, limit: int | None = None, **kwargs: object) -> None:
        self._login()
        today = datetime.now(timezone.utc).date()
        # Skip the daily fetch if today's snapshot is already down (e.g. a re-run
        # to continue the weekly backfill); the catalogue only changes once a day.
        daily_file = self._day_dir(today) / "gp-active.csv"
        if daily_file.exists():
            logger.info("Today's GP snapshot already present, skipping daily fetch")
            record_count = daily_file.read_text().count("\n") - 1
        else:
            record_count = self._fetch_current(today)
        fetched, remaining = self._backfill_weeks(today)
        # No ``complete`` flag — ``is_complete`` is file-based.
        self._save_metadata(
            GP_QUERY,
            record_count,
            day=today.isoformat(),
            weeks_fetched=fetched,
            weeks_remaining=remaining,
        )

    def _fetch_current(self, today: date) -> int:
        """Fetch today's live GP catalogue; return the record count."""
        logger.info("Downloading Space-Track GP catalogue...")
        resp = self.client.get(GP_QUERY)
        resp.raise_for_status()
        body = resp.text
        # The OMM CSV header leads with metadata columns; NORAD_CAT_ID is always
        # in it. Anything else (login HTML, JSON error) means the query failed.
        if "NORAD_CAT_ID" not in body[:2000]:
            raise DownloadError(f"Unexpected GP response: {body[:120]!r}")

        day_dir = self._day_dir(today)
        day_dir.mkdir(parents=True, exist_ok=True)
        out_file = day_dir / "gp-active.csv"
        out_file.write_text(body)
        (day_dir / _DAYS_SIDECAR).write_text(json.dumps({"daily": True}))
        record_count = body.count("\n") - 1
        logger.info(
            "Saved %s GP records -> %s",
            f"{record_count:,}",
            out_file.relative_to(self.out_dir),
        )
        return record_count

    def _incomplete_weeks(self, today: date) -> list[date]:
        """Completed Mondays of the current year still owed days, oldest first.

        Covers weeks with no snapshot at all and weeks built from a subset of
        the seven days, which are topped up in place.
        """
        return [
            m
            for m in _completed_year_mondays(today)
            if len(self._covered_offsets(m)) < _WEEK_DAYS
        ]

    def _backfill_weeks(self, today: date) -> tuple[int, int]:
        """Fetch missing weekly snapshots for the current year, oldest first.

        Returns ``(fetched_this_run, still_missing_after_run)``. Capped per run;
        stops at the first failure (the rest retry on a later run) rather than
        hammering the API once it starts rejecting us.
        """
        missing = self._incomplete_weeks(today)
        if not missing:
            return 0, 0

        logger.info("Weekly backfill: %d week(s) incomplete", len(missing))
        self._history_requests = 0
        fetched = 0
        for monday in missing[: self.MAX_BACKFILL_WEEKS_PER_RUN]:
            try:
                self._fetch_week(monday)
            except Exception:
                logger.exception(
                    "Weekly snapshot for %s failed; stopping backfill",
                    monday.isoformat(),
                )
                break
            fetched += 1
        return fetched, len(missing) - fetched

    def _history_get(self, url: str, label: str) -> str:
        """Throttled gp_history GET; returns the CSV body or raises on a bad reply."""
        if self._history_requests:
            time.sleep(self.HISTORY_DELAY_S)
        self._history_requests += 1
        resp = self.client.get(url)
        body = resp.text
        # Surface Space-Track's own error text (it explains rejected queries even
        # on a 500) rather than the opaque raise_for_status message.
        if resp.status_code != 200 or "NORAD_CAT_ID" not in body[:2000]:
            raise DownloadError(
                f"gp_history {label} -> HTTP {resp.status_code}: {body[:200]!r}"
            )
        return body

    def _fetch_week(self, monday: date) -> None:
        """Build or top up one weekly snapshot, anchored on the week's midpoint.

        Pulls the days of the week the stored snapshot does not already hold, so
        a week built by an earlier, narrower scheme costs only the days it
        missed. Existing rows are merged back in first and compete on the same
        nearest-the-midpoint rule, so a better row replaces them and a row no
        fetched day can supply survives. The result is written to a
        ``gp-active.csv`` under the Monday's date, with a sidecar recording the
        days it now covers. Objects with no TLE that week are left out; the
        export fills them from neighbouring weeks.
        """
        midnight = datetime(monday.year, monday.month, monday.day, tzinfo=timezone.utc)
        midpoint = midnight + timedelta(days=_WEEK_MIDPOINT_DAYS)
        day_dir = self._day_dir(monday)
        out_file = day_dir / "gp-active.csv"

        best: dict[str, tuple[float, str]] = {}
        header = ""
        covered = self._covered_offsets(monday)
        if covered:
            header = self._merge_nearest(out_file.read_text(), midpoint, best)
            logger.info(
                "Week %s: topping up %d stored satellites, %d day(s) still owed",
                monday.isoformat(),
                len(best),
                _WEEK_DAYS - len(covered),
            )
        for off in range(_WEEK_DAYS):
            if off in covered:
                continue
            body = self._history_get(
                GP_HISTORY_QUERY.format(
                    start=(monday + timedelta(days=off)).isoformat(),
                    end=(monday + timedelta(days=off + 1)).isoformat(),
                ),
                f"{monday} day+{off}",
            )
            header = self._merge_nearest(body, midpoint, best)

        day_dir.mkdir(parents=True, exist_ok=True)
        rows = [entry[1] for entry in best.values()]
        out_file.write_text("\n".join([header, *rows]) + "\n")
        (day_dir / _DAYS_SIDECAR).write_text(
            json.dumps({"day_offsets": sorted(_ALL_DAY_OFFSETS)})
        )
        logger.info(
            "Week %s: %d satellites across %d days",
            monday.isoformat(),
            len(best),
            _WEEK_DAYS,
        )

    @staticmethod
    def _merge_nearest(
        body: str, midpoint: datetime, best: dict[str, tuple[float, str]]
    ) -> str:
        """Merge rows into ``best``, keeping the one nearest ``midpoint`` per NORAD.

        Returns the CSV header line (callers reuse the first pull's header).
        """
        lines = body.splitlines()
        header = lines[0]
        cols = next(csv.reader([header]))
        epoch_i = cols.index("EPOCH")
        norad_i = cols.index("NORAD_CAT_ID")
        for line in lines[1:]:
            if not line.strip():
                continue
            fields = next(csv.reader([line]))
            try:
                epoch = datetime.fromisoformat(fields[epoch_i])
            except ValueError, IndexError:
                continue
            if epoch.tzinfo is None:
                epoch = epoch.replace(tzinfo=timezone.utc)
            dist = abs((epoch - midpoint).total_seconds())
            norad = fields[norad_i]
            current = best.get(norad)
            if current is None or dist < current[0]:
                best[norad] = (dist, line)
        return header


def _completed_year_mondays(today: date) -> list[date]:
    """Mondays of ``today``'s year whose week has fully elapsed, oldest first."""
    first = date(today.year, 1, 1)
    first += timedelta(days=(7 - first.weekday()) % 7)  # first Monday on/after Jan 1
    out: list[date] = []
    monday = first
    while monday.year == today.year and monday + timedelta(days=7) <= today:
        out.append(monday)
        monday += timedelta(days=7)
    return out
