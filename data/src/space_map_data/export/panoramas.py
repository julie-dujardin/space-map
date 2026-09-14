"""Surface panoramas: the entries a body's global bundle lists under
`panoramas`, and the sphere textures they point at under `v1/panoramas/`.

A product is exported once it can be placed and dated — a position, a capture
time and a sphere texture. How well it is known travels with it rather than
keeping it out: `geometry` says whether the sphere's angular bounds are
archival or fitted by eye, and `orientation` says how north was established.
A panorama whose north is unknown is still worth showing where it was taken,
so it exports with no offset and the viewer declines to draw a heading for it.
`altitude_m` marks the views taken above the surface rather than standing on
it, which `lat`/`lon` alone would not distinguish.

Entries sort by mission then time, so neighbours in the list are neighbours on
the traverse.
"""

import gzip
import logging
from collections import Counter
import re
import shutil
from functools import cache
from pathlib import Path
from typing import NamedTuple

import orjson
from tqdm import tqdm
from PIL import Image

from space_map_data.export.sidecar_io import write_atomic
from space_map_data.panoramas.missions import probe_id
from space_map_data.utils.paths import EXPORT_DIR, PANORAMA_DERIVED_DIR

logger = logging.getLogger(__name__)

ASSET_DIR = "panoramas"
# What `/view` reads to know which traverses exist before any body bundle is
# fetched.
INDEX_FILE = "panoramas.json"
# Timeline cards show the observed strip at thumbnail size.
PREVIEW_WIDTH = 512


class Product(NamedTuple):
    entry: dict
    image: Path
    preview: Path | None


def _sphere_geometry_is_archival(meta: dict) -> bool:
    return (
        meta.get("grid_geometry_status") != "estimated"
        and meta.get("geometry_status") != "estimated"
    )


def _orientation(meta: dict) -> str | None:
    """How north was established, or None where the archive itself states it."""
    if meta.get("north_azimuth_offset_deg") is None:
        return "unknown"
    status = meta.get("orientation_status")
    return status if status and status != "archival" else None


# A source whose reuse terms are unsettled is processed and kept locally, but
# never published. Withholding is explicit: a product that states nothing about
# reuse is treated as it always was.
REUSE_WITHHELD = "permission-pending"

# Reuse is a property of the release, not of each file, so the missions whose
# terms are unsettled are named here too. A product written before the terms
# were recorded carries no reuse field, and must not publish on that silence.
WITHHELD_MISSIONS = frozenset({"zhurong", "yutu-2"})


def _skip_reason(meta: dict) -> str | None:
    if (meta.get("reuse") or {}).get("status") == REUSE_WITHHELD:
        return "reuse permission pending"
    if meta.get("mission") in WITHHELD_MISSIONS:
        return "reuse permission pending for the release"
    if not meta.get("body_id"):
        return "no body id"
    if not meta.get("position"):
        return "no position"
    if not meta.get("image"):
        return "no sphere texture"
    if not (meta.get("start_time") or meta.get("capture_time")):
        return "undated"
    return None


def _seconds(iso: str | None) -> str | None:
    """Drop fractional seconds: a mosaic spans minutes, and the viewer keys
    its URL on this string."""
    return re.sub(r"\.\d+(?=Z$)", "", iso) if iso else None


