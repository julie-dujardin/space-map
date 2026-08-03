"""Download Bjorn Jonsson's Saturn ring profile data.

Fetches five 1-D radial profiles (13 177 samples each, values in [0, 1])
spanning 74 510 km – 140 390 km from Saturn's center:

- ``backscattered`` — appearance from the sun-lit side
- ``forwardscattered`` — appearance at high phase angle (≈139°)
- ``unlitside`` — appearance from the un-lit side (back-lit transmission)
- ``transparency`` — opacity profile (1 = transparent, 0 = opaque)
- ``color`` — RGB derived from Cassini imaging

The data are publicly available with attribution per
https://bjj.mmedia.is/acknow.html. See the ``ring-metadata.yaml``
written alongside the channel `.txt` files for the canonical
attribution string.

A sixth ``thickness`` channel is derived locally rather than downloaded: BJJ
publishes no vertical extent, so it is rasterised from the NSSDCA per-region
figures in constants/rings/catalog.py and credited separately in the yaml.

On-disk layout::

    sources/textures/rings/saturn/{channel}.txt
    sources/textures/rings/saturn/ring-metadata.yaml
"""

import logging
import time
from datetime import UTC, datetime

import httpx
import yaml

from space_map_data.constants.providers import PROVIDERS
from space_map_data.constants.rings.attribution import NASA, NASA_LICENSE
from space_map_data.constants.rings.catalog import SATURN_MEASURED_THICKNESS
from space_map_data.download.downloader import DownloadError, Downloader
from space_map_data.utils.paths import SOURCES_TEXTURES_DIR

logger = logging.getLogger(__name__)

BASE_URL = "https://bjj.mmedia.is/data/s_rings"
BODY = "naif-699"
BUNDLE = "primary"
SOURCE_PAGE = f"{BASE_URL}/index.html"
DESCRIPTION = (
    "1-D radial profiles of Saturn's main rings: separate channels for "
    "back-scattered light (sun-lit side), forward-scattered light (~139° phase), "
    "un-lit side appearance, transparency, and color."
)

# Geometry constants documented at the source page. The samples are uniformly
# spaced over [INNER_RADIUS_KM, OUTER_RADIUS_KM]; downstream code can derive
# per-sample radii from these without re-deriving from the data.
INNER_RADIUS_KM = 74510.0
OUTER_RADIUS_KM = 140390.0
SAMPLE_COUNT = 13177

CHANNELS: dict[str, str] = {
    "backscattered": "backscattered.txt",
    "forwardscattered": "forwardscattered.txt",
    "unlitside": "unlitside.txt",
    "transparency": "transparency.txt",
    "color": "sat_rings_color.txt",
}

# Derived locally from NSSDCA figures, not fetched.
THICKNESS_FILE = "thickness.txt"
THICKNESS_SCALE_KM = max(z.thickness_m for z in SATURN_MEASURED_THICKNESS) / 1000.0
# The photometry and the vertical extent come from different works, so each
# is credited for what it actually contributed.
SOURCES = [
    {
        "source": SOURCE_PAGE,
        "organisation": "Björn Jónsson",
        "license": "Free use with attribution",
        "work": "Saturn ring profiles",
        "contribution": (
            "back-scattered, forward-scattered and unlit-side brightness, "
            "transparency and colour of the main rings, measured from NASA PDS "
            "Cassini imaging"
        ),
    },
    {
        "source": "https://web.archive.org/web/20241206102306/https://nssdc.gsfc.nasa.gov/planetary/factsheet/satringfact.html",
        "organisation": NASA,
        "license": NASA_LICENSE,
        "work": "NSSDCA Saturnian Rings Fact Sheet",
        "contribution": (
            "vertical thickness of the C, B, Cassini Division and A regions "
            "(D. R. Williams, NASA Goddard Space Flight Center)"
        ),
    },
]

REQUEST_DELAY_SECONDS = 2.0


