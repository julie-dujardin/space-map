"""Mirror the ESA SciFleet 3D-model catalogue.

The site (https://scifleet.esa.int/model-downloads) is a SPA that loads its
satellite list from ``data/satellites.json`` and serves model files at
``downloads/<slug>/<filename>``. We grab fbx + blend + textures.zip for every
spacecraft, grouping ESA's parent/child relationships (BepiColombo's four
modules, Cassini-Huygens's components, etc.) under a single root directory.

Per-root layout::

    DOWNLOAD_DIR/3d/ESA-SciFleet/<root>/
        <slug>.fbx, <slug>.blend, <slug>_textures.zip, ...
        metadata.yaml

metadata.yaml mirrors the per-entry schema of ``nasa-3d-resources.yaml`` so
the two catalogues can be consumed uniformly. ID fields (naif_id, probe_id,
wikidata_qid, norad_cat_id, cospar_id) are left null — the downloader can't
reliably auto-match — and are filled in by hand afterwards.
"""

import logging
import re
import time
from datetime import UTC, datetime
from html import unescape
from pathlib import Path

import httpx
import yaml

from space_map_data.constants.providers import PROVIDERS
from space_map_data.download.downloader import DownloadError, Downloader
from space_map_data.utils.paths import DOWNLOAD_DIR

logger = logging.getLogger(__name__)

CATALOG_URL = "https://scifleet.esa.int/data/satellites.json"
DOWNLOADS_BASE = "https://scifleet.esa.int/downloads"
PAGE_URL = "https://scifleet.esa.int/model-downloads"

TARGET_DIR = DOWNLOAD_DIR / "3d" / "ESA-SciFleet"
DIR_LABEL = "ESA-SciFleet"  # used in model paths (relative to DOWNLOAD_DIR/3d/)

# Formats to fetch and the `type:` label written into metadata.yaml.
WANTED_FORMATS: dict[str, str] = {
    "fbx": "fbx",
    "blend": "blend",
    "textures": "textures",
}

# Explicit per-slug exclusions (in addition to the *_selected planet markers
# and entries without any 3D download).
SKIP_SLUGS = {
    "hst",  # only links to external NASA Hubble obj, no actual file
    "1p halley",  # comet target, no downloads
    "67p",  # Churyumov-Gerasimenko comet target; out of scope
}

REQUEST_DELAY_SECONDS = 1.0


def _strip_html(text: str | None) -> str | None:
    """Collapse whitespace and remove tags from ESA's HTML descriptions."""
    if not text:
        return None
    text = re.sub(r"<[^>]+>", "", text)
    text = unescape(text)
    text = re.sub(r"\s+", " ", text).strip()
    return text or None


