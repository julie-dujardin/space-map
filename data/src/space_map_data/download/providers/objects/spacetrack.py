"""Download GP/TLE elements from Space-Track.

Two products land under a day-tiered tree mirroring the CelesTrak layout, so the
export overlay and ingest catalogue consume them unchanged:

* a daily ``gp`` snapshot (latest element set for every on-orbit object) under
  today's date — the freshest catalogue;
* weekly snapshots for the completed Mondays of the current year, matching the
  historical archive's cadence (one element per satellite, nearest the week's
  midpoint). Each is built from a single-day ``gp_history`` pull around the
  midpoint, then a targeted follow-up over the rest of the week for any live
  satellite the midpoint day missed — so every still-on-orbit object that had a
  TLE that week gets one. These bridge the gap between the archive (which ends
  with the prior year) and today.

Credentials come from the environment (``SPACETRACK_IDENTITY`` /
``SPACETRACK_PASSWORD``); the API rejects anonymous access and throttles
``gp_history`` hard, so every history request is paced and the backfill is
capped per run.
"""

import csv
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
# Same class bounded by a comma-delimited NORAD list — the follow-up that fills
# sats the bulk days missed. Bounding by NORAD keeps the response small so a
# wider EPOCH window is safe (catches rarely-updated objects), but the list goes
# in the URL, so it must stay short — a long list trips Space-Track's edge with a
# 403. Hence the small chunk size below.
GP_HISTORY_LIST_QUERY = (
    "https://www.space-track.org/basicspacedata/query/class/gp_history"
    "/NORAD_CAT_ID/{norads}/epoch/{start}--{end}/format/csv"
)

# Week midpoint, in days from the week's Monday 00:00 UTC — the archive anchors
# each weekly snapshot here (Thursday 12:00), and we keep the element nearest it.
_WEEK_MIDPOINT_DAYS = 3.5
# Full-catalogue days to pull per week (offsets from Monday), spread across the
# midweek so a sat updated on any of them is covered. A single day misses
# 15–30% of the catalogue; three spread days knock that to ~8% before the
# follow-up runs.
_BULK_DAY_OFFSETS = (1, 3, 5)  # Tue / Thu / Sat
# Follow-up search half-window (days each side of the midpoint) and how many
# NORADs per follow-up query (small — the list is in the URL).
_FOLLOWUP_HALF_WINDOW_DAYS = 7
_FOLLOWUP_CHUNK = 200


