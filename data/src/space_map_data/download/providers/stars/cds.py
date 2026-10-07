"""Download the star catalogues that CDS publishes as files.

These catalogues give what Gaia does not: the stars too bright for Gaia, the
brown dwarfs too faint for it, a cleaned list of the nearest stars, and the
velocities, metallicities and spectral types of the Hipparcos stars.

Writes, below sources/stars/cds/:
- <catalogue>/ReadMe    the CDS description, with the format of each file
- <catalogue>/<file>    the files named in CATALOGUES, as published
- metadata.json
`<catalogue>` is the CDS identifier as a path, for example `J/A+A/649/A6`.

Every file is checked against the record count in its ReadMe, on download and
again on each later run. CDS answers 403 to a User-Agent that contains "bot".
"""

import logging
import time
from pathlib import Path

import httpx

from space_map_data.constants.providers import PROVIDERS
from space_map_data.download.cds import CDS_URL, README, count_records, record_counts
from space_map_data.download.downloader import (
    DownloadError,
    Downloader,
    user_agent_without_bot,
)
from space_map_data.utils.paths import SOURCES_STARS_DIR

logger = logging.getLogger(__name__)

OUT_DIR = SOURCES_STARS_DIR / "cds"
ATTEMPTS = 4
RETRY_WAIT_SECONDS = 15.0

CATALOGUES: dict[str, tuple[str, ...]] = {
    # Hipparcos, the new reduction (van Leeuwen 2007).
    "I/311": ("hip2.dat.gz", "hip7p.dat", "hip9p.dat", "hipvim.dat"),
    # The Hipparcos catalogue (ESA 1997): magnitudes, spectral types, HD
    # numbers, and the double-star and variability annexes. Tycho-1 is left out.
    "I/239": (
        "hip_main.dat",
        "h_dm_com.dat.gz",
        "h_dm_cor.dat.gz",
        "hip_dm_g.dat.gz",
        "hip_dm_o.dat.gz",
        "hip_dm_v.dat.gz",
        "hip_dm_x.dat.gz",
        "hip_va_1.dat.gz",
        "hip_va_2.dat.gz",
        "hd_notes.doc.gz",
        "hg_notes.doc",
        "hp_notes.doc.gz",
        "hp_auth.doc.gz",
        "hp_refs.doc.gz",
        "dmsa_o.doc.gz",
    ),
    # USNO Bright Star Catalog (Zacharias+ 2022): new astrometry for the 1,423
    # brightest stars.
    "J/AJ/164/36": ("table2.dat",),
    # Extended Hipparcos Compilation (Anderson+ 2012): radial velocities, iron
    # abundances, spectral types and names for the Hipparcos stars.
    "V/137D": (
        "main.dat.gz",
        "photo.dat.gz",
        "biblio.dat.gz",
        "groups.dat",
        "refs.dat",
    ),
    # Fifth Catalogue of Nearby Stars (Golovin+ 2023): stars and brown dwarfs
    # within 25 pc.
    "J/A+A/670/A19": ("cns5.dat",),
    # The 20 pc census (Kirkpatrick+ 2024).
    "J/ApJS/271/55": (
        "table1.dat",
        "notes1.dat",
        "table2.dat",
        "table3.dat",
        "table4.dat.gz",
        "notes4.dat.gz",
        "table5.dat",
        "table6.dat",
        "table7.dat",
        "table8.dat",
        "table9.dat",
        "table10.dat",
        "table11.dat",
        "table12.dat",
        "table13.dat",
        "table14.dat",
        "table15.dat",
        "table18.dat",
        "tablea2.dat",
        "tablea3.dat",
        "tablea4.dat",
        "tableb1.dat",
        "refs.dat",
    ),
    # Gaia Catalogue of Nearby Stars (Gaia Collaboration 2021): the sources
    # within 100 pc, kept and rejected. The distance PDFs are left out.
    "J/A+A/649/A6": (
        "table1c.dat.gz",
        "table1r.dat.gz",
        "table3.dat.gz",
        "missing.dat",
        "maglim.dat.gz",
        "hyacomb.dat",
        "progwd.dat",
    ),
}


class CDSStarCataloguesDownloader(Downloader):
    name = PROVIDERS.CDS_STAR_CATALOGUES

    def __init__(self, client: httpx.Client) -> None:
        super().__init__(client)
        self.out_dir = OUT_DIR
        self.out_dir.mkdir(parents=True, exist_ok=True)
        self._agent = user_agent_without_bot(client)

    def download(self, limit: int | None = None, **kwargs: object) -> None:
        records: dict[str, dict[str, int]] = {}
        for catalogue, names in CATALOGUES.items():
            catalogue_dir = self.out_dir / catalogue
            catalogue_dir.mkdir(parents=True, exist_ok=True)
            readme = self._get(f"{catalogue}/{README}")
            expected = record_counts(readme.decode("utf-8", errors="replace"))
            unlisted = [n for n in names if n.removesuffix(".gz") not in expected]
            if unlisted:
                raise DownloadError(
                    f"{catalogue}: the ReadMe gives no record count for "
                    f"{', '.join(unlisted)}"
                )
            (catalogue_dir / README).write_bytes(readme)
            records[catalogue] = {}
            for name in names:
                listed = expected[name.removesuffix(".gz")]
                self._ensure_file(catalogue, name, catalogue_dir / name, listed)
                records[catalogue][name] = listed
            logger.info("%s: %d files", catalogue, len(names))

        self._save_metadata(
            CDS_URL,
            sum(len(names) for names in CATALOGUES.values()),
            complete=True,
            records=records,
        )

    def _get(self, path: str) -> bytes:
        for attempt in range(1, ATTEMPTS + 1):
            try:
                response = self.client.get(
                    f"{CDS_URL}/{path}",
                    headers={"User-Agent": self._agent},
                    timeout=600.0,
                )
                if response.status_code in (403, 404):
                    raise DownloadError(f"HTTP {response.status_code} for {path}")
                response.raise_for_status()
                return response.content
            except httpx.HTTPError as error:
                if attempt == ATTEMPTS:
                    raise DownloadError(f"{path}: {error!r}") from error
                logger.warning("%s: attempt %d/%d: %r", path, attempt, ATTEMPTS, error)
                time.sleep(RETRY_WAIT_SECONDS * attempt)
        raise AssertionError("unreachable")

    def _ensure_file(self, catalogue: str, name: str, dest: Path, listed: int) -> None:
        """Keep the file on disk when it has `listed` records, else fetch it."""
        if dest.exists():
            if count_records(dest.read_bytes(), name) == listed:
                logger.debug("%s/%s: already on disk", catalogue, name)
                return
            logger.info(
                "%s/%s: the ReadMe changed its count, fetching again", catalogue, name
            )
        content = self._get(f"{catalogue}/{name}")
        found = count_records(content, name)
        if found != listed:
            raise DownloadError(
                f"{catalogue}/{name}: {found} records, the ReadMe lists {listed}"
            )
        part = dest.with_name(dest.name + ".part")
        part.write_bytes(content)
        part.replace(dest)
        logger.info("%s/%s: %d bytes", catalogue, name, dest.stat().st_size)
