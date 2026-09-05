"""Download fitted mutual orbits for asteroid moons from AsterSat.

AsterSat is the satellites-of-asteroids arm of the Natural Satellites Data
Base, maintained jointly by the Sternberg Astronomical Institute and IMCCE.
Its orbits come from Emelyanov & Drozdov (2020), a uniform fixed-Keplerian
re-fit of every published astrometric observation of these bodies.

It has no bulk endpoint: the satellite list is a `<select>` on the query form
and each orbit is printed in the header of a one-row ephemeris response, so
this walks the list and saves one response per satellite.
"""

import logging
import re
import time
from datetime import timedelta

import httpx
from tqdm import tqdm

from space_map_data.constants.providers import PROVIDERS
from space_map_data.download.downloader import DownloadError, Downloader
from space_map_data.utils.paths import SOURCES_POSITION_DIR

logger = logging.getLogger(__name__)

BASE_URL = "https://www.sai.msu.ru/neb/nss/"
FORM_URL = BASE_URL + "html/multisat/nssAste.htm"
EPHEM_URL = BASE_URL + "cgi-bin/nss-ast.cgi"

# The service publishes no rate limit and never pushed back at 0.4 s/request
# during survey; 4 s keeps a 10x margin over that on a 68-request walk.
PER_REQUEST_DELAY_SECONDS = 4.0

# Any epoch inside the service's stated coverage works — the orbit block is
# printed in the response header regardless, and one step is the cheapest ask.
_EPHEM_PARAMS = {
    "langue": "0",
    "observatory": "500",
    "tscale": "UTC",
    "vangle": "0",
    "initform": "2",  # Julian Day
    "initmom": "2460000.5",
    "steptype": "0",
    "timestep": "1",
    "ntimes": "1",
    "reserve": "2019",
    "reserve2": "2022",
}

_OPTION_RE = re.compile(r'<option value="([^"]+)"[^>]*>([^<\n]*)')


class AsterSatDownloader(Downloader):
    name = PROVIDERS.ASTERSAT
    # Emelyanov re-fits when new astrometry arrives, which is a few systems a
    # year — but the list itself grows with new discoveries.
    max_age = timedelta(days=30)

    def __init__(self, client: httpx.Client) -> None:
        self.client = client
        self.out_dir = SOURCES_POSITION_DIR / "astersat"
        self.out_dir.mkdir(parents=True, exist_ok=True)

    def _list_satellites(self) -> list[tuple[str, str]]:
        """Return ``(form id, label)`` for every satellite the form offers."""
        response = self.client.get(FORM_URL)
        response.raise_for_status()
        select = re.search(
            r'<select name="satellite">(.*?)</select>', response.text, re.S
        )
        if select is None:
            raise DownloadError("AsterSat form has no satellite list — layout changed")
        options = [
            (value, re.sub(r"\s+", " ", label).strip())
            for value, label in _OPTION_RE.findall(select.group(1))
        ]
        if not options:
            raise DownloadError("AsterSat satellite list is empty — layout changed")
        logger.info("AsterSat offers %d asteroid satellites", len(options))
        return options

    def _fetch(self, form_id: str) -> str:
        response = self.client.get(
            EPHEM_URL, params={**_EPHEM_PARAMS, "satellite": form_id}
        )
        response.raise_for_status()
        return response.text

    def download(self, limit: int | None = None, **kwargs: object) -> None:
        satellites = self._list_satellites()
        index_path = self.out_dir / "satellites.tsv"
        index_path.write_text(
            "\n".join(f"{fid}\t{label}" for fid, label in satellites) + "\n"
        )

        to_fetch = [
            (fid, label)
            for fid, label in satellites
            if not self._is_fresh(self.out_dir / f"{fid}.html")
        ]
        fresh = len(satellites) - len(to_fetch)
        if fresh:
            logger.info("%d AsterSat orbits still fresh, skipping", fresh)
        if limit is not None and len(to_fetch) > limit:
            to_fetch = to_fetch[:limit]

        failed = 0
        for form_id, label in tqdm(
            to_fetch, desc="AsterSat orbits", unit="sat", dynamic_ncols=True
        ):
            try:
                body = self._fetch(form_id)
            except Exception as exc:
                logger.warning("Failed to fetch AsterSat orbit for %s: %s", label, exc)
                failed += 1
                continue
            # A refused request still returns HTTP 200 with an `exit N` code
            # and no orbit block, so check the payload rather than the status.
            if "Satellite orbit" not in body:
                logger.warning("%s: response carries no orbit block, skipping", label)
                failed += 1
                continue
            (self.out_dir / f"{form_id}.html").write_text(body)
            time.sleep(PER_REQUEST_DELAY_SECONDS)

        on_disk = sum(
            1 for fid, _ in satellites if (self.out_dir / f"{fid}.html").exists()
        )
        self._save_metadata(
            EPHEM_URL,
            on_disk,
            complete=on_disk == len(satellites),
            satellites_listed=len(satellites),
            failed=failed,
        )
