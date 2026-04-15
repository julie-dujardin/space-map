import logging
import sys

from space_map_data.constants.earth_sats.constellations import (
    GROUP_TO_CATEGORY,
    GROUP_TO_SLUG,
)
from space_map_data.constants.providers import PROVIDERS
from space_map_data.download.downloader import Downloader

logger = logging.getLogger(__name__)

GP_URL = "https://celestrak.org/NORAD/elements/gp.php"
SATCAT_URL = "https://celestrak.org/pub/satcat.csv"

# CelesTrak groups we fetch: constellation memberships (can't be derived from
# OBJECT_NAME) and category-only groupings (military, radar, ...).
GROUPS: tuple[str, ...] = tuple({*GROUP_TO_SLUG.keys(), *GROUP_TO_CATEGORY.keys()})


class CelesTrakDownloader(Downloader):
    name = PROVIDERS.CELESTRAK

    def download(self, limit: int | None = None, **kwargs: object) -> None:
        # 1. Active GP (TLE elements)
        gp_url = f"{GP_URL}?GROUP=active&FORMAT=csv"
        gp_count = self._fetch_csv(gp_url, self.out_dir / "gp-active.csv", "active GP")

        # 2. SATCAT (country, launch site, decay, RCS, ...)
        satcat_count = self._fetch_csv(
            SATCAT_URL, self.out_dir / "satcat.csv", "SATCAT"
        )

        # 3. Per-constellation group memberships
        groups_dir = self.out_dir / "groups"
        groups_dir.mkdir(exist_ok=True)
        group_counts: dict[str, int] = {}
        for group in GROUPS:
            url = f"{GP_URL}?GROUP={group}&FORMAT=csv"
            count = self._fetch_csv(
                url, groups_dir / f"{group}.csv", f"group {group}", allow_empty=True
            )
            group_counts[group] = count

        self._save_metadata(
            gp_url,
            gp_count,
            complete=True,
            satcat_records=satcat_count,
            groups=group_counts,
        )

    def _fetch_csv(
        self, url: str, out_file, label: str, allow_empty: bool = False
    ) -> int:
        logger.info("Downloading %s...", label)
        response = self.client.get(url)

        if response.status_code in (403, 404):
            logger.error("HTTP %d — stopping (do not retry)", response.status_code)
            sys.exit(1)
        response.raise_for_status()

        body = response.text
        # CelesTrak returns plain text "No GP data found" for empty groups
        if not body.startswith("OBJECT_NAME"):
            if allow_empty:
                logger.warning("No data for %s (response: %r)", label, body[:80])
                out_file.write_text("")
                return 0
            logger.error("Unexpected response for %s: %r", label, body[:80])
            sys.exit(1)

        out_file.write_text(body)
        record_count = body.count("\n") - 1
        logger.info(
            "Saved %s records -> %s",
            f"{record_count:,}",
            out_file.relative_to(self.out_dir),
        )
        return record_count