class BJJRingsDownloader(Downloader):
    """Download BJJ Saturn ring profile text files."""

    name = PROVIDERS.BJJ_RINGS

    def __init__(self, client: httpx.Client) -> None:
        super().__init__(client)
        self.out_dir = SOURCES_TEXTURES_DIR / "rings" / "saturn"
        self.out_dir.mkdir(parents=True, exist_ok=True)
        self.metadata_yaml = self.out_dir / "ring-metadata.yaml"

    def is_complete(self, limit: int | None) -> bool:
        if not self.metadata_yaml.exists():
            return False
        if not (self.out_dir / THICKNESS_FILE).exists():
            return False
        return all((self.out_dir / fn).exists() for fn in CHANNELS.values())

    def download(self, limit: int | None = None, **kwargs: object) -> None:
        for i, (channel, filename) in enumerate(CHANNELS.items()):
            target = self.out_dir / filename
            url = f"{BASE_URL}/{filename}"
            if target.exists() and target.stat().st_size > 0:
                logger.debug("skip %s (already downloaded)", filename)
                continue
            if i > 0:
                time.sleep(REQUEST_DELAY_SECONDS)
            logger.info("Fetching %s", url)
            try:
                resp = self.client.get(url, timeout=60.0)
                resp.raise_for_status()
            except Exception as e:
                raise DownloadError(f"Failed to fetch {url}: {e}") from e

            text = resp.text
            n_values = sum(1 for line in text.splitlines() if line.strip())
            if n_values != SAMPLE_COUNT:
                # Loud failure rather than swallow — pipeline assumes a fixed
                # sample count and downstream PNG dims are derived from it.
                raise DownloadError(
                    f"{filename}: expected {SAMPLE_COUNT} non-empty lines, "
                    f"got {n_values} (from {url})"
                )
            target.write_text(text)
            logger.info(
                "Saved %s (%s lines, %s bytes)",
                target.relative_to(self.out_dir),
                f"{n_values:,}",
                f"{len(text):,}",
            )

        self._write_thickness()
        self._write_metadata_yaml()

    def _write_thickness(self) -> None:
        """Rasterise the NSSDCA per-region thickness onto the BJJ sample grid,
        normalised to THICKNESS_SCALE_KM. Radii outside every tabulated region
        (the Roche Division and F ring past the A ring) get 0 — rendered flat."""
        step = (OUTER_RADIUS_KM - INNER_RADIUS_KM) / (SAMPLE_COUNT - 1)
        lines = []
        for i in range(SAMPLE_COUNT):
            radius = INNER_RADIUS_KM + i * step
            thickness_m = next(
                (
                    z.thickness_m
                    for z in SATURN_MEASURED_THICKNESS
                    if z.inner_km <= radius < z.outer_km
                ),
                0.0,
            )
            lines.append(f"{thickness_m / 1000.0 / THICKNESS_SCALE_KM:.6f}")
        (self.out_dir / THICKNESS_FILE).write_text("\n".join(lines) + "\n")
        logger.info(
            "Wrote %s (%s samples, %.0f m full scale)",
            THICKNESS_FILE,
            f"{SAMPLE_COUNT:,}",
            THICKNESS_SCALE_KM * 1000.0,
        )

    def _write_metadata_yaml(self) -> None:
        payload = {
            "body": BODY,
            "bundle": BUNDLE,
            "sources": [dict(s) for s in SOURCES],
            "description": DESCRIPTION,
            "downloaded_at": datetime.now(UTC).isoformat(),
            "inner_radius_km": INNER_RADIUS_KM,
            "outer_radius_km": OUTER_RADIUS_KM,
            "sample_count": SAMPLE_COUNT,
            "thickness_scale_km": THICKNESS_SCALE_KM,
            "channels": {**CHANNELS, "thickness": THICKNESS_FILE},
        }
        self.metadata_yaml.write_text(
            yaml.safe_dump(payload, sort_keys=False, allow_unicode=True)
        )
        logger.info(
            "Wrote ring metadata -> %s",
            self.metadata_yaml.relative_to(self.out_dir.parent),
        )
