"""Natural-body shape-model ingest: manifests → GLB bundles + Object pointers.

Extends the spacecraft model pipeline (shared cache scheme, gltf-transform
Meshopt, Cloudflare file cap) with the concerns unique to scanned body shapes:
- source meshes in a dozen PDS/JAXA/ESA encodings (see ``mesh_formats``);
- true km scale recorded from the mesh bounds (no fit-to-unit-radius);
- provenance/license/citation carried straight from the manifest;
- ``kind: shape_model`` so the frontend sizes the overlay mesh in true km
  and orients it by the body's IAU pole.

Bodies resolve to Objects by ``naif_id`` (the DB row's canonical NAIF form).
Entries with a null ``naif_id`` are skipped with a log line.
"""

import json
import logging
import subprocess
import tempfile
from datetime import UTC, datetime
from pathlib import Path

from ruamel.yaml import YAML

from space_map_data.ingest.providers.models import config, conversion, metadata
from space_map_data.ingest.providers.models.processor import _link_into_export
from space_map_data.models.object import ModelProvenance, Object
from space_map_data.utils.paths import SOURCES_MODELS_BODIES_DIR

log = logging.getLogger(__name__)

_yaml = YAML()
_yaml.preserve_quotes = True

# Manifest ``units`` → km scale. Most archives are already km; a few (e.g. the
# Stardust Wild 2 cart table) ship metres, which would otherwise record a 1000×
# true_scale and mis-size any true-km consumer of the mesh.
_UNIT_TO_KM: dict[str, float] = {"km": 1.0, "m": 0.001}

# Archive-string → MODEL_CATALOGS key, for the credits roll-up. PDS wins when a
# body is co-hosted (e.g. 67P's ESAC draft + PDS mirror) — cleanest license.
_CATALOG_MATCHERS: tuple[tuple[str, str], ...] = (
    ("PDS", "PDS Small Bodies Node"),
    ("DARTS", "JAXA/ISAS DARTS"),
    ("JAXA", "JAXA/ISAS DARTS"),
    ("Rosetta", "ESA/ESAC Rosetta"),
    ("ESAC", "ESA/ESAC Rosetta"),
    ("JPL", "JPL Asteroid Radar Research"),
)


def _catalog_for(archive: str | None) -> str | None:
    if not archive:
        return None
    for needle, catalog in _CATALOG_MATCHERS:
        if needle.lower() in archive.lower():
            return catalog
    return None


