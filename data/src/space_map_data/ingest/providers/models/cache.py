"""Convert-once-per-source compressed-GLB cache.

Each manifest source file is converted to two compressed glTFs (high + low
knobs) under ``CONVERTED_DIR/{slug}/{file_id}.{tier}.glb`` with a sibling
``{file_id}.cache.json`` carrying the invalidation key (source sha256 +
``COMPRESSION_KNOBS_VERSION``). The picker downstream compares
post-compression sizes across all cached candidates to choose which one
becomes the public high/low tier.

A separate cache layer (vs converting straight into ``PROCESSED_DIR``)
lets us:
- Skip already-converted files on subsequent runs without re-reading the
  prod metadata.json.
- Know each source's compressed size before deciding tiers — necessary for
  picking by actual fidelity/size rather than source-format priority.
"""

import json
import logging
import re
import shutil
import tempfile
import zipfile
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from space_map_data.ingest.providers.models import config, conversion, metadata

log = logging.getLogger(__name__)

TIERS = ("high", "low")


@dataclass(frozen=True)
class Cached:
    """One source's two cached compressed-GLB tiers + provenance."""

    file_id: str
    source_path: Path
    source_type: str
    source_sha256: str
    high_glb: Path
    low_glb: Path | None

    def size(self, tier: str) -> int:
        glb = self.high_glb if tier == "high" else self.low_glb
        return glb.stat().st_size if glb and glb.exists() else 0


def file_id_for(source_path: str) -> str:
    """Stable identifier for a manifest file path within a slug's cache dir.

    Strips the directory and keeps ``{basename_without_ext}.{ext}`` so
    sibling files of different types (``cassini.fbx`` vs ``cassini.blend``)
    don't collide. Replaces filesystem-hostile chars with ``_``.
    """
    name = Path(source_path).name  # e.g. "Cassini-Huygens (A) (without Hyugens).glb"
    return re.sub(r"[^A-Za-z0-9._()-]+", "_", name)


def ensure_cached(
    *,
    slug: str,
    source_path: Path,
    source_type: str,
    has_blender: bool,
    has_gltf_transform: bool,
) -> Cached | None:
    """Materialise (or reuse) the high+low compressed-GLB pair for one source.

    Returns None if the source can't be converted in the current
    environment (e.g. needs Blender but it's missing). Sha-matched cache
    entries skip both Blender and gltf-transform; mismatches re-run both.

    Synthesising low from high requires gltf-transform; without it we
    leave ``low_glb=None`` and the picker treats this candidate as
    high-only.
    """
    cache_dir = config.CONVERTED_DIR / slug
    cache_dir.mkdir(parents=True, exist_ok=True)

    fid = file_id_for(str(source_path))
    cache_meta_path = cache_dir / f"{fid}.cache.json"
    high_glb = cache_dir / f"{fid}.high.glb"
    low_glb = cache_dir / f"{fid}.low.glb"

    source_sha256 = metadata.sha256_file(source_path)

    if _cache_hit(cache_meta_path, source_sha256, low_required=has_gltf_transform):
        return Cached(
            file_id=fid,
            source_path=source_path,
            source_type=source_type,
            source_sha256=source_sha256,
            high_glb=high_glb,
            low_glb=low_glb if low_glb.exists() else None,
        )

    if source_type != "glb" and not has_blender:
        log.info("skip cache build for %s (%s): Blender unavailable", slug, fid)
        return None

    # Stale outputs from a prior knob version would mislead the picker if
    # the new build fails partway through — remove before re-running.
    for stale in (high_glb, low_glb, cache_meta_path):
        stale.unlink(missing_ok=True)

    # tmpdir under DOWNLOAD_DIR (not /tmp) so Flatpak'd Blender can see it.
    tmp_root = config.MODELS_DOWNLOAD_DIR / ".staging"
    tmp_root.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(
        prefix=f"smd-cache-{slug}-", dir=tmp_root
    ) as tmp_str:
        tmp = Path(tmp_str)
        intermediate = (
            source_path
            if source_type == "glb"
            else _blender_to_glb_staged(source_path, tmp / "input.glb")
        )

        if has_gltf_transform:
            conversion.gltf_transform_optimize(intermediate, high_glb, tier="high")
            conversion.gltf_transform_optimize(intermediate, low_glb, tier="low")
            produced_low: Path | None = low_glb
        else:
            # No optimiser → pass intermediate through verbatim, no low tier.
            shutil.copyfile(intermediate, high_glb)
            produced_low = None

    _write_cache_meta(
        cache_meta_path,
        source_sha256=source_sha256,
        source_type=source_type,
        has_low=produced_low is not None,
    )

    return Cached(
        file_id=fid,
        source_path=source_path,
        source_type=source_type,
        source_sha256=source_sha256,
        high_glb=high_glb,
        low_glb=produced_low,
    )


