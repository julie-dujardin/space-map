"""Provider entry point: walk Horizons MB, fetch+build each remaining probe."""

import logging
import time

import httpx

from space_map_data.constants.providers import PROVIDERS
from space_map_data.download.downloader import DownloadError, Downloader
from space_map_data.utils.paths import DERIVED_POSITION_DIR

from ..bodies.major_bodies import MB_FILENAME
from ..naif_http import intervals_overlap, spk_coverage
from .cache import fetch_one
from .horizons_api import HORIZONS_URL
from .index import (
    _parse_horizons_spacecraft,
    _write_index,
    agency_naif_coverage,
    celestrak_active_excludes,
    qid_deduped_synth_naifs,
)
from .layout import SYNTH_CACHE_ROOT, SYNTH_KERNELS_DIR
from .spk import build_one

logger = logging.getLogger(__name__)


class HorizonsSyntheticDownloader(Downloader):
    """Synthesize per-spacecraft SPKs from Horizons VECTORS.

    Walks the cached Horizons MB list, drops simulation/debris/stage/booster
    entries and QID-matched agency duplicates, fetches+builds the rest, then
    drops builds whose ET coverage overlaps an agency claim on the same NAIF
    (NAIF recycles low-magnitude IDs across eras — e.g. -9 = Mariner 9 (1971)
    and ESCAPADE-Blue (2025); only same-era collisions are real duplicates).
    Cache-skip via `Revised :` makes repeated runs cheap.
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
        mb_path = DERIVED_POSITION_DIR / "tables" / MB_FILENAME
        if not mb_path.exists():
            raise DownloadError(
                f"Need {mb_path}; run `space-map-download --sources spice` first"
            )
        all_sc = _parse_horizons_spacecraft(mb_path.read_text())
        ct_excludes = celestrak_active_excludes(all_sc)
        qid_dups = qid_deduped_synth_naifs()
        candidates = [
            (n, nm)
            for n, nm, _cospar in all_sc
            if n not in ct_excludes and n not in qid_dups
        ]
        logger.info(
            "horizons-synth: %d MB spacecraft - %d celestrak-active "
            "- %d qid-deduped against agency = %d to synthesize",
            len(all_sc),
            len(ct_excludes),
            len(qid_dups),
            len(candidates),
        )
        if limit is not None:
            candidates = candidates[:limit]
            logger.info("horizons-synth: limiting to %d", limit)
        return candidates

    def download(self, limit: int | None = None, **kwargs: object) -> None:
        candidates = self._candidates(limit)
        agency_coverage = agency_naif_coverage(exclude_mission="HORIZONS-SYNTH")
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
            spk_path = SYNTH_KERNELS_DIR / f"{naif_id}.bsp"
            agency_iv = agency_coverage.get(naif_id, [])
            if agency_iv:
                synth_iv = spk_coverage(spk_path, naif_id)
                if synth_iv and intervals_overlap(synth_iv, agency_iv):
                    # Rebuild as the agency-coverage complement rather than
                    # dropping — some agency SPKs cover a sliver of the
                    # mission (SIRTF ships Spitzer's last 3 months of 16
                    # years). Fully-inside synths are true duplicates.
                    try:
                        build_one(naif_id, exclude=agency_iv)
                    except RuntimeError:
                        logger.info(
                            "naif %d (%s): synth coverage fully inside agency "
                            "claim; dropping synth",
                            naif_id,
                            name,
                        )
                        spk_path.unlink(missing_ok=True)
                        skipped.append((naif_id, name, "agency-window-collision"))
                        continue
                    logger.info(
                        "naif %d (%s): trimmed synth to agency-coverage complement",
                        naif_id,
                        name,
                    )
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