def _entry(meta: dict) -> dict:
    """The exported shape of one product the caller has found exportable."""
    position = meta["position"]
    coverage = meta.get("coverage") or {}
    source_coverage = meta.get("source_coverage") or {}
    sources = meta.get("sources") or {}
    reuse = meta.get("reuse") or {}
    entry = {
        "id": meta["id"],
        "mission": meta.get("mission"),
        "instrument": meta.get("instrument"),
        "sol": meta.get("sol"),
        "time": _seconds(meta.get("start_time") or meta.get("capture_time")),
        "time_end": _seconds(meta.get("stop_time")),
        "lat": position["latitude"],
        "lon": position["longitude"],
        "elevation_m": position.get("elevation_m"),
        # Set only where the camera was not on the ground, so the viewer can
        # say so rather than let a descent view pass for a surface one.
        "altitude_m": meta.get("observer_altitude_m"),
        "title": meta.get("title"),
        # An unknown north leaves the sphere as rendered; the viewer reads
        # `orientation` and draws no heading rather than a wrong one.
        "north_offset_deg": meta.get("north_azimuth_offset_deg") or 0,
        "orientation": _orientation(meta),
        "geometry": None if _sphere_geometry_is_archival(meta) else "estimated",
        # The archive's own coordinate overlay is still drawn on this texture.
        # Recorded so the imagery can be told apart and replaced, not shown.
        "source_grid": coverage.get("includes_source_grid") or None,
        "azimuth_start_deg": source_coverage.get("azimuth_start_deg"),
        "hfov_deg": coverage.get("horizontal_degrees"),
        "sphere_percent": coverage.get("sphere_percent"),
        "color": meta.get("color"),
        "credit": meta.get("credit"),
        "credit_url": meta.get("reuse_policy_url") or reuse.get("policy_url"),
        "source_url": sources.get("label_url") or meta.get("selected_url"),
    }
    return {k: v for k, v in entry.items() if v is not None}


def load_panoramas(
    derived_dir: Path = PANORAMA_DERIVED_DIR,
) -> dict[str, list[Product]]:
    """Exportable products by body id, each with its texture path, in
    mission-then-time order."""
    by_body: dict[str, list[Product]] = {}
    if not derived_dir.is_dir():
        # An absent cache is indistinguishable from one holding nothing, and the
        # export treats nothing as "delete what was published". The cache lives
        # on a mount, so absence usually means unmounted, not emptied on purpose.
        raise FileNotFoundError(
            f"Panorama cache {derived_dir} is missing. Exporting now would delete"
            " every published panorama. Mount the share, or pass an empty"
            " directory to publish none on purpose."
        )
    catalogs = [
        (path, orjson.loads(path.read_bytes()).get("panoramas", []))
        for path in sorted(derived_dir.glob("*/catalog.json"))
    ]
    skipped: Counter[str] = Counter()
    total = sum(len(items) for _, items in catalogs)
    with tqdm(total=total, desc="Panoramas", unit="pano") as progress:
        for _, items in catalogs:
            for item in items:
                progress.update(1)
                meta_path = derived_dir / item["metadata"]
                meta = orjson.loads(meta_path.read_bytes())
                reason = _skip_reason(meta)
                if reason:
                    skipped[reason] += 1
                    logger.debug("Panorama %s not exported: %s", meta.get("id"), reason)
                    continue
                folder = meta_path.parent
                preview = folder / meta["preview"] if meta.get("preview") else None
                by_body.setdefault(meta["body_id"], []).append(
                    Product(_entry(meta), folder / meta["image"], preview)
                )
    for body_id, entries in by_body.items():
        entries.sort(key=lambda p: (p.entry.get("mission", ""), p.entry["time"]))
        by_body[body_id], repeats = _dedupe(entries)
        if repeats:
            skipped["repeats an earlier time and place"] += repeats
    exported = sum(len(v) for v in by_body.values())
    logger.info(
        "Panoramas: %d of %d exported across %d bodies", exported, total, len(by_body)
    )
    for reason, count in skipped.most_common():
        logger.info("  %6d skipped: %s", count, reason)
    return by_body


def _dedupe(entries: list[Product]) -> tuple[list[Product], int]:
    """One product per (time, lat, lon): the viewer addresses a panorama by
    that triple, so a second rendition of the same mosaic is unreachable."""
    seen: set[tuple] = set()
    kept = []
    for product in entries:
        entry = product.entry
        key = (entry["time"], entry["lat"], entry["lon"])
        if key in seen:
            logger.debug("Panorama %s repeats an earlier time and place", entry["id"])
            continue
        seen.add(key)
        kept.append(product)
    return kept, len(entries) - len(kept)


@cache
def _cached() -> dict[str, list[Product]]:
    return load_panoramas()


def panoramas_block(object_id: str) -> list[dict] | None:
    entries = _cached().get(object_id)
    return [p.entry for p in entries] if entries else None


