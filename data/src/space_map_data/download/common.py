"""Download orchestration — source registry and main download loop."""

import logging
import tomllib
from dataclasses import dataclass
from datetime import date
from typing import Any, Type

import httpx

from space_map_data.utils.paths import CONFIG_FILE, DOWNLOAD_DIR
from space_map_data.download.downloader import Downloader
from space_map_data.download.providers.objects.celestrak import CelesTrakDownloader
from space_map_data.download.providers.objects.gcat import GCATDownloader
from space_map_data.download.providers.spice import (
    HorizonsSyntheticDownloader,
    ProbesDownloader,
    PropagationDownloader,
    SpiceDownloader,
)
from space_map_data.download.providers.iau_nomenclature import IAUNomenclatureDownloader
from space_map_data.download.providers.objects.sbdb import SBDBDownloader
from space_map_data.download.providers.objects.sbdb_moons import (
    SBDBMoonsDownloader,
)
from space_map_data.download.providers.wikidata import WikidataDownloader
from space_map_data.download.providers.wikipedia import WikipediaDownloader
from space_map_data.download.providers.images.commons import CommonsDownloader
from space_map_data.download.providers.images.earth_clouds import (
    EarthCloudsDownloader,
)
from space_map_data.download.providers.metadata.texture_sources import (
    TextureSourcesDownloader,
)
from space_map_data.download.providers.bjj_rings import BJJRingsDownloader
from space_map_data.download.providers.three_d.nasa import NASA3DResourcesDownloader
from space_map_data.download.providers.three_d.esa import ESA3DDownloader

logger = logging.getLogger(__name__)


PROVIDERS_CLASSES = [
    CelesTrakDownloader,
    GCATDownloader,
    SBDBDownloader,
    SBDBMoonsDownloader,
    SpiceDownloader,
    ProbesDownloader,
    HorizonsSyntheticDownloader,
    PropagationDownloader,
    WikidataDownloader,
    WikipediaDownloader,
    CommonsDownloader,
    EarthCloudsDownloader,
    IAUNomenclatureDownloader,
    TextureSourcesDownloader,
    BJJRingsDownloader,
    NASA3DResourcesDownloader,
    ESA3DDownloader,
]
SOURCES: dict[str, Type[Downloader]] = {cls.name: cls for cls in PROVIDERS_CLASSES}

ALL_SOURCES = list(SOURCES)


@dataclass
class ProviderResult:
    name: str
    ok: bool
    error: str | None = None
    skipped: bool = False


def load_config() -> dict[str, Any]:
    """Load download configuration from config.toml."""
    if not CONFIG_FILE.exists():
        raise FileNotFoundError(f"Config file not found at {CONFIG_FILE}")
    with CONFIG_FILE.open("rb") as f:
        return tomllib.load(f)


def download(
    sources: list[str] | None = None,
    limit: int | None = 50_000,
    *,
    force: bool = False,
    epoch: date | None = None,
) -> list[ProviderResult]:
    """Download data from the given sources (default: all).

    Each provider is tried independently; a failure is logged and recorded
    but does not stop the loop.
    """
    DOWNLOAD_DIR.mkdir(exist_ok=True)
    selected = list(ALL_SOURCES) if sources is None else sources

    config = load_config()
    user_agent = config["download"]["user_agent"]

    results: list[ProviderResult] = []
    with httpx.Client(
        headers={"User-Agent": user_agent},
        follow_redirects=True,
        timeout=60.0,
    ) as client:
        for name in selected:
            cls = SOURCES[name]
            downloader = cls(client)
            if not force and downloader.is_complete(limit):
                logger.info("Skipping %s (already complete)", name)
                results.append(ProviderResult(name, ok=True, skipped=True))
                continue
            try:
                downloader.download(limit=limit, epoch=epoch)
                results.append(ProviderResult(name, ok=True))
            except Exception as e:
                logger.exception("Provider %s failed", name)
                results.append(
                    ProviderResult(name, ok=False, error=f"{type(e).__name__}: {e}")
                )
    return results
