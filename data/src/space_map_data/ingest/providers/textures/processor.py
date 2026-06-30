"""TextureProcessor: drives the per-entry pipelines and DB availability flag."""

import gc
import json
import logging
from datetime import UTC, datetime
from pathlib import Path

import py360convert
import yaml
from PIL import Image

from space_map_data.export.sidecar_io import mirror_path
from space_map_data.models.object import Object
from space_map_data.utils.db import get_session

from . import config, skybox
from .alignment import align_cylindrical, entry_alignment
from .encoding import resize, save_webp, size_target, tier_for_size
from .image_io import open_displacement_source, open_image, open_specular_source
from .metadata import (
    CLOUD_OUTPUT_RE,
    any_export_over_cap,
    cloud_frame_id,
    expand_entry_files,
    refresh_metadata_from_yaml,
    scraped_attribution,
    stale_metadata_reason,
)

log = logging.getLogger(__name__)


class TextureProcessor:
    def __init__(self) -> None:
        main_yaml = config.RAW_DIR.parent / "download-metadata.yaml"
        bodies: list[dict] = yaml.safe_load(main_yaml.read_text())["bodies"]
        for entry in bodies:
            entry["_source_dir"] = config.RAW_DIR

        # Each non-surface asset dir (e.g. star-map/, night/earth/) carries its
        # own download-metadata.yaml with the same schema; entries get stamped
        # with `_source_dir` pointing at the asset dir so the processor finds
        # the file without a global flat-layout move.
        for sub_yaml in sorted(config.iter_extra_asset_yamls()):
            data = yaml.safe_load(sub_yaml.read_text()) or {}
            sub = sub_yaml.parent
            for entry in data.get("bodies") or []:
                entry["_source_dir"] = sub
                bodies.append(entry)

        self._raw_meta: list[dict] = bodies

    def _reset_texture_available(self) -> None:
        session = get_session()
        session.query(Object).update({Object.map_texture_available: False})
        session.commit()

    def _mark_texture_available(self, object_id: str) -> None:
        session = get_session()
        session.query(Object).filter(Object.id == object_id).update(
            {Object.map_texture_available: True}
        )
        session.commit()

    def _export(
        self,
        img: Image.Image,
        object_id: str,
        out_dir: Path,
        filename_suffix: str = "",
    ) -> dict[str, dict]:
        """Export image at applicable sizes; promotes largest to lossless high if source is below the high tier.

        ``filename_suffix`` is appended to each tier name in the on-disk file
        (e.g. ``"_01"`` → ``low_01.webp``); the returned dict is still keyed
        by bare tier name so callers can nest under a frame key.
        """
        w, h = img.size
        capped = min(max(w, h), config.WEBP_MAX)
        # Sizes to export: all EXPORT_SIZES that fit below the cap, plus the cap itself
        sizes = [s for s in config.EXPORT_SIZES if s < capped]
        sizes.append(capped)

        exports: dict[str, dict] = {}

        for size in sizes:
            tier = tier_for_size(size)
            resized = resize(img, size)
            rec = save_webp(
                resized, out_dir / f"{tier}{filename_suffix}.webp", lossless=False
            )
            exports[tier] = rec

            target = size_target(size)
            if target and rec["size_bytes"] > target:
                log.warning(
                    "%s/%s%s.webp: %.0f KiB exceeds %d KiB target",
                    object_id,
                    tier,
                    filename_suffix,
                    rec["size_bytes"] / 1024,
                    target // 1024,
                )

        # If no high was produced (source ≤ 8192), promote the largest export to high
        # as a lossless copy — but only if it's small enough to be worth it
        if "high" not in exports:
            largest_rec = exports[max(exports, key=lambda t: exports[t]["width"])]
            if largest_rec["size_bytes"] < 300 * 1024:
                exports["high"] = save_webp(
                    resize(img, largest_rec["width"]),
                    out_dir / f"high{filename_suffix}.webp",
                    lossless=True,
                )

        return exports

    def _try_skip(
        self,
        out_dir: Path,
        entry: dict,
        *,
        attribution_file: str,
        label: str,
    ) -> bool:
        """Refresh yaml fields and return True if processing can be skipped.

        Returns False when metadata is missing, the entry's shape has
        diverged from the on-disk metadata (monthly frame-count/template
        change, or a fresher clouds snapshot on disk), or any export
        exceeds the file cap. In all other cases yaml-sourced fields are
        patched into the existing metadata.json and the texture is marked
        available.
        """
        meta_path = mirror_path(out_dir / "metadata.json")
        if not meta_path.exists():
            return False

        try:
            existing = json.loads(meta_path.read_text())
        except (OSError, json.JSONDecodeError):
            existing = {}

        reason = stale_metadata_reason(existing, entry)
        if reason:
            log.info("reprocessing %s: %s", label, reason)
            return False

        if any_export_over_cap(out_dir):
            log.info(
                "reprocessing %s: existing export(s) exceed %.1f MiB cap",
                label,
                config.MAX_FILE_BYTES / 1024 / 1024,
            )
            return False

        log.debug("skipping %s (already processed, use force=True to reprocess)", label)
        refresh_metadata_from_yaml(out_dir, entry, attribution_file)
        self._mark_texture_available(entry["body"])
        return True

    def _write_metadata(
        self,
        out_dir: Path,
        entry: dict,
        *,
        source_file: str,
        attribution_file: str,
        source_dims: list[int] | None,
        exports: dict,
        extra_fields: dict | None = None,
    ) -> None:
        """Build and write metadata.json; mark the texture available.

        ``source_file`` is what gets recorded in metadata (the literal raw
        filename or the monthly template); ``attribution_file`` is the
        concrete filename used to look up scraped attribution (the first
        frame for monthly entries).
        """
        self._mark_texture_available(entry["body"])
        attribution = entry.get("attribution") or scraped_attribution(attribution_file)
        metadata: dict = {
            "id": entry["body"],
            "source": entry["source"],
            "organisation": entry["organisation"],
            "attribution": attribution,
            "description": entry.get("description"),
            "type": entry["type"],
            **(extra_fields or {}),
            "source_file": source_file,
            "source_dimensions": source_dims,
            "processed_at": datetime.now(UTC).isoformat(),
            "exports": exports,
        }
        meta_path = mirror_path(out_dir / "metadata.json")
        meta_path.parent.mkdir(parents=True, exist_ok=True)
        meta_path.write_text(json.dumps(metadata, indent=2))

    def process_all(self, force: bool = False) -> None:
        """Process all textures listed in download-metadata.yaml.

        Warns about any image files in RAW_DIR not referenced by the metadata.
        """
        self._reset_texture_available()
        # `known_files` only gates the RAW_DIR untracked-files check below, so
        # we restrict it to entries actually sourced from raw/. misc/ entries
        # have their own per-subdir manifests and aren't expected in raw/.
        known_files: set[str] = set()
        for entry in self._raw_meta:
            if entry.get("_source_dir", config.RAW_DIR) == config.RAW_DIR:
                known_files.update(expand_entry_files(entry))

        for entry in self._raw_meta:
            if entry.get("skip"):
                continue
            if entry.get("type") == "cylindrical_monthly":
                self._process_monthly(entry, force=force)
                continue
            if entry.get("type") == "cylindrical_specular":
                self._process_specular(entry, force=force)
                continue
            if entry.get("type") == "cylindrical_night_lights":
                self._process_night_lights(entry, force=force)
                continue
            if entry.get("type") == "cylindrical_displacement":
                self._process_displacement(entry, force=force)
                continue
            if entry.get("type") == "cubemap_skybox":
                self._process_skybox(entry, force=force)
                continue
            src = entry.get("_source_dir", config.RAW_DIR) / entry["file"]
            if not src.exists():
                log.warning("listed in metadata but not found: %s", entry["file"])
                continue
            self.process(src, force=force)

        self._process_clouds(force=force)

        for f in sorted(config.RAW_DIR.iterdir()):
            if f.suffix.lower() in config.IMAGE_EXTS and f.name not in known_files:
                log.warning("untracked file not in download-metadata.yaml: %s", f.name)

    def process(self, src: Path | str, force: bool = False) -> Path:
        """Process a raw texture into WebP exports.

        Reads body info from raw/download-metadata.yaml.
        Exports are written to PROCESSED_DIR/<object_id>/ alongside a metadata.json.
        Returns the output directory.
        """
        src = Path(src)
        entry = next((b for b in self._raw_meta if b["file"] == src.name), None)
        if entry is None:
            log.warning("%s not found in download-metadata.yaml", src.name)
            return config.PROCESSED_DIR
        if entry.get("skip"):
            log.debug("skipping %s (marked skip in download-metadata.yaml)", src.name)
            return config.PROCESSED_DIR

        object_id = entry["body"]
        out_dir = config.PROCESSED_DIR / object_id

        if not force and self._try_skip(
            out_dir, entry, attribution_file=src.name, label=src.name
        ):
            return out_dir

        out_dir.mkdir(parents=True, exist_ok=True)
        img = open_image(src)
        source_dims = [img.width, img.height]
        img = align_cylindrical(img, **entry_alignment(entry))
        exports = self._export(img, object_id, out_dir)

        self._write_metadata(
            out_dir,
            entry,
            source_file=src.name,
            attribution_file=src.name,
            source_dims=source_dims,
            exports=exports,
            extra_fields={"alignment": entry_alignment(entry)},
        )
        log.info("processed %s → %s (%d exports)", src.name, object_id, len(exports))
        return out_dir

    def _process_specular(self, entry: dict, force: bool = False) -> Path:
        """Process a `cylindrical_specular` entry from a bathymetry source.

        Output goes to ``{body}_specular/`` — a sibling of the surface texture
        and ``_clouds`` bundle. The exported WebP is a single-channel ocean
        mask (land=0, ocean=255); the renderer routes it into whichever
        material slot (roughness, specular intensity) it sees fit.
        """
        src = entry.get("_source_dir", config.RAW_DIR) / entry["file"]
        if not src.exists():
            log.warning("specular source missing: %s", entry["file"])
            return config.PROCESSED_DIR

        object_id = f"{entry['body']}{config.SPECULAR_SUFFIX}"
        out_dir = config.PROCESSED_DIR / object_id

        # Helpers (`_try_skip`, `_write_metadata`, `_mark_texture_available`)
        # all key off entry["body"]. Override it to the suffixed export id so
        # the on-disk metadata.json's `id` matches the directory — same
        # convention `_process_clouds` uses for `naif-399_clouds`. The DB
        # update for `naif-399_specular` is a harmless no-op (no such row).
        entry = {**entry, "body": object_id}

        if not force and self._try_skip(
            out_dir, entry, attribution_file=src.name, label=object_id
        ):
            return out_dir

        out_dir.mkdir(parents=True, exist_ok=True)
        img = open_specular_source(src)
        source_dims = [img.width, img.height]
        img = align_cylindrical(img, **entry_alignment(entry))
        exports = self._export(img, object_id, out_dir)

        self._write_metadata(
            out_dir,
            entry,
            source_file=src.name,
            attribution_file=src.name,
            source_dims=source_dims,
            exports=exports,
            extra_fields={"alignment": entry_alignment(entry)},
        )
        log.info(
            "processed specular %s → %s (%d exports)", src.name, object_id, len(exports)
        )
        return out_dir

    def _process_night_lights(self, entry: dict, force: bool = False) -> Path:
        """Process a `cylindrical_night_lights` entry — emissive sibling.

        Output goes to ``{body}_night/`` — a sibling of the surface texture,
        same single-frame shape as ``_specular``. The image is treated as a
        plain RGB cylindrical map; the renderer samples it as an emissive
        contribution multiplied by the body's unlit fraction.
        """
        src = entry.get("_source_dir", config.RAW_DIR) / entry["file"]
        if not src.exists():
            log.warning("night-lights source missing: %s", entry["file"])
            return config.PROCESSED_DIR

        object_id = f"{entry['body']}{config.NIGHT_SUFFIX}"
        out_dir = config.PROCESSED_DIR / object_id

        # Helpers key off entry["body"]; override to the suffixed export id so
        # the on-disk metadata.json's `id` matches the directory — same trick
        # `_process_specular` and `_process_clouds` use.
        entry = {**entry, "body": object_id}

        if not force and self._try_skip(
            out_dir, entry, attribution_file=src.name, label=object_id
        ):
            return out_dir

        out_dir.mkdir(parents=True, exist_ok=True)
        img = open_image(src)
        source_dims = [img.width, img.height]
        img = align_cylindrical(img, **entry_alignment(entry))
        exports = self._export(img, object_id, out_dir)

        self._write_metadata(
            out_dir,
            entry,
            source_file=src.name,
            attribution_file=src.name,
            source_dims=source_dims,
            exports=exports,
            extra_fields={"alignment": entry_alignment(entry)},
        )
        log.info(
            "processed night-lights %s → %s (%d exports)",
            src.name,
            object_id,
            len(exports),
        )
        return out_dir

    def _process_displacement(self, entry: dict, force: bool = False) -> Path:
        """Process a `cylindrical_displacement` entry — height-map sibling.

        Output goes to ``{body}_displacement/`` (single-frame, like ``_specular``).
        Records the km at texel 0/255 so the renderer scales displacement true.
        """
        src = entry.get("_source_dir", config.RAW_DIR) / entry["file"]
        if not src.exists():
            log.warning("displacement source missing: %s", entry["file"])
            return config.PROCESSED_DIR

        object_id = f"{entry['body']}{config.DISPLACEMENT_SUFFIX}"
        out_dir = config.PROCESSED_DIR / object_id

        # Helpers key off entry["body"]; override to the suffixed export id so
        # the on-disk metadata.json's `id` matches the directory — same trick
        # `_process_specular` and `_process_night_lights` use.
        entry = {**entry, "body": object_id}

        if not force and self._try_skip(
            out_dir, entry, attribution_file=src.name, label=object_id
        ):
            return out_dir

        out_dir.mkdir(parents=True, exist_ok=True)
        img, elev_min_km, elev_max_km = open_displacement_source(
            src,
            unit=entry.get("height_unit", "m"),
            scale=entry.get("height_scale"),
            offset=entry.get("height_offset"),
            nodata=entry.get("height_nodata"),
        )
        source_dims = [img.width, img.height]
        img = align_cylindrical(img, **entry_alignment(entry))
        exports = self._export(img, object_id, out_dir)

        self._write_metadata(
            out_dir,
            entry,
            source_file=src.name,
            attribution_file=src.name,
            source_dims=source_dims,
            exports=exports,
            extra_fields={
                "alignment": entry_alignment(entry),
                # Value km = bias + scale·texel. For absolute_radius grids the
                # renderer subtracts its sphere radius and skips triaxial.
                "displacement_bias_km": elev_min_km,
                "displacement_scale_km": elev_max_km - elev_min_km,
                "absolute_radius": bool(entry.get("absolute_radius", False)),
            },
        )
        log.info(
            "processed displacement %s → %s (%d exports, %.2f..%.2f km)",
            src.name,
            object_id,
            len(exports),
            elev_min_km,
            elev_max_km,
        )
        return out_dir

    def _process_skybox(self, entry: dict, force: bool = False) -> Path:
        """Process a ``cubemap_skybox`` entry from an HDR equirectangular EXR.

        Loads the source EXR linear-light, applies an exposure-bumped Reinhard
        tonemap, projects to six cubemap faces (px, nx, py, ny, pz, nz) at
        each tier size, and writes one lossy WebP per face per tier:
        ``{tier}_{face}.webp`` under ``PROCESSED_DIR/<body>/``. A single
        metadata.json records the face list, tier sizes, and per-file size
        records (nested ``{tier: {face: rec}}``).

        Skip semantics mirror the other processors: ``_try_skip`` short-
        circuits when metadata exists, the entry shape is unchanged, and no
        export exceeds the size cap.
        """
        src = entry.get("_source_dir", config.RAW_DIR) / entry["file"]
        if not src.exists():
            log.warning("skybox source missing: %s", entry["file"])
            return config.PROCESSED_DIR

        object_id = entry["body"]
        out_dir = config.PROCESSED_DIR / object_id

        if not force and self._try_skip(
            out_dir, entry, attribution_file=src.name, label=f"{object_id} skybox"
        ):
            return out_dir

        # Pre-flight: the streaming loader downsamples to ~384 MiB and
        # py360convert's 4K-per-face cubemap working set adds another ~1 GiB;
        # 2 GiB available is comfortable headroom. (The earlier whole-image
        # imageio load needed 30+ GiB and would OOM-kill the process.)
        SKYBOX_MIN_AVAILABLE_BYTES = 2 * 1024 * 1024 * 1024  # 2 GiB
        avail = skybox.mem_available_bytes()
        if avail is not None and avail < SKYBOX_MIN_AVAILABLE_BYTES:
            log.error(
                "skybox %s: insufficient memory (%.1f GiB available, need ≥%d GiB); "
                "close other apps and rerun",
                object_id,
                avail / 1024**3,
                SKYBOX_MIN_AVAILABLE_BYTES / 1024**3,
            )
            return config.PROCESSED_DIR

        out_dir.mkdir(parents=True, exist_ok=True)

        log.info("loading + tonemapping skybox EXR %s (streaming)…", src.name)
        ldr_equirect = skybox.load_and_tonemap_streaming(src)
        h, w, _ = ldr_equirect.shape
        # Source dims for metadata are the *original* EXR dimensions, not the
        # downsampled working buffer — record both via the explicit factor.
        src_w = w * config.SKYBOX_DOWNSAMPLE
        src_h = h * config.SKYBOX_DOWNSAMPLE
        gc.collect()

        exports: dict[str, dict[str, dict]] = {}
        high_size = config.SKYBOX_TIER_SIZES["high"]
        log.info("extracting cubemap faces at %dpx (high tier)…", high_size)
        # Single e2c pass at high tier; downsample for lower tiers below.
        raw_faces = py360convert.e2c(
            ldr_equirect, face_w=high_size, mode="bilinear", cube_format="dict"
        )
        # Remap py360convert's F/R/B/L/U/D keys to WebGL axis labels.
        high_faces = {config.PY360_TO_FACE[k]: v for k, v in raw_faces.items()}
        del ldr_equirect, raw_faces
        gc.collect()

        for tier, face_size in config.SKYBOX_TIER_SIZES.items():
            tier_exports: dict[str, dict] = {}
            for face in config.SKYBOX_FACES:
                img = Image.fromarray(high_faces[face], mode="RGB")
                if face_size != high_size:
                    img = img.resize((face_size, face_size), Image.Resampling.LANCZOS)
                rec = save_webp(img, out_dir / f"{tier}_{face}.webp", lossless=False)
                tier_exports[face] = rec

                target = size_target(face_size)
                if target and rec["size_bytes"] > target:
                    log.warning(
                        "%s/%s_%s.webp: %.0f KiB exceeds %d KiB target",
                        object_id,
                        tier,
                        face,
                        rec["size_bytes"] / 1024,
                        target // 1024,
                    )
            exports[tier] = tier_exports
        del high_faces
        gc.collect()

        self._write_metadata(
            out_dir,
            entry,
            source_file=src.name,
            attribution_file=src.name,
            source_dims=[src_w, src_h],
            exports=exports,
            extra_fields={
                "encoding": "webp",
                "frame": "j2000",
                "faces": list(config.SKYBOX_FACES),
                "tiers": list(config.SKYBOX_TIER_SIZES),
                "tier_face_size": dict(config.SKYBOX_TIER_SIZES),
                "exposure": config.SKYBOX_EXPOSURE,
                "working_equirect_size": [w, h],
                "downsample_from_source": config.SKYBOX_DOWNSAMPLE,
            },
        )
        log.info(
            "processed skybox %s → %s (%d faces × %d tiers)",
            src.name,
            object_id,
            len(config.SKYBOX_FACES),
            len(config.SKYBOX_TIER_SIZES),
        )
        return out_dir

    def _process_monthly(self, entry: dict, force: bool = False) -> Path:
        """Process a ``cylindrical_monthly`` entry: one body, ``months`` frames.

        Each frame's tier files land as ``{tier}_{NN}.webp`` in the body's
        directory; one ``metadata.json`` records all of them with ``exports``
        keyed by zero-padded month string.

        Skip semantics mirror ``process()``: if metadata exists and no export
        exceeds the file cap, the image work is skipped and only the
        yaml-sourced fields are refreshed. Use ``force=True`` to redo the
        webp encoding (e.g. after changing tier sizes).
        """
        object_id = entry["body"]
        out_dir = config.PROCESSED_DIR / object_id
        months = entry.get("months", 12)
        file_template = entry["file"]
        expected_files = expand_entry_files(entry)
        source_dir: Path = entry.get("_source_dir", config.RAW_DIR)

        missing = [f for f in expected_files if not (source_dir / f).exists()]
        if missing:
            for f in missing:
                log.warning("monthly source missing: %s", f)
            if len(missing) == months:
                # Nothing to process at all; bail before touching out_dir.
                return config.PROCESSED_DIR

        if not force and self._try_skip(
            out_dir,
            entry,
            attribution_file=expected_files[0],
            label=f"{object_id} monthly",
        ):
            return out_dir

        out_dir.mkdir(parents=True, exist_ok=True)

        # Strip prior flat-layout outputs (low/medium/high.webp) when migrating
        # a body from a single-frame entry to a monthly one. Leaving them
        # around would ship stale assets the renderer might pick up.
        for stale in ("low.webp", "medium.webp", "high.webp"):
            stale_path = out_dir / stale
            if stale_path.exists():
                stale_path.unlink()
                log.info("removed stale single-frame export %s", stale_path.name)

        all_exports: dict[str, dict[str, dict]] = {}
        source_dims: list[int] | None = None

        align = entry_alignment(entry)
        for m in range(1, months + 1):
            fname = file_template.format(month=m)
            src = source_dir / fname
            if not src.exists():
                continue
            img = open_image(src)
            if source_dims is None:
                source_dims = [img.width, img.height]
            img = align_cylindrical(img, **align)
            suffix = f"_{m:02d}"
            exports = self._export(img, object_id, out_dir, suffix)
            all_exports[f"{m:02d}"] = exports

        if not all_exports:
            # Every source was missing — we logged per-file warnings above.
            return out_dir

        tier_count = len(next(iter(all_exports.values())))
        self._write_metadata(
            out_dir,
            entry,
            source_file=file_template,
            attribution_file=expected_files[0],
            source_dims=source_dims,
            exports=all_exports,
            extra_fields={"frames": months, "alignment": align},
        )
        log.info(
            "processed %s → %s monthly (%d frames × %d tiers)",
            file_template,
            object_id,
            len(all_exports),
            tier_count,
        )
        return out_dir

    def _process_clouds(self, force: bool = False) -> None:
        """Dispatch each entry in ``CLOUD_SOURCES`` to the timeseries or static path.

        Per-body cloud sources live under ``CLOUDS_DIR/<name>/``; the name
        maps to a NAIF body id, and the processed bundle lands at
        ``PROCESSED_DIR/<body_id>_clouds/``. Directories with image files at
        the top level are treated as a single static texture (e.g. Venus);
        directories holding a date tree of snapshots go through the
        timeseries path (e.g. Earth).
        """
        for subdir_name, body_id in config.CLOUD_SOURCES.items():
            src_dir = config.CLOUDS_DIR / subdir_name
            if not src_dir.exists():
                log.debug("clouds: %s does not exist, skipping", src_dir)
                continue
            top_images = [
                p
                for p in src_dir.iterdir()
                if p.is_file() and p.suffix.lower() in config.IMAGE_EXTS
            ]
            if top_images:
                self._process_clouds_static(body_id, src_dir, top_images, force=force)
            else:
                self._process_clouds_timeseries(body_id, src_dir, force=force)

    def _process_clouds_timeseries(
        self, body_id: str, src_dir: Path, force: bool = False
    ) -> Path:
        """Process a date-tree of cloud-cover snapshots into per-frame WebP exports.

        Walks every PNG under ``src_dir`` (a ``YYYY/MM/DD/HH.png`` tree
        written by a snapshot downloader), derives a sortable
        ``YYYYMMDDHH`` frame id from each path, and exports as
        ``{tier}_{frame_id}.webp`` under ``{body_id}_clouds/``. A single
        top-level metadata.json carries the union of frames; per-frame
        ``size_bytes`` / ``source_file`` are intentionally omitted — they'd
        just repeat across thousands of snapshots.

        Skip semantics: if the existing metadata's ``frames`` list matches
        the on-disk PNG inventory, the image work is a no-op. Otherwise,
        only frames whose low-tier output is missing are re-encoded and
        outputs for vanished snapshots are deleted. ``force=True``
        re-encodes every frame.
        """
        pngs = sorted(src_dir.rglob("*.png"))
        if not pngs:
            log.warning("no cloud snapshots in %s", src_dir)
            return config.PROCESSED_DIR

        inputs: list[tuple[str, Path]] = []
        seen: set[str] = set()
        for p in pngs:
            fid = cloud_frame_id(p)
            if fid is None:
                log.warning(
                    "cloud snapshot at unexpected path: %s",
                    p.relative_to(src_dir).as_posix(),
                )
                continue
            if fid in seen:
                continue
            seen.add(fid)
            inputs.append((fid, p))
        target_frames = [fid for fid, _ in inputs]

        object_id = config.clouds_object_id(body_id)
        out_dir = config.PROCESSED_DIR / object_id
        meta_path = mirror_path(out_dir / "metadata.json")

        download_meta_path = src_dir / "metadata.json"
        download_meta: dict = {}
        if download_meta_path.exists():
            try:
                download_meta = json.loads(download_meta_path.read_text())
            except (OSError, json.JSONDecodeError):
                log.warning(
                    "failed to read clouds download metadata at %s", download_meta_path
                )

        if not force and meta_path.exists():
            try:
                existing = json.loads(meta_path.read_text())
            except (OSError, json.JSONDecodeError):
                existing = {}
            if existing.get("frames") == target_frames:
                log.debug(
                    "skipping clouds (already processed %d frames, use force=True to reprocess)",
                    len(target_frames),
                )
                self._mark_texture_available(object_id)
                return out_dir

        out_dir.mkdir(parents=True, exist_ok=True)

        # Drop outputs for frames the downloader no longer has on disk so
        # the bundle doesn't accumulate ghost snapshots.
        target_set = set(target_frames)
        for f in out_dir.glob("*.webp"):
            m = CLOUD_OUTPUT_RE.match(f.name)
            if not m:
                continue
            if m.group(2) not in target_set:
                f.unlink()
                log.info("removed stale cloud frame %s", f.name)

        tiers: list[str] = []
        for fid, src in inputs:
            suffix = f"_{fid}"
            if not force and (out_dir / f"low{suffix}.webp").exists():
                # Existing output covers this frame; tier discovery falls to
                # any frame we actually encode (they share dims, so tiers
                # match), or the post-loop fallback below.
                continue
            img = open_image(src)
            exports = self._export(img, object_id, out_dir, suffix)
            if not tiers:
                tiers = sorted(exports.keys())

        # Every frame was already on disk — recover the tier list from one
        # of the existing outputs so the metadata stays accurate.
        if not tiers and target_frames:
            first_fid = target_frames[0]
            tiers = sorted(
                t
                for t in ("low", "medium", "high")
                if (out_dir / f"{t}_{first_fid}.webp").exists()
            )

        self._mark_texture_available(object_id)
        metadata: dict = {
            "id": object_id,
            "source": download_meta.get("source_url", ""),
            "organisation": "EUMETSAT",
            "attribution": download_meta.get("attribution"),
            "description": "Near-real-time cloud-cover overlay (3-hour cadence).",
            "type": "clouds_overlay",
            "tiers": tiers,
            "frames": target_frames,
            "processed_at": datetime.now(UTC).isoformat(),
        }
        meta_path.parent.mkdir(parents=True, exist_ok=True)
        meta_path.write_text(json.dumps(metadata, indent=2))
        log.info(
            "processed clouds → %s (%d frames × %d tiers)",
            object_id,
            len(target_frames),
            len(tiers),
        )
        return out_dir

    def _process_clouds_static(
        self,
        body_id: str,
        src_dir: Path,
        images: list[Path],
        force: bool = False,
    ) -> Path:
        """Process a single static cloud texture into ``{tier}_static.webp`` exports.

        ``src_dir`` holds one cylindrical image plus a ``metadata.json``
        sidecar from the downloader (source URL, attribution, description).
        The output mirrors the timeseries layout — same URL template
        ``{tier}_{frame}.webp`` — using ``"static"`` as the sentinel frame
        id so the frontend's cloud loader needs no special-case branch.
        """
        if len(images) > 1:
            log.warning(
                "static clouds %s: expected 1 image, found %d (using %s)",
                src_dir,
                len(images),
                images[0].name,
            )
        src = images[0]

        object_id = config.clouds_object_id(body_id)
        out_dir = config.PROCESSED_DIR / object_id
        meta_path = mirror_path(out_dir / "metadata.json")

        download_meta_path = src_dir / "metadata.json"
        download_meta: dict = {}
        if download_meta_path.exists():
            try:
                download_meta = json.loads(download_meta_path.read_text())
            except (OSError, json.JSONDecodeError):
                log.warning(
                    "failed to read clouds download metadata at %s", download_meta_path
                )

        if not force and meta_path.exists() and (out_dir / "low_static.webp").exists():
            log.debug(
                "skipping static clouds %s (already processed, use force=True to reprocess)",
                object_id,
            )
            self._mark_texture_available(object_id)
            return out_dir

        out_dir.mkdir(parents=True, exist_ok=True)
        img = open_image(src)
        source_dims = [img.width, img.height]
        exports = self._export(img, object_id, out_dir, filename_suffix="_static")
        tiers = sorted(exports.keys())

        self._mark_texture_available(object_id)
        organisation, description = config.CLOUDS_STATIC_META.get(
            body_id, ("Unknown", "Cloud overlay.")
        )
        metadata: dict = {
            "id": object_id,
            "source": download_meta.get("source_url", ""),
            "organisation": organisation,
            "attribution": download_meta.get("attribution"),
            "description": description,
            "type": "clouds_overlay",
            "tiers": tiers,
            "frames": ["static"],
            "source_file": src.name,
            "source_dimensions": source_dims,
            "processed_at": datetime.now(UTC).isoformat(),
        }
        meta_path.parent.mkdir(parents=True, exist_ok=True)
        meta_path.write_text(json.dumps(metadata, indent=2))
        log.info(
            "processed static clouds %s → %s (%d tiers)",
            src.name,
            object_id,
            len(tiers),
        )
        return out_dir
