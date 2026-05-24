"""ModelProcessor: read 3D manifests, convert + optimise, emit per-slug glTF bundles.

Mirrors ``TextureProcessor`` in shape: reset DB pointer → walk manifests →
per entry, ``_try_skip`` against the on-disk metadata.json → otherwise
convert + optimise → write metadata.json + point each mission's
``Object.model_name`` at the slug.

Each manifest entry produces one bundle under ``EXPORT_DIR/v1/models/{slug}/``.
The slug is the user-facing name for the model on disk and on the DB rows
that point at it; many missions may share a single slug (Viking 1/2
orbiter, Cluster II constellation). Slugs are unique across all catalogs —
collisions are a hard error.

Source ladder:
- ``.glb`` source — passes straight to gltf-transform.
- ``.fbx``/``.blend``/``.obj``/``.3ds`` — Blender headless → intermediate
  ``.glb`` → gltf-transform.

External deps (Blender + ``@gltf-transform/cli``) are optional: missing
deps are logged once at startup, and unconvertible entries are skipped.
"""

import json
import logging
import shutil
import subprocess
import tempfile
import zipfile
from collections import defaultdict
from datetime import UTC, datetime
from pathlib import Path

from ruamel.yaml import YAML
from tqdm import tqdm

from space_map_data.export.sidecar_io import mirror_path
from space_map_data.ingest.providers.models import config, conversion, metadata
from space_map_data.models.object import Object
from space_map_data.utils.db import get_session

log = logging.getLogger(__name__)

_yaml = YAML()
_yaml.preserve_quotes = True
_yaml.width = 4096  # don't reflow long URLs/notes


class SlugConflictError(RuntimeError):
    """Two manifest entries share the same slug — names must be globally unique."""


