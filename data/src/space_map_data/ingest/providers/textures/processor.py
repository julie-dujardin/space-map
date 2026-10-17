"""TextureProcessor: drives the per-entry pipelines and DB availability flag."""

import gc
import hashlib
import json
import logging
import shutil
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from functools import cached_property
from pathlib import Path

import numpy as np
import py360convert
from PIL import Image

from space_map_data.constants.manifests.textures import (
    TILES_ONLY,
    builds_tiers,
    layer_files,
    layer_grid,
    load_entries,
    month_layers,
    rank_by_body,
)
from space_map_data.export.sidecar_io import mirror_path
from space_map_data.models.object import Object
from space_map_data.utils.db import get_session
from space_map_data.utils.paths import SOURCES_TEXTURES_DIR

from . import config, deshade, patches, skybox, tiles
from .alignment import align_cylindrical, entry_alignment
from .encoding import resize, save_webp, size_target, tier_for_size
from .image_io import (
    open_displacement_source,
    open_height_raster,
    open_image,
    open_specular_source,
)
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


def _height_fields(entry: dict, layer: dict) -> dict:
    """How the samples of a height raster are read: the file's own statement,
    unless the patch's file or the entry says otherwise. A file that fills
    its gaps from a coarser model also gives the side of its blocks."""
    fields = {
        "unit": layer.get("height_unit") or entry.get("height_unit") or "m",
        **{
            key: layer.get(f"height_{key}", entry.get(f"height_{key}"))
            for key in ("scale", "offset", "nodata")
        },
    }
    # The fields are part of the version of a patch. Other files keep theirs.
    if layer.get("fill_block"):
        fields["fill_block"] = layer["fill_block"]
    return fields


def _height_signature(fields: dict) -> dict:
    """The fields of a height raster as part of a version. A file with fill
    also counts how its fill is read."""
    if "fill_block" in fields:
        return {**fields, "fill_recipe": tiles.FILL_RECIPE}
    return fields


def _described_files(names: list[str]) -> dict:
    """A layer's files for the descriptor: listed, or counted past a few."""
    if len(names) <= 16:
        return {"files": names}
    return {"file_count": len(names), "first_file": names[0], "last_file": names[-1]}


# The sibling layers that get a tile pyramid, by entry type. Clouds do not:
# they are a time series at a resolution the tiers already hold.
_TILED_SIBLINGS = {
    "cylindrical_displacement": config.DISPLACEMENT_SUFFIX,
    "cylindrical_specular": config.SPECULAR_SUFFIX,
    "cylindrical_night_lights": config.NIGHT_SUFFIX,
}


def _coverage_runs(slots: list[str]) -> list[list[str]]:
    """``[first, last]`` slot id for each contiguous run of snapshots.

    Built from every slot on disk, repeats included: a frozen upstream still
    describes that time, it just doesn't change the picture. Only a missing
    slot breaks a run, which is what the renderer must not hold a frame across.
    """
    step = timedelta(hours=config.CLOUDS_SLOT_HOURS)
    runs: list[list[str]] = []
    previous: datetime | None = None
    for fid in slots:
        moment = datetime.strptime(fid, "%Y%m%d%H").replace(tzinfo=UTC)
        if previous is not None and moment - previous == step:
            runs[-1][1] = fid
        else:
            runs.append([fid, fid])
        previous = moment
    return runs


def _source_digest(path: Path, cached: dict | None) -> dict:
    """sha256 of ``path``, reused from ``cached`` while its size and mtime hold.

    The downloader rewrites the current slot on every run, so a digest keyed by
    frame id alone would go stale.
    """
    stat = path.stat()
    signature = [stat.st_size, int(stat.st_mtime)]
    if cached and cached.get("signature") == signature:
        return cached
    digest = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            digest.update(chunk)
    return {"signature": signature, "sha256": digest.hexdigest()}


def _refresh_cloud_credits(meta_path: Path, download_meta: dict) -> None:
    """Patch download-sourced credit fields (license, attribution) onto an
    existing cloud metadata.json on skip — so credit edits ship without
    re-encoding every frame. Clouds don't flow through the shared
    ``refresh_metadata_from_yaml`` (their metadata shape differs)."""
    try:
        current = json.loads(meta_path.read_text())
    except OSError, json.JSONDecodeError:
        return
    desired = {
        "license": download_meta.get("license"),
        "attribution": download_meta.get("attribution"),
    }
    if all(current.get(k) == v for k, v in desired.items()):
        return
    current.update(desired)
    meta_path.write_text(json.dumps(current, indent=2))
    log.info(
        "refreshed cloud credits from download metadata: %s", meta_path.parent.name
    )