def write_panorama_index(out_dir: Path) -> None:
    """Write `v1/panoramas.json`: every traverse that has coverage, as body
    plus mission with its span and the probe that drove it. The points
    themselves stay in the body bundle."""
    bodies = []
    for body_id, products in sorted(_cached().items()):
        missions: dict[str, list[dict]] = {}
        for product in products:
            missions.setdefault(product.entry.get("mission") or "", []).append(
                product.entry
            )
        summaries = []
        for mission, entries in sorted(missions.items()):
            summary = {
                "mission": mission,
                "probe": probe_id(mission),
                "count": len(entries),
                "first_time": entries[0]["time"],
                "last_time": entries[-1]["time"],
            }
            summaries.append({k: v for k, v in summary.items() if v is not None})
        bodies.append({"id": body_id, "missions": summaries})
    path = out_dir / INDEX_FILE
    write_atomic(path, orjson.dumps({"bodies": bodies}, option=orjson.OPT_INDENT_2))
    logger.info("Panorama index: %d bodies in %s", len(bodies), path)


def _write_preview(source: Path, target: Path) -> None:
    with Image.open(source) as im:
        im.thumbnail((PREVIEW_WIDTH, PREVIEW_WIDTH))
        im.save(target, "WEBP", quality=80)


def write_panorama_assets(out_dir: Path) -> None:
    """Copy every exportable sphere texture to `v1/panoramas/<id>.webp`, with
    a `<id>-preview.webp` thumbnail beside it."""
    asset_dir = out_dir / ASSET_DIR
    asset_dir.mkdir(parents=True, exist_ok=True)
    copied = 0
    wanted: set[Path] = set()
    for entries in _cached().values():
        for entry, image, preview in entries:
            target = asset_dir / f"{entry['id']}{image.suffix}"
            wanted.add(target)
            if not (target.exists() and target.stat().st_size == image.stat().st_size):
                shutil.copyfile(image, target)
                copied += 1
            if preview is None:
                continue
            thumb = asset_dir / f"{entry['id']}-preview.webp"
            wanted.add(thumb)
            if not thumb.exists() or thumb.stat().st_mtime < preview.stat().st_mtime:
                _write_preview(preview, thumb)
                copied += 1
    stale = [p for p in asset_dir.iterdir() if p not in wanted]
    for path in stale:
        path.unlink()
    logger.info(
        "Panorama assets: %d copied, %d stale removed in %s",
        copied,
        len(stale),
        asset_dir,
    )


def _patch_global_bundles(out_dir: Path) -> None:
    """Rewrite `panoramas` on every global bundle: set on the bodies that have
    some, cleared on the ones that no longer do."""
    by_body = _cached()
    seen: set[str] = set()
    for bucket_path in sorted((out_dir / "objects" / "__global__").glob("*.json.gz")):
        bundle = orjson.loads(gzip.decompress(bucket_path.read_bytes()))
        changed = False
        for body_id, data in bundle.items():
            if body_id in by_body:
                data["panoramas"] = [p.entry for p in by_body[body_id]]
                seen.add(body_id)
                changed = True
            elif data.pop("panoramas", None) is not None:
                logger.info("Panoramas: %s has none any more", body_id)
                changed = True
        if changed:
            write_atomic(bucket_path, gzip.compress(orjson.dumps(bundle), mtime=0))
    for body_id in sorted(set(by_body) - seen):
        logger.warning(
            "%s not in any global bundle; its panoramas are unreachable", body_id
        )


def export_panoramas_only() -> None:
    """`space-map-export --only panoramas` — assets plus in-place bundle
    patches, then fresh cache tokens for both classes."""
    from space_map_data.export.pipeline.orchestrator import _content_token

    out_dir = EXPORT_DIR / "v1"
    metadata_path = out_dir / "metadata.json"
    if not metadata_path.exists():
        raise SystemExit(f"Export dir {out_dir} missing — run a full export first.")
    write_panorama_assets(out_dir)
    write_panorama_index(out_dir)
    _patch_global_bundles(out_dir)
    metadata = orjson.loads(metadata_path.read_bytes())
    for cls in ("objects", ASSET_DIR):
        metadata["versions"][cls] = _content_token(out_dir / cls)
    metadata_path.write_bytes(orjson.dumps(metadata, option=orjson.OPT_INDENT_2))
