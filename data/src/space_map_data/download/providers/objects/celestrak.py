import json
import logging
from datetime import date, datetime, timezone
from pathlib import Path

import httpx

from space_map_data.constants.earth_sats.constellations import (
    GROUP_TO_CATEGORY,
    GROUP_TO_SLUG,
)
from space_map_data.constants.providers import PROVIDERS
from space_map_data.download.downloader import DownloadError, Downloader
from space_map_data.utils.paths import SOURCES_POSITION_DIR

logger = logging.getLogger(__name__)

GP_URL = "https://celestrak.org/NORAD/elements/gp.php"
SATCAT_URL = "https://celestrak.org/pub/satcat.csv"

# CelesTrak groups we fetch: constellation memberships (can't be derived from
# OBJECT_NAME) and category-only groupings (military, radar, ...).
GROUPS: tuple[str, ...] = tuple({*GROUP_TO_SLUG.keys(), *GROUP_TO_CATEGORY.keys()})


class CelesTrakDownloader(Downloader):
    name = PROVIDERS.CELESTRAK

    def __init__(self, client: httpx.Client) -> None:
        self.client = client
        self.out_dir = SOURCES_POSITION_DIR / "celestrak"
        self.out_dir.mkdir(parents=True, exist_ok=True)

    def _day_dir(self, day: date) -> Path:
        return self.out_dir / f"{day.year:04d}" / f"{day.month:02d}" / f"{day.day:02d}"

    def is_complete(self, limit: int | None) -> bool:
        # GP/groups are refetched every UTC day; skip only if today is done.
        if not self.metadata_file.exists():
            return False
        meta = json.loads(self.metadata_file.read_text())
        today = datetime.now(timezone.utc).date().isoformat()
        return meta.get("day") == today

    def download(self, limit: int | None = None, **kwargs: object) -> None:
        # SATCAT metadata + group memberships (curated lists not derivable from
        # a satellite's name); orbital elements come from Space-Track.
        today = datetime.now(timezone.utc).date()
        day_dir = self._day_dir(today)
        day_dir.mkdir(parents=True, exist_ok=True)

        # 1. SATCAT (country, launch site, decay, RCS, ...) — not elements, top-level
        satcat_count = self._fetch_csv(
            SATCAT_URL, self.out_dir / "satcat.csv", "SATCAT"
        )

        # 2. Per-group memberships (constellation + category) — daily
        groups_dir = day_dir / "groups"
        groups_dir.mkdir(exist_ok=True)
        group_counts: dict[str, int] = {}
        for group in GROUPS:
            url = f"{GP_URL}?GROUP={group}&FORMAT=csv"
            count = self._fetch_csv(
                url, groups_dir / f"{group}.csv", f"group {group}", allow_empty=True
            )
            group_counts[group] = count

        self._save_metadata(
            SATCAT_URL,
            satcat_count,
            complete=True,
            day=today.isoformat(),
            satcat_records=satcat_count,
            groups=group_counts,
        )

    def _fetch_csv(
        self, url: str, out_file, label: str, allow_empty: bool = False
    ) -> int:
        logger.info("Downloading %s...", label)
        response = self.client.get(url)

        if response.status_code in (403, 404):
            raise DownloadError(
                f"HTTP {response.status_code} fetching {label} — stopping (do not retry)"
            )
        response.raise_for_status()

        body = response.text
        # CelesTrak returns plain text "No GP data found" for empty groups
        if not body.startswith("OBJECT_NAME"):
            if allow_empty:
                logger.warning("No data for %s (response: %r)", label, body[:80])
                out_file.write_text("")
                return 0
            raise DownloadError(f"Unexpected response for {label}: {body[:80]!r}")

        out_file.write_text(body)
        record_count = body.count("\n") - 1
        logger.info(
            "Saved %s records -> %s",
            f"{record_count:,}",
            out_file.relative_to(self.out_dir),
        )
        return record_count
