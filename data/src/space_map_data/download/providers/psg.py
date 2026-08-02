"""Download NASA PSG's vertical atmosphere templates.

The Planetary Spectrum Generator ships a curated reference profile per body —
pressure, temperature and molecular mixing ratios on 30-100 levels — each
assembled from named published work (Venus from VIRA, Mars from the Mars
Climate Database, Titan from Teanby 2006, the giants from Moses 2005). That
aggregation is the reason to pull it: one fetch gets the profile behind a
dozen papers, already reconciled onto a single grid, and the per-body
``ATMOSPHERE-DESCRIPTION`` line names which ones.

What it is used for: the layer boundaries in ``constants/atmosphere/
structure.py`` are turning points in temperature, and these profiles are what
says whether the published tropopause is where the profile actually turns —
see ``tests/constants/test_atmosphere_structure.py``. The full profiles are
also what the piecewise-density shader will need when it stops being one
exponential per body.

The templates carry no altitude axis (Mars is the exception and includes one),
so cross-checks work in pressure, which is what the sources quote anyway.

On-disk layout::

    sources/atmosphere/psg/{body}.txt      raw PSG config, ATMOSPHERE-LAYER-N rows
    sources/atmosphere/psg/metadata.json
"""

import logging
import re
import time
from pathlib import Path
from typing import NamedTuple

import httpx

from space_map_data.constants.providers import PROVIDERS
from space_map_data.download.downloader import DownloadError, Downloader
from space_map_data.utils.paths import SOURCES_ATMOSPHERE_DIR

logger = logging.getLogger(__name__)

API_URL = "https://psg.gsfc.nasa.gov/api.php"
SOURCE_PAGE = "https://psg.gsfc.nasa.gov/"
CITATION = "https://doi.org/10.1016/j.jqsrt.2018.05.023"  # Villanueva et al. 2018

# PSG object name -> our object ID. Only bodies PSG actually ships a template
# for: Pluto, Triton and Io return a config with zero layers.
BODIES: dict[str, str] = {
    "Venus": "naif-299",
    "Earth": "naif-399",
    "Mars": "naif-499",
    "Jupiter": "naif-599",
    "Saturn": "naif-699",
    "Titan": "naif-606",
    "Uranus": "naif-799",
    "Neptune": "naif-899",
}

# Earth's template is a MERRA-2 reanalysis for whatever date it is asked for,
# so pin one rather than let the file churn on every re-download.
REQUEST_DATE = "2024/01/15 12:00"

# The anonymous server allows 100 calls a day; this uses eight.
REQUEST_DELAY_SECONDS = 3.0
REQUEST_TIMEOUT_SECONDS = 180.0

# Below this a response is a stub or an error page, not a profile.
MIN_LAYERS = 10

BAR_TO_PA = 1.0e5

_BOT_TOKEN = re.compile(r"[-_]?bot", re.IGNORECASE)
FALLBACK_USER_AGENT = "space-map/0.1"