class ESA3DDownloader(Downloader):
    """Mirror scifleet.esa.int 3D models."""

    name = PROVIDERS.ESA_3D

    def __init__(self, client: httpx.Client) -> None:
        # Skip base mkdir; we manage our own path under 3d/.
        self.client = client
        self.out_dir = TARGET_DIR
        TARGET_DIR.mkdir(parents=True, exist_ok=True)

    def is_complete(self, limit: int | None) -> bool:
        # Always re-run; per-file skip handles incremental downloads.
        return False

    def download(self, limit: int | None = None, **kwargs: object) -> None:
        catalog = self._fetch_catalog()
        groups = self._group_by_root(catalog)
        logger.info(
            "ESA SciFleet: %d roots covering %d entries",
            len(groups),
            sum(len(m) for m in groups.values()),
        )

        for root, members in sorted(groups.items()):
            self._process_root(root, members, catalog)

    def _fetch_catalog(self) -> dict:
        logger.info("GET %s", CATALOG_URL)
        try:
            resp = self.client.get(CATALOG_URL, timeout=60.0)
            resp.raise_for_status()
        except Exception as e:
            raise DownloadError(f"Failed to fetch ESA catalog: {e}") from e
        return resp.json()

    def _group_by_root(self, catalog: dict) -> dict[str, list[str]]:
        """Group satellite entries by their topmost ancestor slug.

        Skips planet/moon UI markers, entries without any 3D download,
        and explicit SKIP_SLUGS.
        """
        groups: dict[str, list[str]] = {}
        for slug, entry in catalog.items():
            if slug.endswith("_selected"):
                continue
            if slug in SKIP_SLUGS:
                continue
            if entry.get("type") != "satellite":
                continue
            downloads = entry.get("downloads", {}) or {}
            if not any(downloads.get(f) for f in ("fbx", "blend", "obj")):
                continue
            # Walk parent chain to find the root.
            root = slug
            seen = {slug}
            while True:
                parent = catalog.get(root, {}).get("parent")
                if not parent or parent in seen or parent not in catalog:
                    break
                root = parent
                seen.add(parent)
            groups.setdefault(root, []).append(slug)
        return groups

    def _process_root(self, root: str, members: list[str], catalog: dict) -> None:
        dir_path = TARGET_DIR / root
        dir_path.mkdir(parents=True, exist_ok=True)

        entries: list[dict] = []
        for slug in sorted(members):
            entry = catalog[slug]
            downloads = entry.get("downloads", {}) or {}
            models: list[dict] = []
            for fmt, type_label in WANTED_FORMATS.items():
                fname = downloads.get(fmt)
                if not fname:
                    continue
                ok, size = self._download_file(slug, fname, dir_path / fname)
                if not ok:
                    continue
                models.append(
                    {
                        "path": f"{DIR_LABEL}/{root}/{fname}",
                        "type": type_label,
                        "size": size,
                    }
                )
            if not models:
                logger.warning("No models downloaded for %s", slug)
            entries.append(self._build_entry(slug, entry, models))

        self._write_metadata(dir_path, root, entries)

    def _build_entry(self, slug: str, raw: dict, models: list[dict]) -> dict:
        name = (raw.get("heading") or slug).strip()
        return {
            "slug": slug,
            "name": name,
            "kind": "probe",
            "naif_id": None,
            "probe_id": None,
            "probe_mission": None,
            "wikidata_qid": None,
            "norad_cat_id": None,
            "cospar_id": None,
            "notes": None,
            "esa_catalog": {
                "id": slug,
                "parent": raw.get("parent"),
                "label": raw.get("label"),
                "launch_year": raw.get("launch_year") or None,
                "status": raw.get("status") or None,
                "category_filter": raw.get("category_filter") or None,
                "description": _strip_html(raw.get("description")),
            },
            "models": models,
        }

    def _write_metadata(self, dir_path: Path, root: str, entries: list[dict]) -> None:
        meta = {
            "source": {
                "catalog": "ESA SciFleet",
                "catalog_url": PAGE_URL,
                "catalog_api": CATALOG_URL,
                "attribution": "ESA / scifleet.esa.int",
                "downloaded_at": datetime.now(UTC).isoformat(),
            },
            "entries": entries,
        }
        out = dir_path / "metadata.yaml"
        out.write_text(
            yaml.safe_dump(
                meta,
                sort_keys=False,
                allow_unicode=True,
                width=120,
            )
        )
        logger.info(
            "Wrote %s (%d entries)", out.relative_to(TARGET_DIR.parent), len(entries)
        )

    def _download_file(self, slug: str, fname: str, target: Path) -> tuple[bool, int]:
        """Download a file, skipping if already on disk with non-zero size."""
        url = f"{DOWNLOADS_BASE}/{slug}/{fname}"
        if target.exists() and target.stat().st_size > 0:
            logger.debug(
                "skip %s (exists, %d bytes)", target.name, target.stat().st_size
            )
            return True, target.stat().st_size

        logger.info("GET %s", url)
        try:
            with self.client.stream("GET", url, timeout=600.0) as resp:
                resp.raise_for_status()
                with target.open("wb") as f:
                    for chunk in resp.iter_bytes(64 * 1024):
                        f.write(chunk)
        except Exception as e:
            logger.warning("Failed %s: %s", url, e)
            if target.exists():
                target.unlink()
            return False, 0
        time.sleep(REQUEST_DELAY_SECONDS)
        size = target.stat().st_size
        logger.info("  %s (%.1f MB)", target.name, size / (1024 * 1024))
        return True, size
