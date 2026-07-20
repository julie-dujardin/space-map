"""SBDB small-body catalog mirror with incremental sync.

The catalog lives in ``sbdb.sqlite``, keyed by spkid. The first run pages
through the full database; later runs fetch only records whose orbit
solution changed (``soln_date``) and reconcile against the remote spkid
list to pick up deletions (merged designations) and spkid migrations
(unnumbered -> numbered).

Physical-parameter edits that don't bump ``soln_date`` are only picked up
by a full resync: delete ``sbdb.sqlite`` (and ``fields.json`` to refresh
the schema) and re-run.
"""

import json
import logging
import sqlite3
import time
from bisect import bisect_left, bisect_right
from datetime import date, datetime, timedelta, timezone

import httpx
from tqdm import tqdm

from space_map_data.constants.providers import PROVIDERS
from space_map_data.download.downloader import Downloader
from space_map_data.utils.paths import SOURCES_POSITION_DIR

logger = logging.getLogger(__name__)

URL = "https://ssd-api.jpl.nasa.gov/sbdb_query.api"
PAGE_SIZE = 5000
PAGE_SLEEP = 5
# Delta lower bound overlaps the last sync: soln_date filters are date-only
# (the API rejects time components) and upserts make the overlap free.
DELTA_OVERLAP_DAYS = 2
# Above this, delta pagination (which degrades badly at deep offsets on
# filtered queries) is slower than an unfiltered full resync.
DELTA_FULL_RESYNC_THRESHOLD = 200_000
# Minimum age of the last successful sync before another one runs.
FRESHNESS = timedelta(days=1)