class SpaceTrackDownloader(Downloader):
    name = PROVIDERS.SPACETRACK

    # Space-Track caps gp_history at 10 pulls / 15 min (and 30/min, 300/hr
    # overall). A week costs several requests (one bulk day + follow-up chunks),
    # so spend >=100s between every history request — 10 per 15 min exactly — and
    # backfill few weeks per run.
    MAX_BACKFILL_WEEKS_PER_RUN = 3
    HISTORY_DELAY_S = 100.0

    def __init__(self, client: httpx.Client) -> None:
        self.client = client
        self.out_dir = SOURCES_POSITION_DIR / "spacetrack" / "current"
        self.out_dir.mkdir(parents=True, exist_ok=True)
        self._history_requests = 0  # paces every gp_history call within a run

    def _day_dir(self, day: date) -> Path:
        return self.out_dir / f"{day.year:04d}" / f"{day.month:02d}" / f"{day.day:02d}"

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
        fetched, remaining = self._backfill_weeks(today, self._load_live_launch(today))
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
        record_count = body.count("\n") - 1
        logger.info(
            "Saved %s GP records -> %s",
            f"{record_count:,}",
            out_file.relative_to(self.out_dir),
        )
        return record_count

    def _missing_weeks(self, today: date) -> list[date]:
        """Completed Mondays of the current year with no snapshot yet, oldest first."""
        return [
            m
            for m in _completed_year_mondays(today)
            if not (self._day_dir(m) / "gp-active.csv").exists()
        ]

    def _load_live_launch(self, today: date) -> dict[str, str]:
        """Map ``NORAD -> LAUNCH_DATE`` from today's live catalogue.

        The set of currently-on-orbit objects is the "should be up" reference for
        the weekly follow-up; the launch date lets us skip a sat for weeks before
        it existed.
        """
        daily = self._day_dir(today) / "gp-active.csv"
        if not daily.exists():
            return {}
        with open(daily, newline="") as f:
            return {
                r["NORAD_CAT_ID"]: r.get("LAUNCH_DATE") or ""
                for r in csv.DictReader(f)
                if r.get("NORAD_CAT_ID")
            }

    def _backfill_weeks(
        self, today: date, live_launch: dict[str, str]
    ) -> tuple[int, int]:
        """Fetch missing weekly snapshots for the current year, oldest first.

        Returns ``(fetched_this_run, still_missing_after_run)``. Capped per run;
        stops at the first failure (the rest retry on a later run) rather than
        hammering the API once it starts rejecting us.
        """
        missing = self._missing_weeks(today)
        if not missing:
            return 0, 0

        logger.info("Weekly backfill: %d week(s) missing", len(missing))
        self._history_requests = 0
        fetched = 0
        for monday in missing[: self.MAX_BACKFILL_WEEKS_PER_RUN]:
            try:
                self._fetch_week(monday, live_launch)
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

    def _fetch_week(self, monday: date, live_launch: dict[str, str]) -> None:
        """Reconstruct one weekly snapshot, anchored on the week's midpoint.

        A few full-catalogue days cover most of the catalogue; a follow-up then
        fetches every still-on-orbit sat (launched by then) the days missed, over
        a wider window. Each satellite keeps the row nearest the midpoint, written
        to a ``gp-active.csv`` under the Monday's date.
        """
        midnight = datetime(monday.year, monday.month, monday.day, tzinfo=timezone.utc)
        midpoint = midnight + timedelta(days=_WEEK_MIDPOINT_DAYS)

        # 1. Bulk: a few full-catalogue days (no NORAD list -> no URL limit).
        best: dict[str, tuple[float, str]] = {}
        header = ""
        for off in _BULK_DAY_OFFSETS:
            body = self._history_get(
                GP_HISTORY_QUERY.format(
                    start=(monday + timedelta(days=off)).isoformat(),
                    end=(monday + timedelta(days=off + 1)).isoformat(),
                ),
                f"{monday} day+{off}",
            )
            header = self._merge_nearest(body, midpoint, best)
        from_bulk = len(best)

        # 2. Follow-up: chase live sats the bulk days missed, in short URL-safe
        #    chunks over a wider window.
        expected = {
            n for n, launch in live_launch.items() if _launched_by(launch, midpoint)
        }
        missing = sorted(expected - set(best), key=lambda n: int(n))
        lo = (midpoint - timedelta(days=_FOLLOWUP_HALF_WINDOW_DAYS)).date()
        hi = (midpoint + timedelta(days=_FOLLOWUP_HALF_WINDOW_DAYS)).date()
        for i in range(0, len(missing), _FOLLOWUP_CHUNK):
            chunk = missing[i : i + _FOLLOWUP_CHUNK]
            body = self._history_get(
                GP_HISTORY_LIST_QUERY.format(
                    norads=",".join(chunk), start=lo.isoformat(), end=hi.isoformat()
                ),
                f"{monday} follow-up {i // _FOLLOWUP_CHUNK + 1}",
            )
            self._merge_nearest(body, midpoint, best)

        day_dir = self._day_dir(monday)
        day_dir.mkdir(parents=True, exist_ok=True)
        rows = [entry[1] for entry in best.values()]
        (day_dir / "gp-active.csv").write_text("\n".join([header, *rows]) + "\n")
        logger.info(
            "Week %s: %d satellites (%d from %d bulk days, %d filled, %d still missing)",
            monday.isoformat(),
            len(best),
            from_bulk,
            len(_BULK_DAY_OFFSETS),
            len(best) - from_bulk,
            len(expected - best.keys()),
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
            except (ValueError, IndexError):
                continue
            if epoch.tzinfo is None:
                epoch = epoch.replace(tzinfo=timezone.utc)
            dist = abs((epoch - midpoint).total_seconds())
            norad = fields[norad_i]
            current = best.get(norad)
            if current is None or dist < current[0]:
                best[norad] = (dist, line)
        return header


def _launched_by(launch: str, midpoint: datetime) -> bool:
    """Whether a satellite existed by the week's midpoint (unknown date → yes)."""
    if not launch:
        return True
    try:
        return date.fromisoformat(launch) <= midpoint.date()
    except ValueError:
        return True


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