class ModelProcessor:
    def __init__(self) -> None:
        self._yaml_docs: list[tuple[Path, dict]] = []
        self._global_warnings: list[str] = []
        self._has_blender = conversion.blender_available()
        self._has_gltf_transform = conversion.gltf_transform_available()
        if not self._has_blender:
            log.warning(
                "blender not on PATH — .fbx/.blend/.obj/.3ds models will be skipped. "
                "Install Blender to convert non-glTF sources."
            )
        if not self._has_gltf_transform:
            log.warning(
                "gltf-transform CLI not on PATH — models will be copied verbatim "
                "without Meshopt/WebP compression. `pnpm i -g @gltf-transform/cli` "
                "(or rely on npx) to enable."
            )

    def process_all(self, force: bool = False) -> None:
        self._global_warnings = []
        self._load_manifests()
        self._check_slug_uniqueness()
        self._reset_model_pointer()

        # Build the mission_id → slug map *before* doing any conversion work:
        # the first slug to claim a mission wins, and the assignment is what
        # we'll write to the DB at the end. Future-work TODO: explicit per-
        # mission winner selection when several slugs depict the same mission
        # (e.g. "cassini-with-huygens" vs "cassini").
        mission_winners = self._assign_mission_winners()

        all_entries: list[tuple[Path, dict]] = [
            (yaml_path, entry)
            for yaml_path, doc in self._yaml_docs
            for entry in doc.get("entries") or []
        ]
        for yaml_path, entry in tqdm(all_entries, desc="3D models", unit="entry"):
            self._process_entry(entry, yaml_path, force=force)

        self._write_mission_pointers(mission_winners)

        warnings_file = config.MODELS_DOWNLOAD_DIR / "warnings.json"
        warnings_file.write_text(json.dumps(self._global_warnings, indent=2))
        if self._global_warnings:
            log.warning(
                "%d model warning(s) — see %s",
                len(self._global_warnings),
                warnings_file,
            )

    def _load_manifests(self) -> None:
        """Discover every 3D manifest under ``MODELS_DOWNLOAD_DIR``."""
        self._yaml_docs = []
        if config.NASA_MANIFEST.exists():
            self._yaml_docs.append(
                (config.NASA_MANIFEST, _yaml.load(config.NASA_MANIFEST.read_text()))
            )
        else:
            log.info("no NASA manifest at %s", config.NASA_MANIFEST)
        if config.ESA_DIR.exists():
            for sub in sorted(config.ESA_DIR.iterdir()):
                meta = sub / "metadata.yaml"
                if meta.is_file():
                    self._yaml_docs.append((meta, _yaml.load(meta.read_text())))

    def _check_slug_uniqueness(self) -> None:
        """Hard-fail if two entries (any catalog) share a slug.

        Slugs name the on-disk model dir and are the value the DB's
        ``model_name`` column points at; collisions would silently overwrite
        each other's GLBs.
        """
        seen: dict[str, Path] = {}
        for yaml_path, doc in self._yaml_docs:
            for entry in doc.get("entries") or []:
                slug = entry.get("slug")
                if not slug:
                    continue
                prior = seen.get(slug)
                if prior is not None:
                    raise SlugConflictError(
                        f"slug {slug!r} declared in both {prior} and {yaml_path}"
                    )
                seen[slug] = yaml_path

    def _assign_mission_winners(self) -> dict[str, str]:
        """Build {object_id: slug} for every mission across all manifests.

        When a single mission has multiple candidate slugs (e.g.
        ``cassini-with-huygens`` and ``cassini``), the first one encountered
        in iteration order wins. TODO: replace with an explicit canonical
        flag in the manifest once we know how the frontend wants to pick.
        """
        candidates: dict[str, list[str]] = defaultdict(list)
        for _yaml_path, doc in self._yaml_docs:
            for entry in doc.get("entries") or []:
                slug = entry.get("slug")
                if not slug:
                    continue
                for mission in entry.get("missions") or []:
                    oid = metadata.resolve_mission_object_id(mission)
                    if oid is None:
                        continue
                    candidates[oid].append(slug)

        winners: dict[str, str] = {}
        for oid, slugs in candidates.items():
            winners[oid] = slugs[0]
            if len(slugs) > 1:
                log.warning(
                    "mission %s has multiple model slugs %s — picking %s "
                    "(TODO: explicit canonical selection)",
                    oid,
                    slugs,
                    slugs[0],
                )
        return winners

    def _reset_model_pointer(self) -> None:
        session = get_session()
        session.query(Object).update({Object.model_name: None})
        session.commit()

    def _write_mission_pointers(self, winners: dict[str, str]) -> None:
        """Write the resolved ``model_name`` pointer for every mission winner.

        Missing object_ids (mission resolved but no DB row) are silently
        skipped — the .update() on an empty filter is a no-op. Hand-authored
        manifests like Cluster II's NORAD list often include decayed
        satellites with no DB presence; we don't want to break ingest for
        catalog-authoring drift.
        """
        session = get_session()
        for oid, slug in winners.items():
            session.query(Object).filter(Object.id == oid).update(
                {Object.model_name: slug}
            )
        session.commit()

    def _process_entry(self, entry: dict, yaml_path: Path, *, force: bool) -> None:
        slug = entry.get("slug")
        if not slug:
            self._global_warnings.append(
                f"{yaml_path.name}: entry without slug — skipping"
            )
            return

        high_src, low_src = metadata.pick_tier_sources(entry.get("files") or [])
        if high_src is None:
            msg = f"{slug}: no convertible file in entry (have: {[m.get('type') for m in entry.get('files') or []]})"
            log.info(msg)
            self._global_warnings.append(msg)
            return

        source_root = config.MODELS_DOWNLOAD_DIR
        high_path = source_root / high_src["path"]
        high_type: str = high_src["type"]
        if not high_path.exists():
            self._global_warnings.append(f"{slug}: missing source {high_src['path']}")
            return
        if high_type != "glb" and not self._has_blender:
            log.info(
                "skipping %s: high source is .%s but Blender is missing",
                slug,
                high_type,
            )
            return

        # When the manifest supplies a hand-authored low tier, validate it and
        # carry path+type as one item so the downstream call site doesn't have
        # to re-check the None-ness of two parallel variables.
        low: tuple[Path, str] | None = None
        if low_src is not None:
            candidate = source_root / low_src["path"]
            low_type: str = low_src["type"]
            if not candidate.exists():
                self._global_warnings.append(
                    f"{slug}: missing low source {low_src['path']}"
                )
            elif low_type != "glb" and not self._has_blender:
                pass  # Blender absent → synthesise low from high downstream
            else:
                low = (candidate, low_type)

        out_dir = config.PROCESSED_DIR / slug
        meta_path = mirror_path(out_dir / "metadata.json")

        source_hashes = {"high": metadata.sha256_file(high_path)}
        if low is not None:
            source_hashes["low"] = metadata.sha256_file(low[0])

        if not force and self._try_skip(meta_path, source_hashes):
            return

        try:
            high_glb, low_glb = self._build_tiers(
                slug=slug,
                high_path=high_path,
                high_type=high_type,
                low=low,
                out_dir=out_dir,
            )
        except subprocess.CalledProcessError as exc:
            stderr = (exc.stderr or "")[-500:]
            self._global_warnings.append(
                f"{slug}: conversion failed ({exc.cmd[0]}): {stderr}"
            )
            log.error("conversion failed for %s: %s", slug, stderr)
            return

        exports = self._export_record(high_glb, low_glb)
        attribution = self._attribution(yaml_path)
        self._write_metadata(
            out_dir=out_dir,
            slug=slug,
            entry=entry,
            attribution=attribution,
            exports=exports,
            source_hashes=source_hashes,
        )
        log.info("processed %s", slug)

    def _try_skip(self, meta_path: Path, source_hashes: dict[str, str]) -> bool:
        if not meta_path.exists():
            return False
        try:
            existing = json.loads(meta_path.read_text())
        except (OSError, json.JSONDecodeError):
            return False
        if existing.get("schema") != config.SCHEMA_VERSION:
            return False
        if existing.get("source_hashes") != source_hashes:
            return False
        return True

    def _build_tiers(
        self,
        *,
        slug: str,
        high_path: Path,
        high_type: str,
        low: tuple[Path, str] | None,
        out_dir: Path,
    ) -> tuple[Path, Path | None]:
        """Produce ``out_dir/high.glb`` (always) and ``out_dir/low.glb`` (optional)."""
        out_dir.mkdir(parents=True, exist_ok=True)
        high_glb_final = out_dir / "high.glb"
        low_glb_final: Path | None = out_dir / "low.glb"

        # tmpdir is under DOWNLOAD_DIR (not /tmp) so Flatpak'd Blender can
        # see and write into it — see _to_glb's comment.
        tmp_root = config.MODELS_DOWNLOAD_DIR / ".staging"
        tmp_root.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(
            prefix=f"smd-model-{slug}-", dir=tmp_root
        ) as tmp_str:
            tmp = Path(tmp_str)
            high_intermediate = (
                high_path
                if high_type == "glb"
                else self._to_glb(high_path, tmp / "high_in.glb")
            )
            self._optimize(high_intermediate, high_glb_final, tier="high")

            if low is not None:
                low_path, low_type = low
                low_intermediate = (
                    low_path
                    if low_type == "glb"
                    else self._to_glb(low_path, tmp / "low_in.glb")
                )
                self._optimize(low_intermediate, low_glb_final, tier="low")
            elif self._has_gltf_transform:
                self._optimize(high_glb_final, low_glb_final, tier="low")
            else:
                low_glb_final = None  # no compressor, no low tier

        return high_glb_final, low_glb_final

    def _to_glb(self, src: Path, dst: Path) -> Path:
        """Convert ``src`` to ``dst`` via Blender, staging textures.zip if present.

        ESA SciFleet sources ship as ``foo.fbx`` + ``foo_textures.zip``; the
        FBX references texture filenames that only resolve when ``textures/``
        sits alongside the .fbx (Blender's FBX import walks the source's
        directory for relative paths). Stage source + extracted textures
        into a tmpdir before invoking Blender.

        Staging lives under ``DOWNLOAD_DIR`` rather than ``/tmp`` because
        Flatpak'd Blender mounts its own ``/tmp`` — host ``/tmp`` paths are
        invisible to it. ``DOWNLOAD_DIR`` is under ``$HOME`` which Flatpak
        manifests typically expose via ``--filesystem=host``.
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

    def _optimize(self, src: Path, dst: Path, *, tier: str) -> None:
        if self._has_gltf_transform:
            conversion.gltf_transform_optimize(src, dst, tier=tier)
        else:
            # No optimiser — pass through verbatim. The .glb won't be Meshopt/
            # WebP-compressed, but it's still loadable by Three.js' GLTFLoader.
            shutil.copyfile(src, dst)

    def _export_record(self, high_glb: Path, low_glb: Path | None) -> dict[str, dict]:
        exports: dict[str, dict] = {
            "high": {
                "size_bytes": high_glb.stat().st_size,
                "sha256": metadata.sha256_file(high_glb),
            }
        }
        if low_glb is not None and low_glb.exists():
            exports["low"] = {
                "size_bytes": low_glb.stat().st_size,
                "sha256": metadata.sha256_file(low_glb),
            }
        return exports

    def _attribution(self, yaml_path: Path) -> str | None:
        """Resolve an attribution string for a manifest doc.

        ESA per-directory manifests have ``source.attribution`` at the top.
        NASA's single manifest's source block lacks one; the repo's overall
        license (NASA Image Use) is what `_MODEL_SOURCES` in the credits
        writer keys off — return "NASA" so the catalog match works.
        """
        for path, doc in self._yaml_docs:
            if path != yaml_path:
                continue
            attr = (doc.get("source") or {}).get("attribution")
            if isinstance(attr, str):
                return attr
            if (doc.get("source") or {}).get("name") == "NASA-3D-Resources":
                return "NASA"
        return None

    def _write_metadata(
        self,
        *,
        out_dir: Path,
        slug: str,
        entry: dict,
        attribution: str | None,
        exports: dict[str, dict],
        source_hashes: dict[str, str],
    ) -> None:
        out_dir.mkdir(parents=True, exist_ok=True)
        meta = {
            "slug": slug,
            "schema": config.SCHEMA_VERSION,
            "attribution": attribution,
            "tiers": sorted(exports.keys()),
            "exports": exports,
            "source_hashes": source_hashes,
            "processed_at": datetime.now(UTC).isoformat(),
        }
        meta_path = mirror_path(out_dir / "metadata.json")
        meta_path.parent.mkdir(parents=True, exist_ok=True)
        meta_path.write_text(json.dumps(meta, indent=2))