class SBDBDownloader(Downloader):
    name = PROVIDERS.SBDB

    def __init__(self, client: httpx.Client) -> None:
        self.client = client
        self.out_dir = SOURCES_POSITION_DIR / "sbdb"
        self.out_dir.mkdir(parents=True, exist_ok=True)

    @property
    def db_file(self):
        return self.out_dir / "sbdb.sqlite"

    @property
    def _fields_file(self):
        return self.out_dir / "fields.json"

    # --- fields ---------------------------------------------------------

    def _fetch_all_fields(self) -> dict:
        """Discover all available field names via the info endpoint."""
        response = self.client.get(URL, params={"info": "field"})
        response.raise_for_status()
        return response.json()["info"]["field"]

    def _get_fields(self) -> list[str]:
        """Load cached fields from disk or fetch and save them."""
        fields = None
        if self._fields_file.exists():
            fields = json.loads(self._fields_file.read_text())
            logger.info("Loaded %d fields from %s", len(fields), self._fields_file.name)
        else:
            fields = self._fetch_all_fields()
            self._fields_file.write_text(json.dumps(fields, indent=4))
            logger.info("Fetched and saved %d fields", len(fields))
        return [f["name"] for cat in fields.values() for f in cat["list"]]

    # --- sqlite ---------------------------------------------------------

    def _ensure_schema(self, con: sqlite3.Connection, fields: list[str]) -> None:
        """Create tables; drop a ``bodies`` table whose columns don't match
        the current field list (forces a full resync)."""
        con.execute(
            "CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT)"
        )
        existing = [r[1] for r in con.execute("PRAGMA table_info(bodies)")]
        if existing and existing != fields:
            logger.warning(
                "SBDB mirror schema mismatch (%d cols on disk, %d expected), rebuilding",
                len(existing),
                len(fields),
            )
            con.execute("DROP TABLE bodies")
            con.execute("DELETE FROM meta")
            existing = []
        if not existing:
            cols = ", ".join(
                f'"{c}" INTEGER PRIMARY KEY' if c == "spkid" else f'"{c}" TEXT'
                for c in fields
            )
            con.execute(f"CREATE TABLE bodies ({cols})")
        con.commit()

    @staticmethod
    def _meta_get(con: sqlite3.Connection, key: str) -> str | None:
        row = con.execute("SELECT value FROM meta WHERE key = ?", (key,)).fetchone()
        return row[0] if row else None

    @staticmethod
    def _meta_set(con: sqlite3.Connection, key: str, value: str | None) -> None:
        if value is None:
            con.execute("DELETE FROM meta WHERE key = ?", (key,))
        else:
            con.execute(
                "INSERT OR REPLACE INTO meta (key, value) VALUES (?, ?)", (key, value)
            )

    @staticmethod
    def _upsert(con: sqlite3.Connection, fields: list[str], rows: list[list]) -> None:
        cols = ", ".join(f'"{c}"' for c in fields)
        placeholders = ", ".join(["?"] * len(fields))
        con.executemany(
            f"INSERT OR REPLACE INTO bodies ({cols}) VALUES ({placeholders})", rows
        )

    # --- fetching -------------------------------------------------------

    def _sync_pages(
        self,
        con: sqlite3.Connection,
        fields: list[str],
        cdata: str | None,
        *,
        start_offset: int = 0,
        limit: int | None = None,
        desc: str,
        on_page=None,
    ) -> tuple[int, bool, int]:
        """Page through a query, upserting each page into ``bodies``.

        Returns ``(written, finished, remote_count)``; ``finished`` is False
        when the row cap stopped the fetch early. ``limit`` caps
        ``start_offset + written`` to mirror the CLI's record limit.
        """
        params_base = {"fields": ",".join(fields), "full-prec": "true"}
        if cdata is not None:
            params_base["sb-cdata"] = cdata
        written = 0
        offset = start_offset
        total = 0
        bar = tqdm(
            total=None, unit="obj", desc=desc, dynamic_ncols=True, initial=start_offset
        )
        try:
            while True:
                remaining = None if limit is None else limit - offset
                if remaining is not None and remaining <= 0:
                    return written, False, total
                page_limit = (
                    PAGE_SIZE if remaining is None else min(PAGE_SIZE, remaining)
                )
                response = self.client.get(
                    URL,
                    params={
                        **params_base,
                        "limit": page_limit,
                        "limit-from": offset,
                    },
                )
                response.raise_for_status()
                payload = response.json()

                if bar.total is None:
                    total = payload["count"]
                    bar.total = min(total, limit) if limit is not None else total
                    bar.refresh()

                rows = payload.get("data") or []
                if rows:
                    self._upsert(con, fields, rows)
                    written += len(rows)
                    offset += len(rows)
                    bar.update(len(rows))
                if on_page is not None:
                    on_page(con, offset)
                con.commit()

                if len(rows) < page_limit:
                    return written, True, total
                time.sleep(PAGE_SLEEP)
        finally:
            bar.close()

    def _full_sync(
        self, con: sqlite3.Connection, fields: list[str], limit: int | None
    ) -> tuple[int, bool]:
        """Build (or resume) the full mirror. Returns (changed, finished)."""
        offset = int(self._meta_get(con, "full_sync_offset") or "0")
        if offset:
            logger.info("Resuming full SBDB sync from offset %d", offset)

        # A resume offset goes stale as records shift between runs (objects
        # get numbered and move within the sort order); the reconciliation
        # below heals anything skipped or duplicated.
        written, finished, _ = self._sync_pages(
            con,
            fields,
            None,
            start_offset=offset,
            limit=limit,
            desc="SBDB full sync",
            on_page=lambda c, off: self._meta_set(c, "full_sync_offset", str(off)),
        )
        if not finished:
            return written, False

        # Also purges stale rows when resyncing over an existing mirror.
        deleted, fetched, reconciled = self._reconcile(
            con, fields, None if limit is None else limit - written
        )
        if reconciled:
            self._meta_set(con, "full_sync_offset", None)
            self._meta_set(con, "last_sync", self._today())
            con.commit()
        return written + deleted + fetched, reconciled

    def _delta_sync(
        self, con: sqlite3.Connection, fields: list[str], limit: int | None
    ) -> tuple[int, bool]:
        """Fetch records re-fit since the last sync, then reconcile.

        Returns (changed_rows, finished).
        """
        last_sync = self._meta_get(con, "last_sync")
        assert last_sync is not None
        since = date.fromisoformat(last_sync) - timedelta(days=DELTA_OVERLAP_DAYS)
        cdata = json.dumps({"AND": [f"soln_date|GE|{since.isoformat()}"]})

        count = self._count(cdata)
        if count > DELTA_FULL_RESYNC_THRESHOLD:
            logger.info(
                "SBDB delta since %s spans %d records, falling back to full resync",
                since.isoformat(),
                count,
            )
            self._meta_set(con, "last_sync", None)
            self._meta_set(con, "full_sync_offset", None)
            con.commit()
            return self._full_sync(con, fields, limit)

        written, finished, total = self._sync_pages(
            con, fields, cdata, limit=limit, desc=f"SBDB delta ({since.isoformat()})"
        )
        if not finished:
            logger.warning(
                "SBDB delta stopped by record limit (%d of %d fetched)", written, total
            )
            return written, False

        deleted, fetched, reconciled = self._reconcile(
            con, fields, None if limit is None else limit - written
        )
        if reconciled:
            self._meta_set(con, "last_sync", self._today())
            con.commit()
        return written + deleted + fetched, reconciled

    def _count(self, cdata: str) -> int:
        """Number of remote records matching a constraint."""
        response = self.client.get(
            URL, params={"fields": "spkid", "sb-cdata": cdata, "limit": 1}
        )
        response.raise_for_status()
        return response.json()["count"]

    def _remote_spkids(self) -> list[int]:
        """The full remote spkid list, unpaginated (~17 MB of JSON)."""
        response = self.client.get(URL, params={"fields": "spkid"})
        response.raise_for_status()
        return [int(r[0]) for r in response.json()["data"]]

    def _reconcile(
        self, con: sqlite3.Connection, fields: list[str], limit: int | None
    ) -> tuple[int, int, bool]:
        """Diff local spkids against the remote list: delete records JPL
        removed (merges, migrations) and fetch records the delta missed.

        Returns (deleted, fetched, finished).
        """
        remote_sorted = sorted(self._remote_spkids())
        remote = set(remote_sorted)
        local = {r[0] for r in con.execute("SELECT spkid FROM bodies")}

        stale = local - remote
        if stale:
            logger.info("Deleting %d records no longer in SBDB", len(stale))
            con.executemany("DELETE FROM bodies WHERE spkid = ?", [(s,) for s in stale])
            con.commit()

        missing = sorted(remote - local)
        if not missing:
            return len(stale), 0, True

        logger.info("Fetching %d records missed by the delta", len(missing))
        fetched = 0
        for lo, hi in self._missing_ranges(missing, remote_sorted):
            remaining = None if limit is None else limit - fetched
            if remaining is not None and remaining <= 0:
                logger.warning(
                    "SBDB reconciliation stopped by record limit "
                    "(%d of %d missing fetched)",
                    fetched,
                    len(missing),
                )
                return len(stale), fetched, False
            written, finished, _ = self._sync_pages(
                con,
                fields,
                json.dumps({"AND": [f"spkid|RG|{lo}|{hi}"]}),
                limit=remaining,
                desc=f"SBDB reconcile {lo}..{hi}",
            )
            fetched += written
            if not finished:
                return len(stale), fetched, False
            time.sleep(PAGE_SLEEP)
        return len(stale), fetched, True

    @staticmethod
    def _missing_ranges(
        missing: list[int], remote_sorted: list[int]
    ) -> list[tuple[int, int]]:
        """Group missing spkids into ranges for ``spkid|RG`` queries.

        Ranges also cover spkids we already hold (harmless upserts), so each
        one is grown only while it spans <= PAGE_SIZE remote records.
        """
        ranges = []
        i = 0
        while i < len(missing):
            lo_idx = bisect_left(remote_sorted, missing[i])
            j = i
            while (
                j + 1 < len(missing)
                and bisect_right(remote_sorted, missing[j + 1]) - lo_idx <= PAGE_SIZE
            ):
                j += 1
            ranges.append((missing[i], missing[j]))
            i = j + 1
        return ranges

    # --- orchestration --------------------------------------------------

    @staticmethod
    def _today() -> str:
        return datetime.now(timezone.utc).date().isoformat()

    def is_complete(self, limit: int | None) -> bool:
        if not self.metadata_file.exists():
            return False
        meta = json.loads(self.metadata_file.read_text())
        if meta.get("complete"):
            checked = meta.get("checked_at") or meta["downloaded_at"]
            return (
                datetime.now(timezone.utc) - datetime.fromisoformat(checked) < FRESHNESS
            )
        record_count = meta.get("record_count")
        return record_count is not None and limit is not None and limit <= record_count

    def _write_metadata(
        self, con: sqlite3.Connection, *, changed: bool, finished: bool
    ) -> None:
        """``downloaded_at`` moves only when the mirror content changed (it
        feeds the export cache signature); ``checked_at`` tracks sync
        freshness and moves on every finished run."""
        now = datetime.now(timezone.utc).isoformat()
        old = (
            json.loads(self.metadata_file.read_text())
            if self.metadata_file.exists()
            else {}
        )
        record_count = con.execute("SELECT COUNT(*) FROM bodies").fetchone()[0]
        self.metadata_file.write_text(
            json.dumps(
                {
                    "downloaded_at": now
                    if changed or not old.get("downloaded_at")
                    else old["downloaded_at"],
                    "checked_at": now if finished else old.get("checked_at", now),
                    "source_url": URL,
                    "record_count": record_count,
                    "complete": self._meta_get(con, "last_sync") is not None,
                },
                indent=2,
            )
        )

    def download(self, limit: int | None = None, **kwargs: object) -> None:
        fields = self._get_fields()
        con = sqlite3.connect(self.db_file)
        try:
            self._ensure_schema(con, fields)
            if self._meta_get(con, "last_sync") is None:
                changed, finished = self._full_sync(con, fields, limit)
            else:
                changed, finished = self._delta_sync(con, fields, limit)
            record_count = con.execute("SELECT COUNT(*) FROM bodies").fetchone()[0]
            logger.info(
                "SBDB mirror: %s records (%s changed this run)",
                f"{record_count:,}",
                f"{changed:,}",
            )
            self._write_metadata(con, changed=bool(changed), finished=finished)
        finally:
            con.close()