def _cache_hit(meta_path: Path, source_sha256: str, *, low_required: bool) -> bool:
    if not meta_path.exists():
        return False
    try:
        existing = json.loads(meta_path.read_text())
    except (OSError, json.JSONDecodeError):
        return False
    if existing.get("schema") != config.SCHEMA_VERSION:
        return False
    if existing.get("knobs") != config.COMPRESSION_KNOBS_VERSION:
        return False
    if existing.get("source_sha256") != source_sha256:
        return False
    # A run that had gltf-transform previously cached a `low`; if it's gone
    # now (user removed it), reuse high anyway. The opposite — needing low
    # but the cache was built without it — must trigger a rebuild.
    if low_required and not existing.get("has_low"):
        return False
    return True


def _write_cache_meta(
    meta_path: Path,
    *,
    source_sha256: str,
    source_type: str,
    has_low: bool,
) -> None:
    payload = {
        "schema": config.SCHEMA_VERSION,
        "knobs": config.COMPRESSION_KNOBS_VERSION,
        "source_type": source_type,
        "source_sha256": source_sha256,
        "has_low": has_low,
        "converted_at": datetime.now(UTC).isoformat(),
    }
    meta_path.write_text(json.dumps(payload, indent=2))


def _blender_to_glb_staged(src: Path, dst: Path) -> Path:
    """Convert ``src`` to ``dst`` via Blender, staging any sibling textures.zip.

    Mirrors ``ModelProcessor._to_glb`` — kept as a free function so the
    cache module doesn't reach back into the processor. ESA .fbx files
    reference textures via relative paths that only resolve when
    ``<name>_textures.zip`` is extracted alongside the .fbx.
    """
    staging_root = config.MODELS_DOWNLOAD_DIR / ".staging"
    staging_root.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(
        prefix="smd-blender-", dir=staging_root
    ) as staging_str:
        staging = Path(staging_str)
        staged_src = staging / src.name
        shutil.copyfile(src, staged_src)
        for textures_zip in src.parent.glob("*_textures.zip"):
            with zipfile.ZipFile(textures_zip) as zf:
                zf.extractall(staging)
        conversion.blender_to_glb(staged_src, dst)
    return dst


def prune_slug_dirs(active_slugs: set[str]) -> int:
    """Delete ``CONVERTED_DIR/{slug}/`` directories no longer in any manifest.

    Mirrors ``ModelProcessor._prune_stale_bundles`` but for the upstream
    cache. Returns count pruned.
    """
    if not config.CONVERTED_DIR.exists():
        return 0
    pruned = 0
    for slug_dir in config.CONVERTED_DIR.iterdir():
        if not slug_dir.is_dir() or slug_dir.name.startswith("."):
            continue
        if slug_dir.name in active_slugs:
            continue
        log.info("pruning stale converted cache: %s", slug_dir.name)
        shutil.rmtree(slug_dir)
        pruned += 1
    return pruned


def prune_orphan_files(slug: str, active_file_ids: set[str]) -> int:
    """Inside one slug's cache dir, delete files whose ``file_id`` no longer
    appears in the manifest entry (source file removed).
    """
    cache_dir = config.CONVERTED_DIR / slug
    if not cache_dir.exists():
        return 0
    pruned = 0
    for entry in cache_dir.iterdir():
        # Each cached source contributes up to 3 files: .high.glb, .low.glb, .cache.json.
        # Recover the file_id by stripping the longest matching suffix.
        for suffix in (".high.glb", ".low.glb", ".cache.json"):
            if entry.name.endswith(suffix):
                fid = entry.name[: -len(suffix)]
                if fid not in active_file_ids:
                    log.info("pruning orphan cache file %s/%s", slug, entry.name)
                    entry.unlink()
                    pruned += 1
                break
    return pruned