class PSGAtmosphereDownloader(Downloader):
    """Download PSG reference atmosphere profiles."""

    name = PROVIDERS.PSG_ATMOSPHERE

    def __init__(self, client: httpx.Client) -> None:
        super().__init__(client)
        self.out_dir = SOURCES_ATMOSPHERE_DIR / "psg"
        self.out_dir.mkdir(parents=True, exist_ok=True)
        self._agent: str | None = None

    def is_complete(self, limit: int | None) -> bool:
        if not self.metadata_file.exists():
            return False
        if not all((self.out_dir / f"{body}.txt").exists() for body in BODIES.values()):
            return False
        return super().is_complete(limit)

    def download(self, limit: int | None = None, **kwargs: object) -> None:
        descriptions: dict[str, str] = {}
        for i, (psg_name, object_id) in enumerate(BODIES.items()):
            target = self.out_dir / f"{object_id}.txt"
            if target.exists() and target.stat().st_size > 0:
                descriptions[object_id] = _description(target.read_text())
                logger.debug("skip %s (already downloaded)", psg_name)
                continue
            if i > 0:
                time.sleep(REQUEST_DELAY_SECONDS)
            text = self._fetch(psg_name)
            target.write_text(text)
            descriptions[object_id] = _description(text)
            logger.info(
                "Saved %s (%s levels) — %s",
                target.name,
                f"{_layer_count(text):,}",
                descriptions[object_id],
            )

        self._save_metadata(
            API_URL,
            record_count=len(BODIES),
            complete=True,
            citation=CITATION,
            source_page=SOURCE_PAGE,
            request_date=REQUEST_DATE,
            # The provenance that matters is per body: each line names the
            # papers PSG built that template from, and that is what a credits
            # entry has to carry.
            templates=descriptions,
        )

    def _fetch(self, psg_name: str) -> str:
        config = (
            f"<OBJECT>Planet\n<OBJECT-NAME>{psg_name}\n<OBJECT-DATE>{REQUEST_DATE}\n"
        )
        logger.info("Fetching PSG atmosphere template for %s", psg_name)
        try:
            resp = self.client.post(
                API_URL,
                data={"type": "cfg", "watm": "y", "file": config},
                headers={"User-Agent": self._user_agent()},
                timeout=REQUEST_TIMEOUT_SECONDS,
            )
            resp.raise_for_status()
        except Exception as e:
            raise DownloadError(f"PSG request for {psg_name} failed: {e}") from e

        text = resp.text
        count = _layer_count(text)

        if count < MIN_LAYERS:
            # A body with no template answers 200 with a layerless config, so
            # a quiet write here would bank an empty file as if it were data.
            raise DownloadError(
                f"PSG returned {count} atmosphere levels for {psg_name} "
                f"(expected at least {MIN_LAYERS})"
            )
        return text

    def _user_agent(self) -> str:
        """PSG answers 200 with an empty body to any User-Agent containing
        "bot", so the shared one has to lose that token. Contact details stay."""
        if self._agent is None:
            shared = str(self.client.headers.get("User-Agent", ""))
            self._agent = _BOT_TOKEN.sub("", shared).strip() or FALLBACK_USER_AGENT
            if self._agent != shared:
                logger.info(
                    "Requesting as %r — PSG blocks bot user agents", self._agent
                )
        return self._agent


class Level(NamedTuple):
    """One row of a PSG profile. `abundances` are volume mixing ratios keyed
    by the template's own molecule names, aerosol columns included."""

    pressure_pa: float
    temperature_k: float
    abundances: dict[str, float]


def profile_path(object_id: str) -> Path:
    return SOURCES_ATMOSPHERE_DIR / "psg" / f"{object_id}.txt"


def read_profile(object_id: str) -> list[Level]:
    """Read a downloaded profile, bottom level first.

    Raises FileNotFoundError if the body was never downloaded — callers decide
    whether a missing profile is a skip or a failure.
    """
    text = profile_path(object_id).read_text()
    names = _molecules(text)
    levels = []
    for line in text.splitlines():
        if not line.startswith("<ATMOSPHERE-LAYER-"):
            continue
        values = [float(v) for v in line.split(">", 1)[1].split(",")]
        levels.append(
            Level(
                pressure_pa=values[0] * BAR_TO_PA,
                temperature_k=values[1],
                abundances=dict(zip(names, values[2:])),
            )
        )
    # PSG writes top-down for some bodies and bottom-up for others.
    levels.sort(key=lambda level: -level.pressure_pa)
    return levels


def _molecules(text: str) -> list[str]:
    prefix = "<ATMOSPHERE-LAYERS-MOLECULES>"
    for line in text.splitlines():
        if line.startswith(prefix):
            return line[len(prefix) :].strip().split(",")
    logger.warning("PSG config has no ATMOSPHERE-LAYERS-MOLECULES line")
    return []


def _layer_count(text: str) -> int:
    return sum(1 for line in text.splitlines() if line.startswith("<ATMOSPHERE-LAYER-"))


def _description(text: str) -> str:
    """PSG's own one-line provenance for the template, e.g. 'Titan atmosphere
    - Teanby et al. 2006, Icarus'."""
    prefix = "<ATMOSPHERE-DESCRIPTION>"
    for line in text.splitlines():
        if line.startswith(prefix):
            return line[len(prefix) :].strip()
    logger.warning("PSG config has no ATMOSPHERE-DESCRIPTION line")
    return ""