class BodyModelProcessor:
    """Convert + export the missions/radar shape-model manifests."""

    def __init__(self, session) -> None:
        self._session = session
        self._has_blender = conversion.blender_available()
        self._has_gltf_transform = conversion.gltf_transform_available()

    def load_entries(self) -> list[tuple[str, Path, dict]]:
        """Return ``(tier, tier_dir, entry)`` for every missions/radar entry."""
        out: list[tuple[str, Path, dict]] = []
        for tier in config.BODY_MANIFEST_TIERS:
            tier_dir = SOURCES_MODELS_BODIES_DIR / tier
            manifest = tier_dir / "manifest.yaml"
            if not manifest.exists():
                log.info("no bodies manifest at %s", manifest)
                continue
            doc = _yaml.load(manifest.read_text()) or {}
            for entry in doc.get("entries") or []:
                out.append((tier, tier_dir, entry))
        return out

    def wanted_slugs(self, entries: list[tuple[str, Path, dict]]) -> set[str]:
        """Slugs that resolve to a DB Object — the shippable set for pruning."""
        return {
            entry["slug"]
            for _tier, _dir, entry in entries
            if entry.get("slug") and self._resolve_object_id(entry) is not None
        }

    def process(self, entries: list[tuple[str, Path, dict]], *, force: bool) -> None:
        if not self._has_blender:
            log.warning("blender unavailable — skipping natural-body shape models")
            return
        for tier, tier_dir, entry in entries:
            slug = entry.get("slug")
            if not slug:
                log.warning("bodies/%s: entry without slug — skipping", tier)
                continue
            try:
                self._process_entry(tier, tier_dir, entry, force=force)
            except subprocess.CalledProcessError as exc:
                stderr = (exc.stderr or "")[-800:]
                log.warning("body %s: conversion failed: %s", slug, stderr)
            except Exception:
                log.exception("body %s: unexpected failure", slug)

    def _resolve_object_id(self, entry: dict) -> str | None:
        naif = entry.get("naif_id")
        if naif is None:
            return None
        row = self._session.query(Object.id).where(Object.naif_id == int(naif)).first()
        return row[0] if row else None

    def _process_entry(
        self, tier: str, tier_dir: Path, entry: dict, *, force: bool
    ) -> None:
        slug = entry["slug"]
        if entry.get("naif_id") is None:
            log.warning("body %s: null naif_id in manifest — skipping", slug)
            return
        object_id = self._resolve_object_id(entry)
        if object_id is None:
            log.warning(
                "body %s: no DB Object for naif_id=%s — skipping",
                slug,
                entry.get("naif_id"),
            )
            return

        candidates = [
            f for f in (entry.get("files") or []) if f.get("format") and f.get("path")
        ]
        if not candidates:
            log.warning("body %s: no usable files in entry", slug)
            return
        # Manifest order is authoritative (curated best-first) — facets are no
        # quality proxy: a superseding model can be coarser (Kleopatra:
        # Shepard 2018 vs Ostro 2000).
        picked = self._convert_first_fitting(slug, tier_dir, candidates, force=force)
        if picked is None:
            log.warning("body %s: no candidate produced a shippable GLB", slug)
            return
        source_file, high_glb, low_glb, bounds = picked

        out_dir = config.PROCESSED_DIR / slug
        _link_into_export(high_glb, out_dir / "high.glb")
        _link_into_export(low_glb, out_dir / "low.glb")
        self._write_metadata(
            out_dir=out_dir,
            slug=slug,
            tier=tier,
            entry=entry,
            object_id=object_id,
            source_file=source_file,
            high_glb=out_dir / "high.glb",
            low_glb=out_dir / "low.glb",
            bounds=bounds,
        )
        self._session.query(Object).filter(Object.id == object_id).update(
            {Object.model_name: slug, Object.model_provenance: ModelProvenance(tier)}
        )

    def _convert_first_fitting(
        self,
        slug: str,
        tier_dir: Path,
        candidates: list[dict],
        *,
        force: bool,
    ) -> tuple[dict, Path, Path, dict | None] | None:
        """Convert candidates in order; return the first whose high tier fits."""
        for f in candidates:
            src = tier_dir / f["path"]
            if not src.exists():
                log.warning("body %s: missing source %s", slug, f["path"])
                continue
            try:
                high_glb, low_glb, bounds = self._cached_tiers(
                    slug,
                    src,
                    f["format"],
                    force,
                    lon_first=f.get("grid_order") == "lon_lat",
                    units=f.get("units", "km"),
                )
            except subprocess.CalledProcessError as exc:
                stderr = (exc.stderr or "")[-500:]
                log.info("body %s: candidate %s failed: %s", slug, f["path"], stderr)
                continue
            high_size = high_glb.stat().st_size
            if high_size > config.MAX_FILE_BYTES:
                log.info(
                    "body %s: %s high tier %d B > cap — trying next source",
                    slug,
                    f["path"],
                    high_size,
                )
                continue
            return f, high_glb, low_glb, bounds
        return None

    def _cached_tiers(
        self,
        slug: str,
        src: Path,
        fmt: str,
        force: bool,
        *,
        lon_first: bool = False,
        units: str = "km",
    ) -> tuple[Path, Path, dict | None]:
        """Materialise (or reuse) the high+low GLB pair + true km bounds.

        Bounds come from the raw pre-Meshopt GLB: Meshopt quantises positions
        to int16, so the shipped GLB's accessor min/max are quantisation range,
        not km. They're cached so a cache hit doesn't need a reconvert. ``units``
        scales metre-unit archives into the km convention (see ``_UNIT_TO_KM``).
        """
        scale = _UNIT_TO_KM[units]
        cache_dir = config.BODY_CONVERTED_DIR / slug
        cache_dir.mkdir(parents=True, exist_ok=True)
        # Keyed on source content (not path) + parse params that change the mesh.
        fid = metadata.sha256_file(src)[:16]
        if lon_first:
            fid += "-lonlat"
        if scale != 1.0:
            fid += f"-{units}"
        high_glb = cache_dir / f"{fid}.high.glb"
        low_glb = cache_dir / f"{fid}.low.glb"
        meta_path = cache_dir / f"{fid}.cache.json"

        cached = self._cache_hit(meta_path, high_glb, low_glb) if not force else None
        if cached is not None:
            return high_glb, low_glb, cached.get("bounds")

        for stale in (high_glb, low_glb, meta_path):
            stale.unlink(missing_ok=True)

        # Stage under the downloads dir — the Flatpak Blender can't see /tmp.
        tmp_root = SOURCES_MODELS_BODIES_DIR / ".staging"
        tmp_root.mkdir(parents=True, exist_ok=True)
        bounds: dict | None = None
        with tempfile.TemporaryDirectory(
            prefix=f"smd-body-{slug}-", dir=tmp_root
        ) as td:
            work = Path(td)
            from space_map_data.ingest.providers.models.bodies import mesh_formats

            mesh = mesh_formats.normalize_to_mesh(
                src, fmt, work, lon_first=lon_first, scale=scale
            )
            for dst, target in (
                (high_glb, config.BODY_HIGH_TIER_MAX_TRIS),
                (low_glb, config.BODY_LOW_TIER_TRIS),
            ):
                raw = work / (dst.stem + ".raw.glb")
                conversion.body_blender_to_glb(mesh, raw, target_tris=target)
                if dst is high_glb:
                    bounds = metadata.gltf_bounds(raw)  # km, pre-quantisation
                if self._has_gltf_transform:
                    conversion.gltf_transform_meshopt(raw, dst)
                else:
                    raw.replace(dst)

        meta_path.write_text(
            json.dumps(
                {
                    "knobs": config.BODY_KNOBS_VERSION,
                    "schema": config.SCHEMA_VERSION,
                    "source_sha256": metadata.sha256_file(src),
                    "bounds": bounds,
                    "converted_at": datetime.now(UTC).isoformat(),
                }
            )
        )
        return high_glb, low_glb, bounds

    def _cache_hit(self, meta_path: Path, high_glb: Path, low_glb: Path) -> dict | None:
        """Return the cache stamp when high/low GLBs are current, else None."""
        if not (meta_path.exists() and high_glb.exists() and low_glb.exists()):
            return None
        try:
            meta = json.loads(meta_path.read_text())
        except OSError, json.JSONDecodeError:
            return None
        if (
            meta.get("knobs") == config.BODY_KNOBS_VERSION
            and meta.get("schema") == config.SCHEMA_VERSION
        ):
            return meta
        return None

    def _write_metadata(
        self,
        *,
        out_dir: Path,
        slug: str,
        tier: str,
        entry: dict,
        object_id: str,
        source_file: dict,
        high_glb: Path,
        low_glb: Path,
        bounds: dict | None,
    ) -> None:
        catalog = _catalog_for(entry.get("archive"))
        catalog_url = (
            config.MODEL_CATALOGS[catalog]["url"]
            if catalog in config.MODEL_CATALOGS
            else None
        )
        credit = {
            "name": (
                config.MODEL_CATALOGS[catalog]["default_attribution"]
                if catalog in config.MODEL_CATALOGS
                else "NASA"
            ),
            "url": entry.get("archive_url") or catalog_url,
        }
        # Short, uniform license for the credit chip — from the catalog. The
        # detailed per-entry ``license``/``citation`` stay as top-level metadata.
        catalog_license = (
            config.MODEL_CATALOGS[catalog].get("license")
            if catalog in config.MODEL_CATALOGS
            else None
        )
        if catalog_license:
            credit["license"] = catalog_license
        exports: dict = {}
        for name, glb in (("high", high_glb), ("low", low_glb)):
            record: dict = {
                "size_bytes": glb.stat().st_size,
                "sha256": metadata.sha256_file(glb),
                "source_type": source_file["format"],
                "credit": credit,
            }
            if catalog:
                record["catalog"] = catalog
            stats = metadata.gltf_stats(glb)
            if stats:
                record["stats"] = stats
            exports[name] = record

        true_scale = None
        if bounds:
            true_scale = {
                "max_extent_km": bounds["max_extent"],
                "bounding_radius_km": bounds["bounding_radius"],
                "bbox_min_km": bounds["min"],
                "bbox_max_km": bounds["max"],
            }
        else:
            log.warning("body %s: no true-scale bounds available", slug)

        payload: dict = {
            "slug": slug,
            "schema": config.SCHEMA_VERSION,
            "kind": "shape_model",
            "provenance": tier,
            "object_id": object_id,
            "naif_id": entry.get("naif_id"),
            "name": entry.get("name"),
            "credit": credit,
            "license": entry.get("license"),
            "license_url": entry.get("license_url"),
            "citation": _flatten(entry.get("citation")),
            "archive": entry.get("archive"),
            "archive_url": entry.get("archive_url"),
            "tiers": ["high", "low"],
            "exports": exports,
            "processed_at": datetime.now(UTC).isoformat(),
        }
        # Observing spacecraft for mission-tier shapes — links the model to its
        # probe page. Absent for multi-mission/ambiguous bodies (see manifest).
        if entry.get("probe_id") is not None:
            payload["probe_id"] = int(entry["probe_id"])
        if true_scale:
            payload["true_scale"] = true_scale
        out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / "metadata.json").write_text(json.dumps(payload, indent=2))


def _flatten(text: str | None) -> str | None:
    """Collapse a folded-YAML multi-line citation to a single line."""
    if not text:
        return None
    return " ".join(text.split())
