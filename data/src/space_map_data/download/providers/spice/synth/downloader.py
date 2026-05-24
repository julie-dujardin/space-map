"""Provider entry point: walk Horizons MB, fetch+build each remaining probe."""

import logging
import time

import httpx

from space_map_data.constants.providers import PROVIDERS
from space_map_data.download.downloader import DownloadError, Downloader
from space_map_data.utils.paths import DOWNLOAD_DIR

from ..bodies.major_bodies import MB_FILENAME
from .cache import fetch_one
from .horizons_api import HORIZONS_URL
from .index import (
    _existing_agency_naifs,
    _parse_horizons_spacecraft,
    _write_index,
    qid_deduped_synth_naifs,
)
from .layout import SYNTH_CACHE_ROOT
from .spk import build_one

logger = logging.getLogger(__name__)


class HorizonsSyntheticDownloader(Downloader):
    """Synthesize per-spacecraft SPKs from Horizons VECTORS.

    Selection: walk the cached Horizons MB list, drop simulation/debris/
    stage/booster entries, drop NAIF IDs already covered by an agency SPK in
    `missions/`, then fetch+build the remainder. Cache-skip via OBJ_DATA's
    `Revised :` header makes repeated runs cheap.
    """

    name = PROVIDERS.SPICE_HORIZONS_SYNTH

    def __init__(self, client: httpx.Client) -> None:
        # Skip Downloader's default `out_dir = DOWNLOAD_DIR / name`; the cache
        # tree lives under spice/horizons-synth/ so it's grouped with other
        # SPICE data.
        self.client = client
        self.out_dir = SYNTH_CACHE_ROOT
        self.out_dir.mkdir(parents=True, exist_ok=True)

    def _candidates(self, limit: int | None) -> list[tuple[int, str]]:
        mb_path = DOWNLOAD_DIR / PROVIDERS.SPICE / MB_FILENAME
        if not mb_path.exists():
            raise DownloadError(
                f"Need {mb_path}; run `space-map-download --sources spice` first"
            )
        all_sc = _parse_horizons_spacecraft(mb_path.read_text())
        agency = _existing_agency_naifs()
        qid_dups = qid_deduped_synth_naifs()
        candidates = [
            (n, nm) for n, nm in all_sc if n not in agency and n not in qid_dups
        ]
        logger.info(
            "horizons-synth: %d MB spacecraft - %d already in missions/ "
            "- %d qid-deduped against agency = %d to synthesize",
            len(all_sc),
            len(agency),
            len(qid_dups),
            len(candidates),
        )
        if limit is not None:
            candidates = candidates[:limit]
            logger.info("horizons-synth: limiting to %d", limit)
        return candidates

    def download(self, limit: int | None = None, **kwargs: object) -> None:
        candidates = self._candidates(limit)
        succeeded: dict[int, str] = {}
        skipped: list[tuple[int, str, str]] = []
        failed: list[tuple[int, str, str]] = []

        for i, (naif_id, name) in enumerate(candidates, 1):
            logger.info("[%d/%d] naif %d (%s)", i, len(candidates), naif_id, name)
            try:
                fetch_one(self.client, naif_id)
            except RuntimeError as exc:
                logger.warning("naif %d fetch failed: %s", naif_id, exc)
                failed.append((naif_id, name, f"fetch: {exc}"))
                continue
            except httpx.HTTPError as exc:
                logger.warning("naif %d HTTP error: %s", naif_id, exc)
                failed.append((naif_id, name, f"http: {exc}"))
                continue
            try:
                build_one(naif_id)
            except RuntimeError as exc:
                # build_one raises if no segments meet degree+1 — common
                # for spacecraft whose Horizons coverage is < 8 days.
                logger.warning("naif %d build failed: %s", naif_id, exc)
                skipped.append((naif_id, name, f"build: {exc}"))
                continue
            succeeded[naif_id] = name
            # Light pacing between spacecraft.
            time.sleep(0.5)

        _write_index(succeeded)
        self._save_metadata(
            HORIZONS_URL,
            len(succeeded),
            complete=False,  # cache-skip handles per-spacecraft idempotency
            attempted=len(candidates),
            succeeded=len(succeeded),
            skipped=len(skipped),
            failed=len(failed),
            failed_examples=[
                {"naif_id": n, "name": nm, "reason": r} for n, nm, r in failed[:10]
            ],
            skipped_examples=[
                {"naif_id": n, "name": nm, "reason": r} for n, nm, r in skipped[:10]
            ],
        )
        logger.info(
            "horizons-synth: %d succeeded / %d skipped / %d failed (of %d)",
            len(succeeded),
            len(skipped),
            len(failed),
            len(candidates),
        )
