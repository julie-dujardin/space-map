"""Build Earth's water mask from OpenStreetMap coastlines and HydroSHEDS vectors.

The mask feeds the ``cylindrical_specular`` texture entry, which the renderer
uses as a roughness map. It replaces a GEBCO bathymetry threshold, which had
no inland water at all and read every shallow bank — the Bahamas, the Florida
shelf, the Persian Gulf — as land.

Three archives are pulled and rasterised locally (see ``water_mask``). The
HydroSHEDS pair is a frozen v1.0 release, so only the OSM extract expires.

Licensing: OSM water polygons are ODbL, the HydroSHEDS products CC BY 4.0 —
both attributed through the manifest at
``constants/manifests/textures/specular/earth/``, beside Titan's.

On-disk layout::

    sources/textures/specular/earth/vectors/<archive>/…   extracted shapefiles
    sources/textures/specular/earth/water-mask.png        rendered mask
    sources/textures/specular/earth/metadata.json
"""

import logging
import zipfile
from dataclasses import dataclass
from datetime import timedelta
from pathlib import Path

import httpx

from space_map_data.constants.providers import PROVIDERS
from space_map_data.download.downloader import DownloadError, Downloader
from space_map_data.utils.paths import SOURCES_TEXTURES_DIR

from .water_mask import render_water_mask

logger = logging.getLogger(__name__)

MASK_FILE = "water-mask.png"
ARCHIVE_TIMEOUT_S = 900.0
MIN_ARCHIVE_BYTES = 10 * 1024 * 1024


@dataclass(frozen=True)
class VectorSource:
    """One shapefile archive: where to get it and which layer to read back."""

    key: str
    url: str
    # Shapefile stem relative to the extraction root, without the .shp suffix.
    layer: str
    source_page: str
    # False for frozen releases, so a staleness sweep re-pulls only OSM.
    expires: bool


OCEAN = VectorSource(
    key="water-polygons-split-4326",
    url="https://osmdata.openstreetmap.de/download/water-polygons-split-4326.zip",
    layer="water-polygons-split-4326/water_polygons",
    source_page="https://osmdata.openstreetmap.de/data/water-polygons.html",
    expires=True,
)
LAKES = VectorSource(
    key="HydroLAKES_polys_v10_shp",
    url="https://data.hydrosheds.org/file/hydrolakes/HydroLAKES_polys_v10_shp.zip",
    layer="HydroLAKES_polys_v10_shp/HydroLAKES_polys_v10",
    source_page="https://www.hydrosheds.org/products/hydrolakes",
    expires=False,
)
RIVERS = VectorSource(
    key="HydroRIVERS_v10_shp",
    url="https://data.hydrosheds.org/file/HydroRIVERS/HydroRIVERS_v10_shp.zip",
    layer="HydroRIVERS_v10_shp/HydroRIVERS_v10",
    source_page="https://www.hydrosheds.org/products/hydrorivers",
    expires=False,
)
SOURCES = (OCEAN, LAKES, RIVERS)


class EarthWaterDownloader(Downloader):
    """Fetch the coastline/lake/river vectors and rasterise Earth's water mask."""

    name = PROVIDERS.EARTH_WATER
    # OSM coastlines improve continuously but the mask costs ~2 minutes and
    # 4 GiB to rebuild, so it is refreshed on a yearly sweep rather than daily.
    max_age = timedelta(days=365)

    def __init__(self, client: httpx.Client) -> None:
        self.client = client
        # Beside Titan's hand-downloaded specular map — same texture type, same
        # manifest tree. The vectors sit under the body dir rather than a
        # sibling: only `file` in the manifest is read, so the subdirectory is
        # invisible to the texture pipeline.
        self.out_dir = SOURCES_TEXTURES_DIR / "specular" / "earth"
        self.vectors_dir = self.out_dir / "vectors"
        self.out_dir.mkdir(parents=True, exist_ok=True)

    def _layer_path(self, source: VectorSource) -> Path:
        return self.vectors_dir / f"{source.layer}.shp"

    def _fetch(self, source: VectorSource) -> None:
        """Download and extract one archive, unless its layer is already on disk and current."""
        layer = self._layer_path(source)
        if layer.exists() and (not source.expires or self._is_fresh(layer)):
            logger.info("%s already extracted", source.key)
            return

        # Written beside the target and moved on success so an interrupted run
        # cannot leave a truncated zip that extracts to a partial layer.
        archive = self.vectors_dir / f"{source.key}.zip"
        partial = archive.with_suffix(".partial")
        self.vectors_dir.mkdir(parents=True, exist_ok=True)
        logger.info("Downloading %s...", source.key)
        written = 0
        with self.client.stream("GET", source.url, timeout=ARCHIVE_TIMEOUT_S) as resp:
            if resp.status_code in (403, 404):
                raise DownloadError(f"{source.key}: HTTP {resp.status_code}")
            resp.raise_for_status()
            with partial.open("wb") as fh:
                for chunk in resp.iter_bytes(chunk_size=1 << 20):
                    fh.write(chunk)
                    written += len(chunk)
        if written < MIN_ARCHIVE_BYTES:
            partial.unlink(missing_ok=True)
            raise DownloadError(f"{source.key}: {written} bytes, expected an archive")

        partial.replace(archive)
        with zipfile.ZipFile(archive) as zf:
            zf.extractall(self.vectors_dir)
        # The extracted shapefiles are what every later run reads; keeping the
        # zip beside them doubles ~5 GiB of source data for nothing.
        archive.unlink()
        if not layer.exists():
            raise DownloadError(
                f"{source.key}: {source.layer}.shp missing after extract"
            )
        logger.info("Extracted %s (%.0f MB downloaded)", source.key, written / 1e6)

    def download(self, limit: int | None = None, **kwargs: object) -> None:
        for source in SOURCES:
            self._fetch(source)

        render_water_mask(
            ocean=self._layer_path(OCEAN),
            lakes=self._layer_path(LAKES),
            rivers=self._layer_path(RIVERS),
            out_path=self.out_dir / MASK_FILE,
        )
        self._save_metadata(
            OCEAN.source_page,
            record_count=len(SOURCES),
            complete=True,
            layers={s.key: s.source_page for s in SOURCES},
        )