class TextureProcessor:
    def __init__(self) -> None:
        self._raw_meta: list[dict] = load_entries(SOURCES_TEXTURES_DIR)

    @cached_property
    def _bundles(self) -> dict[str, str]:
        """Where each surface map exports to, once the candidates for a body
        have been ranked against each other. Derived from the entries rather
        than set up front, so it holds however the processor was built."""
        return rank_by_body(self._raw_meta)

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
        except OSError, json.JSONDecodeError:
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

    def _prune_stale_tiers(self, out_dir: Path, exports: dict, object_id: str) -> None:
        """Drop tier files a reprocess no longer produces (e.g. after a tier-size
        or source change) — leftovers would ship alongside fresh exports."""
        for tier in ("low", "medium", "high"):
            if tier in exports:
                continue
            stale = out_dir / f"{tier}.webp"
            if stale.exists():
                stale.unlink()
                log.info("removed stale export %s/%s.webp", object_id, tier)

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
            # The bundle, not the body: a sibling layer and a body's
            # second-best map both live beside it under their own name, and
            # this is what the renderer builds their URLs from.
            "id": out_dir.name,
            "source": entry["source"],
            "organisation": entry["organisation"],
            "license": entry.get("license"),
            "distribution": entry.get("distribution"),
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
        """Process all textures listed in the manifests.

        Warns about any image files in RAW_DIR not referenced by the metadata.
        """
        self._reset_texture_available()
        # `known_files` only gates the RAW_DIR untracked-files check below, so
        # we restrict it to entries actually sourced from raw/. misc/ entries
        # have their own per-subdir manifests and aren't expected in raw/.
        known_files: set[str] = set()
        for entry in self._raw_meta:
            if entry["_source_dir"] == config.RAW_DIR:
                known_files.update(expand_entry_files(entry))

        for entry in self._raw_meta:
            if not builds_tiers(entry):
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
            src = entry["_source_dir"] / entry["file"]
            if not src.exists():
                log.warning("listed in metadata but not found: %s", entry["file"])
                continue
            self.process(src, force=force)

        self._process_clouds(force=force)

        for f in sorted(config.RAW_DIR.iterdir()):
            if f.suffix.lower() in config.IMAGE_EXTS and f.name not in known_files:
                log.warning("untracked file not in the texture manifests: %s", f.name)

    def process(self, src: Path | str, force: bool = False) -> Path:
        """Process a raw texture into WebP exports.

        Reads body info from the root texture manifest.
        Exports are written to PROCESSED_DIR/<object_id>/ alongside a metadata.json.
        Returns the output directory.
        """
        src = Path(src)
        entries = [b for b in self._raw_meta if b.get("file") == src.name]
        if not entries:
            log.warning("%s not found in the texture manifests", src.name)
            return config.PROCESSED_DIR
        # A file may also be listed as the source of a pyramid alone.
        entry = next((b for b in entries if builds_tiers(b)), None)
        if entry is None:
            log.debug("skipping %s (no tiers asked for in the manifest)", src.name)
            return config.PROCESSED_DIR

        object_id = self._bundles.get(src.name)
        if object_id is None:
            log.debug("skipping %s (not a ranked map)", src.name)
            return config.PROCESSED_DIR
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
        self._prune_stale_tiers(out_dir, exports, object_id)

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

    def process_tiles(self, force: bool = False) -> None:
        """Build a tile pyramid for every map, and drop the pyramids of maps
        that are gone."""
        sources: dict[str, dict] = {}
        for entry in self._raw_meta:
            if entry.get("skip"):
                continue
            pyramid_id = self._pyramid_id(entry)
            if pyramid_id is None:
                continue
            current = sources.get(pyramid_id)
            dedicated = entry.get("tiles") == TILES_ONLY
            if current is None or (dedicated and current.get("tiles") != TILES_ONLY):
                sources[pyramid_id] = entry
            elif dedicated:
                log.warning(
                    "%s: %s already has a tile source, ignoring",
                    entry.get("file", entry["body"]),
                    pyramid_id,
                )
        for pyramid_id, entry in sources.items():
            self._process_tiles(entry, pyramid_id, force=force)
            self._process_patches(entry, pyramid_id)

        for root in (
            config.TILES_PROCESSED_DIR,
            mirror_path(config.TILES_METADATA_DIR),
        ):
            if not root.exists():
                continue
            for child in root.iterdir():
                # A stopped build of a map that is still there waits for its
                # next run, which may be days of work in.
                name = child.name.removesuffix(".building")
                if child.is_dir() and name not in sources:
                    shutil.rmtree(child)
                    log.info("removed stale tile pyramid %s", child)

    def _pyramid_id(self, entry: dict) -> str | None:
        """The bundle a pyramid refines: it shares the id of that bundle's
        tiers, whichever entry those come from. None for what is not tiled."""
        type_ = entry.get("type", "")
        if type_ in ("cylindrical", "cylindrical_monthly"):
            # An entry written for a pyramid refines the bundle whose tiers
            # come from its file: a body with a second map can sharpen both.
            # With a file of its own it refines the body's best map.
            bundle = self._bundles.get(entry.get("file", ""))
            if bundle is None and entry.get("tiles") == TILES_ONLY:
                return entry["body"]
            return bundle
        suffix = _TILED_SIBLINGS.get(type_)
        return None if suffix is None else f"{entry['body']}{suffix}"

    def _process_tiles(self, entry: dict, pyramid_id: str, force: bool) -> None:
        source_dir = entry["_source_dir"]
        is_height = entry["type"] == "cylindrical_displacement"
        # One pyramid per frame; a single-frame map has one, unnamed.
        frames: dict[str, list[dict]]
        if entry["type"] == "cylindrical_monthly":
            frames = {
                f"{month:02d}": [layer]
                for month, layer in enumerate(month_layers(entry), 1)
            }
        else:
            frames = {"": [entry, *(entry.get("insets") or [])]}
        base_specs = [spec for specs in frames.values() for spec in specs]
        brightness_specs = entry.get("brightness") or []

        missing = [
            name
            for spec in (*base_specs, *brightness_specs)
            for name, _ in layer_files(spec)
            if not (source_dir / name).exists()
        ]
        if missing:
            log.warning(
                "tile source missing for %s: %d files, first %s",
                pyramid_id,
                len(missing),
                missing[0],
            )
            return

        alignment = entry_alignment(entry)
        height_fields = {
            key: entry.get(key)
            for key in ("height_unit", "height_scale", "height_offset", "height_nodata")
        }

        def signed_files(spec: dict) -> dict:
            if "grid" not in spec:
                path = source_dir / spec["file"]
                return {"file": spec["file"], "size": path.stat().st_size}
            return {
                "files": [
                    [name, (source_dir / name).stat().st_size]
                    for name, _ in layer_files(spec)
                ]
            }

        signature: dict = {
            "recipe": tiles.RECIPE,
            "tile_size": config.TILE_SIZE,
            "max_level": entry.get("tiles_max_level"),
            "alignment": alignment,
            "nodata_fill_km": entry.get("nodata_fill_km"),
            "layers": [
                {
                    **signed_files(spec),
                    "lat_range": spec.get("lat_range"),
                    **{k: spec.get(k, v) for k, v in height_fields.items()},
                }
                for spec in base_specs
            ],
        }
        sharpen_sigma = entry.get("sharpen_sigma", config.TILE_SHARPEN_SIGMA)
        if brightness_specs:
            signature["brightness"] = {
                "recipe": tiles.SHARPEN_RECIPE,
                "sigma": sharpen_sigma,
                "range": config.TILE_SHARPEN_RANGE,
                "layers": [
                    {
                        "files": [
                            [name, (source_dir / name).stat().st_size]
                            for name, _ in layer_files(spec)
                        ],
                        "lat_range": spec.get("lat_range"),
                        "projection": spec.get("projection"),
                        "alignment": entry_alignment(spec),
                        **({"gamma": spec["gamma"]} if spec.get("gamma") else {}),
                    }
                    for spec in brightness_specs
                ],
            }
            if entry.get("soften_colour"):
                signature["brightness"]["soften_colour"] = True
        version = tiles.signature_version(signature)
        credit = {
            "id": pyramid_id,
            "source": entry["source"],
            "organisation": entry["organisation"],
            "license": entry.get("license"),
            "distribution": entry.get("distribution"),
            "attribution": entry.get("attribution")
            or scraped_attribution(layer_files(base_specs[0])[0][0]),
            "description": entry.get("description"),
            "type": entry["type"],
        }

        out_dir = config.TILES_PROCESSED_DIR / pyramid_id
        meta_path = mirror_path(
            config.TILES_METADATA_DIR / pyramid_id / "metadata.json"
        )
        # Built aside, so a failed run never leaves half a pyramid in place.
        # The first part to build tells whether what is there can be kept.
        building = out_dir.with_name(f"{out_dir.name}.building")
        first = next(iter(frames))
        # A run that stopped before the descriptor named its build left the
        # saves in the pyramid it had just put in place.
        if not building.exists() and tiles.resumable(out_dir / first, version):
            out_dir.rename(building)
        pending = building.exists() and tiles.resumable(building / first, version)
        existing = (
            json.loads(meta_path.read_text())
            if meta_path.exists() and out_dir.exists()
            else None
        )
        current = existing and existing.get("version") == version
        if existing and current and not (force or pending):
            if any(existing.get(k) != v for k, v in credit.items()):
                meta_path.write_text(json.dumps({**existing, **credit}, indent=2))
                log.info("refreshed tile credits from yaml: %s", pyramid_id)
            log.debug("skipping tiles for %s (already built)", pyramid_id)
            return

        brightness = [
            self._open_brightness_layer(source_dir, spec) for spec in brightness_specs
        ]
        described = [
            {
                **_described_files([name for name, _ in layer_files(spec)]),
                "source": spec["source"],
                "dimensions": layer.dimensions,
                "full_width": layer.width,
                "lat_range": spec.get("lat_range"),
                "role": "brightness",
            }
            for spec, layer in zip(brightness_specs, brightness)
        ]

        if building.exists() and not pending:
            shutil.rmtree(building)
        max_level = entry.get("tiles_max_level")
        stats: tiles.PyramidStats | None = None
        cap_stats: tiles.PyramidStats | None = None
        parts: list[Path] = []
        coding = None
        for frame, specs in frames.items():
            layers = []
            quanta = []
            for spec in specs:
                grid = [[source_dir / name for name in row] for row in layer_grid(spec)]
                path = grid[0][0]
                lat_bottom, lat_top = spec.get("lat_range") or (-90.0, 90.0)
                placement = tiles.Placement(
                    lat_top=lat_top, lat_bottom=lat_bottom, **alignment
                )
                if is_height:
                    raster = open_height_raster(
                        path,
                        unit=spec.get("height_unit")
                        or height_fields["height_unit"]
                        or "m",
                        scale=spec.get("height_scale", height_fields["height_scale"]),
                        offset=spec.get(
                            "height_offset", height_fields["height_offset"]
                        ),
                        nodata=spec.get(
                            "height_nodata", height_fields["height_nodata"]
                        ),
                    )
                    quanta.append(tiles.height_quantum_km(raster))
                    layers.append(tiles.height_layer(raster, placement))
                elif entry["type"] == "cylindrical_specular":
                    mask = np.asarray(open_specular_source(path))
                    layers.append(tiles.Layer(mask, placement))
                else:
                    layer = tiles.open_colour_grid(grid, placement)
                    if brightness_specs and entry.get("soften_colour"):
                        layer = tiles.softened(layer, sharpen_sigma)
                    layers.append(layer)
            if max_level is None:
                max_level = tiles.finest_level(
                    max(layer.width for layer in (*layers, *brightness))
                )
            if stats is None or cap_stats is None:
                stats = tiles.PyramidStats.empty(max_level)
                cap_stats = tiles.PyramidStats.empty(max_level)
                described[:0] = [
                    {
                        **(
                            {"file": spec["file"]}
                            if "file" in spec
                            else _described_files(
                                [name for name, _ in layer_files(spec)]
                            )
                        ),
                        "source": spec["source"],
                        "dimensions": layer.dimensions,
                        "full_width": layer.width,
                        "lat_range": spec.get("lat_range"),
                    }
                    for spec, layer in zip(specs, layers)
                ]
            if is_height:
                lo, hi, gaps = tiles.height_range_km(layers)
                coding = tiles.HeightCoding.for_range(
                    lo, hi, min(quanta), entry.get("nodata_fill_km")
                )
                log.info(
                    "%s: %.3f..%.3f km in %.2f m steps, %d source px unmapped",
                    pyramid_id,
                    lo,
                    hi,
                    coding.step_km * 1000,
                    gaps,
                )
            name = f"{pyramid_id} {frame}".strip()
            shared = (layers, max_level, coding, brightness, sharpen_sigma, version)
            builder = tiles.PyramidBuilder(name, layers, building / frame, *shared[1:])
            stats.add(builder.build())
            parts.append(Path(frame))
            if max_level >= tiles.CapBuilder.min_level:
                for folder, north in tiles.CAP_FOLDERS.items():
                    cap = tiles.CapBuilder(
                        f"{name} {folder} cap",
                        north,
                        layers,
                        building / frame / folder,
                        *shared[1:],
                    )
                    cap_stats.add(cap.build())
                    parts.append(Path(frame, folder))
            # The builders keep the frame's layers until the next frame's
            # replace them: what they read goes now, or two months stay held.
            for layer in layers:
                layer.release()
        assert stats is not None and cap_stats is not None and max_level is not None
        if out_dir.exists():
            shutil.rmtree(out_dir)
        building.rename(out_dir)

        metadata: dict = {
            **credit,
            "version": version,
            "tile_size": config.TILE_SIZE,
            "max_level": max_level,
            "layers": described,
            "levels": stats.levels(),
            "cap_levels": cap_stats.levels(tiles.CapBuilder.min_level),
            "processed_at": datetime.now(UTC).isoformat(),
        }
        if entry["type"] == "cylindrical_monthly":
            metadata["frames"] = len(frames)
        if coding is not None:
            metadata["displacement_bias_km"] = coding.bias_km
            metadata["displacement_scale_km"] = coding.step_km * tiles.HEIGHT_LEVELS
            metadata["absolute_radius"] = bool(entry.get("absolute_radius", False))
        meta_path.parent.mkdir(parents=True, exist_ok=True)
        meta_path.write_text(json.dumps(metadata, indent=2))
        # Last: until the descriptor names this build, the saves are all that
        # keeps the next run from starting it over.
        for part in parts:
            tiles.clear_state(out_dir / part)
        log.info(
            "tiled %s: levels 0-%d, %d tiles, %.2f GiB",
            pyramid_id,
            max_level,
            sum(stats.tiles) + sum(cap_stats.tiles),
            (sum(stats.size_bytes) + sum(cap_stats.size_bytes)) / 2**30,
        )

    def _process_patches(self, entry: dict, pyramid_id: str) -> None:
        """Build the patches of a pyramid that are not there, and take out the
        ones its entry no longer names."""
        out_dir = config.TILES_PROCESSED_DIR / pyramid_id
        meta_path = mirror_path(
            config.TILES_METADATA_DIR / pyramid_id / "metadata.json"
        )
        if not (out_dir.exists() and meta_path.exists()):
            return
        metadata = json.loads(meta_path.read_text())
        built = {patch["id"]: patch for patch in metadata.get("patches") or []}
        wanted = {spec["id"]: spec for spec in entry.get("patches") or []}
        if not (built or wanted):
            self._drop_copies(pyramid_id, set())
            return
        source_dir = entry["_source_dir"]
        base_level = metadata["max_level"]
        # A height pyramid: its patches are heights in its own coding.
        coding = None
        if "displacement_scale_km" in metadata:
            coding = tiles.HeightCoding(
                metadata["displacement_bias_km"],
                metadata["displacement_scale_km"] / tiles.HEIGHT_LEVELS,
                metadata["displacement_bias_km"],
            )

        def save() -> None:
            metadata["patches"] = list(built.values())
            if not built:
                del metadata["patches"]
            meta_path.write_text(json.dumps(metadata, indent=2))

        for patch_id in built.keys() - wanted.keys():
            patches.remove(out_dir, base_level, built.pop(patch_id))
            save()
            log.info("removed patch %s of %s", patch_id, pyramid_id)

        # Mosaics with their Sun's shading taken out, kept for the next build.
        # A source out of reach for a run keeps its copies.
        copies_dir = config.DESHADED_DIR / pyramid_id
        kept_copies: set[str] = set()
        kept_mosaics: list[str] = []

        for patch_id, spec in wanted.items():
            files = [name for layer in spec["files"] for name, _ in layer_files(layer)]
            terrain = None
            if spec.get("deshade"):
                terrain = self._site_terrain(entry["body"], patch_id)
                if terrain is None:
                    log.error(
                        "patch %s %s: no terrain model to deshade it by",
                        pyramid_id,
                        patch_id,
                    )
                    continue
            missing = [
                path
                for path in [source_dir / name for name in files]
                + [path for path, _ in terrain or []]
                if not path.exists()
            ]
            if missing:
                log.warning(
                    "patch source missing for %s %s: %s",
                    pyramid_id,
                    patch_id,
                    missing[0].name,
                )
                if terrain is not None:
                    kept_mosaics.extend(files)
                continue
            sigma = spec.get("sharpen_sigma", config.PATCH_SIGMA)
            signature: dict = {
                "recipe": patches.RECIPE,
                "pyramid": metadata["version"],
                "sigma": sigma,
                "max_level": spec.get("tiles_max_level"),
                "files": [
                    [name, (source_dir / name).stat().st_size, layer.get("gamma")]
                    for layer in spec["files"]
                    for name, _ in layer_files(layer)
                ],
            }
            if coding is not None:
                signature["recipe"] = patches.HEIGHT_RECIPE
                signature["heights"] = [
                    _height_signature(_height_fields(entry, layer))
                    for layer in spec["files"]
                ]
            copy_keys: dict[str, str] = {}
            if terrain is not None:
                signature["deshade"] = [
                    deshade.RECIPE,
                    [
                        [path.name, path.stat().st_size, _height_signature(how)]
                        for path, how in terrain
                    ],
                ]
                for name in files:
                    copy_keys[name] = tiles.signature_version(
                        {
                            "mosaic": [name, (source_dir / name).stat().st_size],
                            "deshade": signature["deshade"],
                        }
                    )
                    kept_copies.add(deshade.copy_name(name, copy_keys[name]))
            version = tiles.signature_version(signature)
            credit = {
                key: spec.get(key)
                for key in (
                    "id",
                    "name",
                    "source",
                    "organisation",
                    "license",
                    "attribution",
                )
            }
            current = built.get(patch_id)
            if current and current["version"] == version:
                if any(current.get(key) != value for key, value in credit.items()):
                    built[patch_id] = {**current, **credit}
                    save()
                continue

            # Built aside, and the tiles it replaces stay until it is whole: a
            # stopped build leaves the pyramid as it was.
            building = out_dir / f".patch-{patch_id}"
            if building.exists():
                shutil.rmtree(building)
            try:
                models = [
                    tiles.open_height_region_layer(path, **how)
                    for path, how in terrain or []
                ]
                rasters = []
                for layer in spec["files"]:
                    for name, _ in layer_files(layer):
                        path = source_dir / name
                        if coding is not None:
                            rasters.append(
                                tiles.open_height_region_layer(
                                    path, **_height_fields(entry, layer)
                                )
                            )
                            continue
                        if models:
                            path = deshade.deshaded(
                                path, models, copy_keys[name], copies_dir
                            )
                        rasters.append(
                            tiles.open_region_layer(path, layer.get("gamma"))
                        )
                builder = patches.PatchBuilder(
                    f"{pyramid_id} {patch_id}",
                    out_dir,
                    base_level,
                    rasters,
                    building,
                    sigma,
                    spec.get("tiles_max_level"),
                    coding,
                )
            except ValueError as error:
                # A file this build cannot place: the other patches still can.
                log.error("patch %s %s: %s", pyramid_id, patch_id, error)
                continue
            # The tiles of the first level are the widest. One that two
            # patches share would be written by each without the other's
            # detail, and deleted with either.
            reach = builder.tile_range(base_level + 1)
            shared = [
                other["id"]
                for other in built.values()
                if other["id"] != patch_id
                and patches.share_tiles(
                    reach,
                    patches.first_range(
                        base_level, other["max_level"], other["x"], other["y"]
                    ),
                )
            ]
            if shared:
                log.error(
                    "patch %s %s shares tiles with %s: they belong in one patch",
                    pyramid_id,
                    patch_id,
                    shared[0],
                )
                continue
            stats = builder.build()
            if current:
                del built[patch_id]
                save()
                patches.remove(out_dir, base_level, current)
            patches.put_in_place(building, out_dir, patch_id)
            x0, x1, y0, y1 = builder.tile_range(builder.level)
            built[patch_id] = {
                **credit,
                "version": version,
                "max_level": builder.level,
                "map_levels": builder.map_levels,
                "x": [x0, x1],
                "y": [y0, y1],
                "files": files,
                "full_width": builder.full_width,
                "bounds": {
                    edge: round(getattr(builder, edge), 6)
                    for edge in ("west", "east", "south", "north")
                },
                "levels": stats.levels(base_level + 1),
                "processed_at": datetime.now(UTC).isoformat(),
            }
            save()
            log.info(
                "patched %s %s: levels %d-%d, %d tiles, %.2f GiB",
                pyramid_id,
                patch_id,
                base_level + 1,
                builder.level,
                sum(stats.tiles),
                sum(stats.size_bytes) / 2**30,
            )

        self._drop_copies(pyramid_id, kept_copies, kept_mosaics)

    @staticmethod
    def _drop_copies(
        pyramid_id: str, keep: set[str], mosaics: Sequence[str] = ()
    ) -> None:
        """Delete the deshaded copies of a pyramid that are not in ``keep``
        and not of one of ``mosaics``."""
        folder = config.DESHADED_DIR / pyramid_id
        if not folder.exists():
            return
        for copy in folder.iterdir():
            if copy.name in keep or any(deshade.copy_of(copy.name, m) for m in mosaics):
                continue
            copy.unlink()
            log.info("removed deshaded copy %s", copy.name)

    def _site_terrain(self, body: str, patch_id: str) -> list[tuple[Path, dict]] | None:
        """The terrain models of a site: the files of the patch of the same id
        in the body's height pyramid, and how each is read."""
        for entry in self._raw_meta:
            if (
                entry.get("skip")
                or entry.get("type") != "cylindrical_displacement"
                or entry["body"] != body
            ):
                continue
            for spec in entry.get("patches") or []:
                if spec["id"] == patch_id:
                    found = [
                        (entry["_source_dir"] / name, _height_fields(entry, layer))
                        for layer in spec["files"]
                        for name, _ in layer_files(layer)
                    ]
                    return found or None
        return None

    def _open_brightness_layer(self, source_dir: Path, spec: dict) -> tiles.Source:
        lat_bottom, lat_top = spec.get("lat_range") or (-90.0, 90.0)
        placement = tiles.Placement(
            lat_top=lat_top, lat_bottom=lat_bottom, **entry_alignment(spec)
        )
        grid = [[source_dir / name for name in row] for row in layer_grid(spec)]
        if spec.get("projection") == "polar_stereographic":
            return tiles.open_polar_brightness_layer(
                grid[0][0], placement, spec.get("gamma")
            )
        return tiles.open_brightness_layer(grid, placement, spec.get("gamma"))

    def _process_specular(self, entry: dict, force: bool = False) -> Path:
        """Process a `cylindrical_specular` entry.

        Output goes to ``{body}_specular/`` — a sibling of the surface texture
        and ``_clouds`` bundle; the renderer routes it into whichever material
        slot (roughness, specular intensity) it sees fit. The source is a
        ready-made grayscale mask, used as-is.
        """
        src = entry["_source_dir"] / entry["file"]
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
        self._prune_stale_tiers(out_dir, exports, object_id)

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
        src = entry["_source_dir"] / entry["file"]
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
        self._prune_stale_tiers(out_dir, exports, object_id)

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
        src = entry["_source_dir"] / entry["file"]
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
            nodata_fill_km=entry.get("nodata_fill_km"),
        )
        source_dims = [img.width, img.height]
        img = align_cylindrical(img, **entry_alignment(entry))
        exports = self._export(img, object_id, out_dir)
        self._prune_stale_tiers(out_dir, exports, object_id)

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
        src = entry["_source_dir"] / entry["file"]
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
        # 2 GiB available is comfortable headroom.
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
        source_dir: Path = entry["_source_dir"]

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
        self._prune_stale_clouds()

    def _prune_stale_clouds(self) -> None:
        """Delete cloud bundles for bodies no longer in ``CLOUD_SOURCES``.

        The export reads the bundles off disk, so dropping a source leaves the
        overlay shipping until its directory goes.
        """
        wanted = {
            config.clouds_object_id(body_id)
            for body_id in config.CLOUD_SOURCES.values()
        }
        for root in (config.PROCESSED_DIR, mirror_path(config.PROCESSED_DIR)):
            if not root.exists():
                continue
            for bundle in root.iterdir():
                if not bundle.is_dir() or not bundle.name.endswith(
                    config.CLOUDS_SUFFIX
                ):
                    continue
                if bundle.name in wanted:
                    continue
                log.info("pruning stale cloud bundle: %s", bundle)
                shutil.rmtree(bundle)

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
        slots = [fid for fid, _ in inputs]
        coverage = _coverage_runs(slots)
        existing: dict = {}

        object_id = config.clouds_object_id(body_id)
        out_dir = config.PROCESSED_DIR / object_id
        meta_path = mirror_path(out_dir / "metadata.json")

        download_meta_path = src_dir / "metadata.json"
        download_meta: dict = {}
        if download_meta_path.exists():
            try:
                download_meta = json.loads(download_meta_path.read_text())
            except OSError, json.JSONDecodeError:
                log.warning(
                    "failed to read clouds download metadata at %s", download_meta_path
                )

        if not force and meta_path.exists():
            try:
                existing = json.loads(meta_path.read_text())
            except OSError, json.JSONDecodeError:
                existing = {}
            if existing.get("slots") == slots:
                log.debug(
                    "skipping clouds (already processed %d slots, use force=True to reprocess)",
                    len(slots),
                )
                _refresh_cloud_credits(meta_path, download_meta)
                self._mark_texture_available(object_id)
                return out_dir

        out_dir.mkdir(parents=True, exist_ok=True)

        # Keep only the snapshots that differ from the frame before them:
        # upstream freezes for days at a time, and a held picture needs one
        # file, not one per slot. Cached digests keep a rerun off a full rehash.
        cached_digests: dict = {} if force else dict(existing.get("digests") or {})
        digests: dict = {}
        kept: list[tuple[str, Path]] = []
        previous_sha: str | None = None
        for fid, src in inputs:
            entry = _source_digest(src, cached_digests.get(fid))
            digests[fid] = entry
            if entry["sha256"] == previous_sha:
                continue
            previous_sha = entry["sha256"]
            kept.append((fid, src))
        target_frames = [fid for fid, _ in kept]
        if len(kept) < len(inputs):
            log.info(
                "clouds %s: %d of %d slots repeat the frame before them",
                object_id,
                len(inputs) - len(kept),
                len(inputs),
            )

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
        for fid, src in kept:
            suffix = f"_{fid}"
            if not force and (out_dir / f"low{suffix}.webp").exists():
                # Existing output covers this frame; tier discovery falls to
                # any frame we actually encode (they share dims, so tiers
                # match), or the post-loop fallback below.
                continue
            img = open_image(src, keep_alpha=True)
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
            "license": download_meta.get("license"),
            "attribution": download_meta.get("attribution"),
            "description": "Near-real-time cloud-cover overlay (3-hour cadence).",
            "type": "clouds_overlay",
            "tiers": tiers,
            "frames": target_frames,
            "coverage": coverage,
            # Build-only, dropped by clouds_block: the slot inventory drives the
            # cheap skip check, the digests spare a rerun the full rehash.
            "slots": slots,
            "digests": digests,
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
            except OSError, json.JSONDecodeError:
                log.warning(
                    "failed to read clouds download metadata at %s", download_meta_path
                )

        if not force and meta_path.exists() and (out_dir / "low_static.webp").exists():
            log.debug(
                "skipping static clouds %s (already processed, use force=True to reprocess)",
                object_id,
            )
            _refresh_cloud_credits(meta_path, download_meta)
            self._mark_texture_available(object_id)
            return out_dir

        out_dir.mkdir(parents=True, exist_ok=True)
        img = open_image(src, keep_alpha=True)
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
            "license": download_meta.get("license"),
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
