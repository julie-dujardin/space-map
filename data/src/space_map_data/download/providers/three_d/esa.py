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
the two catalogues can be consumed uniformly: ``slug``, ``files`` (the
downloaded source files, textures.zip excluded), and an empty ``missions``
list that gets hand-filled with NAIF / probe / NORAD / COSPAR IDs after
download (the SciFleet API doesn't expose them).
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
MERGED_MANIFEST = DOWNLOAD_DIR / "3d" / "merged.yaml"

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


def _load_claimed_esa_slugs() -> set[str]:
    """ESA slugs claimed by other manifests — to be skipped on metadata write.

    A slug is "claimed" if its corresponding file (``<slug>.<ext>``) appears
    in the ``files:`` list of an entry that's NOT itself that slug — meaning
    another entry has folded those files in.

    Sources:
    - ``merged.yaml`` — cross-catalog consolidations (e.g. ``cassini`` in
      merged.yaml uses ``ESA-SciFleet/cassini_huygens/cassini.fbx``).
    - Existing per-catalog ``metadata.yaml`` files — intra-ESA folds (e.g.
      ESA ``schiaparelli`` has ``edm.fbx`` folded in, claiming ``edm``).

    Files are still downloaded — they're referenced by path — but the
    standalone entry doesn't appear in the per-catalog metadata so the
    slug-uniqueness check on the ingest side doesn't fire.
    """
    claimed: set[str] = set()

    # 1. merged.yaml claims (cross-catalog).
    if MERGED_MANIFEST.is_file():
        try:
            doc = yaml.safe_load(MERGED_MANIFEST.read_text())
        except yaml.YAMLError as e:
            logger.warning(
                "Failed to parse %s: %s — no merged exclusions applied",
                MERGED_MANIFEST,
                e,
            )
            doc = None
        for entry in (doc or {}).get("entries") or []:
            for f in entry.get("files") or []:
                path = f.get("path") or ""
                if path.startswith(f"{DIR_LABEL}/"):
                    claimed.add(Path(path).stem)

    # 2. Intra-ESA folds: a file basename that differs from its host entry's
    # slug is folded foreign content (e.g. schiaparelli's files contain
    # edm.fbx → claims `edm`). Walk every existing ESA metadata.yaml.
    if TARGET_DIR.exists():
        for sub in TARGET_DIR.iterdir():
            meta = sub / "metadata.yaml"
            if not meta.is_file():
                continue
            try:
                doc = yaml.safe_load(meta.read_text())
            except yaml.YAMLError:
                continue
            for entry in (doc or {}).get("entries") or []:
                entry_slug = entry.get("slug")
                if not entry_slug:
                    continue
                for f in entry.get("files") or []:
                    stem = Path(f.get("path") or "").stem
                    if stem and stem != entry_slug:
                        claimed.add(stem)

    return claimed


class ESA3DDownloader(Downloader):
    """Mirror scifleet.esa.int 3D models."""

    name = PROVIDERS.ESA_3D

    def __init__(self, client: httpx.Client) -> None:
        # Skip base mkdir; we manage our own path under 3d/.
        self.client = client
        self.out_dir = TARGET_DIR
        TARGET_DIR.mkdir(parents=True, exist_ok=True)
        self._claimed_slugs = _load_claimed_esa_slugs()
        if self._claimed_slugs:
            logger.info(
                "merged.yaml claims %d ESA slug(s): %s",
                len(self._claimed_slugs),
                sorted(self._claimed_slugs),
            )

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

        # Preserve hand-edits (canonical, notes, wikidata_qid, missions, …)
        # across rewrites by indexing the existing metadata.yaml by slug.
        out = dir_path / "metadata.yaml"
        existing_by_slug = self._load_existing_entries(out)

        entries: list[dict] = []
        seen_slugs: set[str] = set()
        for slug in sorted(members):
            entry = catalog[slug]
            downloads = entry.get("downloads", {}) or {}
            files: list[dict] = []
            for fmt, type_label in WANTED_FORMATS.items():
                fname = downloads.get(fmt)
                if not fname:
                    continue
                ok, size = self._download_file(slug, fname, dir_path / fname)
                if not ok:
                    continue
                # `textures.zip` is fetched for the converter to stage next to
                # the .fbx but isn't a model file in its own right — keep it
                # out of the manifest's `files:` list.
                if type_label == "textures":
                    continue
                files.append(
                    {
                        "path": f"{DIR_LABEL}/{root}/{fname}",
                        "type": type_label,
                        "size": size,
                    }
                )
            if not files:
                logger.warning("No models downloaded for %s", slug)
            seen_slugs.add(slug)
            if slug in self._claimed_slugs:
                # Files were still downloaded so the claiming entry's path
                # references resolve; the standalone entry just doesn't
                # appear in this metadata.yaml (would otherwise trip
                # slug-uniqueness on the ingest side).
                if existing_by_slug.get(slug, {}).get("canonical"):
                    logger.warning(
                        "ESA slug %r marked canonical AND claimed elsewhere — "
                        "dropping standalone entry; review your manifest",
                        slug,
                    )
                else:
                    logger.info("ESA slug %r excluded — claimed elsewhere", slug)
                continue
            entries.append(
                self._build_entry(slug, entry, files, existing_by_slug.get(slug))
            )

        # Carry over entries whose slug no longer appears in the API response
        # (verbatim) instead of dropping them — the user's hand-edits and any
        # still-on-disk files stay useful. Warn so the divergence is visible.
        # Claimed slugs are still excluded.
        for stale_slug, stale_entry in existing_by_slug.items():
            if stale_slug in seen_slugs:
                continue
            if stale_slug in self._claimed_slugs:
                continue
            logger.warning(
                "ESA slug %r no longer in catalog API — keeping existing entry as-is",
                stale_slug,
            )
            entries.append(stale_entry)
        # Restore alphabetical ordering after the verbatim appends.
        entries.sort(key=lambda e: e.get("slug") or "")

        if not entries:
            # Every member is claimed → no per-catalog manifest makes sense
            # for this root. Drop any stale file from a previous run.
            if out.exists():
                out.unlink()
                logger.info(
                    "Removed stale %s (all members claimed elsewhere)",
                    out.relative_to(TARGET_DIR.parent),
                )
            else:
                logger.info(
                    "Skipping metadata write for %s (all members claimed elsewhere)",
                    dir_path.relative_to(TARGET_DIR.parent),
                )
            return

        self._write_metadata(dir_path, root, entries)

    def _load_existing_entries(self, path: Path) -> dict[str, dict]:
        if not path.is_file():
            return {}
        try:
            doc = yaml.safe_load(path.read_text())
        except yaml.YAMLError as e:
            logger.warning(
                "Existing %s unreadable (%s); hand-edits won't be preserved this run",
                path,
                e,
            )
            return {}
        return {
            entry["slug"]: entry
            for entry in ((doc or {}).get("entries") or [])
            if entry.get("slug")
        }

    def _build_entry(
        self, slug: str, raw: dict, files: list[dict], existing: dict | None
    ) -> dict:
        """Build a metadata entry, preserving hand-edits across rewrites.

        Downloader-owned (always refreshed): ``slug``, ``esa_catalog``. The
        ``files`` list is API-derived but carries over any *foreign-stem*
        entries from ``existing`` (e.g. ``rosetta`` keeps its folded-in
        ``rosetta_sc.fbx`` across re-downloads — without that, the fold
        relationship erodes and the foreign slug pops back as standalone
        on the next run).

        Defaulted-if-absent but preserved-if-set: ``kind`` (default
        ``"probe"``), ``wikidata_qid`` (default ``None``), ``missions``
        (default ``[]``). Everything else (``canonical``, ``notes``, unknown
        future fields) is carried over verbatim from ``existing``.

        Field order in the output is fixed so diffs stay readable across runs.
        """
        existing = existing or {}
        entry: dict = {"slug": slug, "kind": existing.get("kind", "probe")}
        if existing.get("canonical"):
            entry["canonical"] = existing["canonical"]
        if existing.get("notes"):
            entry["notes"] = existing["notes"]
        entry["wikidata_qid"] = existing.get("wikidata_qid")
        entry["esa_catalog"] = {
            "id": slug,
            "parent": raw.get("parent"),
            "label": raw.get("label"),
            "launch_year": raw.get("launch_year") or None,
            "status": raw.get("status") or None,
            "category_filter": raw.get("category_filter") or None,
            "description": _strip_html(raw.get("description")),
        }
        # Carry over folded-in files (basename ≠ own slug) so the fold relation
        # survives rewrites. Without this, _load_claimed_esa_slugs loses its
        # only signal that the foreign slug is claimed.
        folded = [
            f
            for f in (existing.get("files") or [])
            if Path(f.get("path", "")).stem != slug
            and not any(f.get("path") == nf["path"] for nf in files)
        ]
        if folded:
            logger.info(
                "preserving %d folded file(s) on ESA entry %r: %s",
                len(folded),
                slug,
                [Path(f["path"]).name for f in folded],
            )
        entry["files"] = files + folded
        # IDs (naif_id, probe_id, norad_cat_id, cospar_id, name) per mission
        # are filled in manually after download — the SciFleet API doesn't
        # expose them. Multi-mission entries (Cluster, Double Star, Proba-3)
        # grow extra rows under `missions:`.
        entry["missions"] = existing.get("missions") or []
        # Carry over any other user-added fields that the downloader doesn't
        # know about, after the canonical-ordered ones.
        for k, v in existing.items():
            if k not in entry:
                entry[k] = v
        return entry

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
