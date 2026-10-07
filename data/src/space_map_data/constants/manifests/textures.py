"""Texture download manifests, merged into one entry list.

Layout under ``textures/`` mirrors the download dir it describes: the root
manifest covers flat per-body surface textures in ``surfaces/``, and each
manually-staged asset (``star-map/``, ``night/earth/``, ``displacement/moon/``,
…) carries its own manifest at the directory holding its files — so a source
directory can be recovered from its manifest's own path, now that manifests no
longer sit next to their bytes.

``clouds/`` and ``rings/`` are excluded — they use their own downloader-written
metadata files, not hand-curated ones.
"""

import logging
from collections.abc import Iterator
from pathlib import Path

import yaml

logger = logging.getLogger(__name__)

MANIFESTS_DIR = Path(__file__).parent / "textures"
MANIFEST_NAME = "download-metadata.yaml"
# The root manifest's entries are the only ones whose files don't live in the
# directory the manifest mirrors.
SURFACES_SUBDIR = "surfaces"
# The map types where one body can have several candidates worth keeping.
_RANKED_TYPES = ("cylindrical", "cylindrical_monthly")
# `tiles:` value of an entry that feeds its bundle's tile pyramid and nothing
# else, in place of the entry the tiers come from.
TILES_ONLY = "only"


def builds_tiers(entry: dict) -> bool:
    """Whether the entry exports the whole-globe ``{tier}.webp`` files."""
    return not entry.get("skip") and entry.get("tiles") != TILES_ONLY


def source_layers(entry: dict) -> list[dict]:
    """Every raster an entry names: its own, then the layers that refine it in
    a pyramid. ``insets`` replace it over the band each one covers,
    ``brightness`` layers replace only its fine detail."""
    return [entry, *(entry.get("insets") or []), *(entry.get("brightness") or [])]


def _corner(degrees: int, width: int) -> str:
    """A quad corner as file names state it: zero-padded, minus for west and
    south, no sign otherwise."""
    return f"{'-' if degrees < 0 else ''}{abs(degrees):0{width}d}"


def _layer_cells(layer: dict) -> list[list[tuple[str, str | None]]]:
    """``(file, download link)`` for each file of a layer, as rows north to
    south and each row west to east. A link is the file itself, or a zip
    archive that holds it."""
    prefix = f"{layer['dir']}/" if layer.get("dir") else ""
    if "quads" in layer:
        # A regular grid of square quads, each named by its south-west corner.
        quads = layer["quads"]
        step = quads["step_deg"]
        south, north = layer["lat_range"]
        west = int(layer.get("lon_at_left_deg", -180))
        rows = []
        for lat in range(north - step, south - 1, -step):
            row = []
            for lon in range(west, west + 360, step):
                names = {"lon": _corner(lon, 3), "lat": _corner(lat, 2)}
                archive = quads.get("archive")
                row.append(
                    (
                        prefix + quads["file"].format(**names),
                        archive.format(**names) if archive else None,
                    )
                )
            rows.append(row)
        return rows
    if "grid" in layer:
        base = layer.get("download_dir")
        return [
            [(prefix + name, f"{base}/{name}" if base else None) for name in row]
            for row in layer["grid"]
        ]
    return [[(prefix + layer["file"], layer.get("download_url"))]]


def layer_grid(layer: dict) -> list[list[str]]:
    """The files of a layer, relative to the entry's source directory: rows
    north to south, each row west to east."""
    return [[name for name, _ in row] for row in _layer_cells(layer)]


def layer_files(layer: dict) -> list[tuple[str, str | None]]:
    """``(file, download link)`` for each file of a layer."""
    return [cell for row in _layer_cells(layer) for cell in row]


def load_entries(textures_dir: Path) -> list[dict]:
    """Every texture entry, stamped with ``_source_dir`` (its files' directory,
    resolved under ``textures_dir``)."""
    entries: list[dict] = []
    for manifest, source_dir in _manifests(textures_dir):
        bodies = (yaml.safe_load(manifest.read_text()) or {}).get("bodies") or []
        valid = [entry for entry in bodies if isinstance(entry, dict)]
        if len(valid) != len(bodies):
            logger.warning(
                "Dropping %d empty/invalid body entries from %s",
                len(bodies) - len(valid),
                manifest.relative_to(MANIFESTS_DIR.parent),
            )
        for entry in valid:
            entry["_source_dir"] = source_dir
        entries.extend(valid)
    return entries


def _manifests(textures_dir: Path) -> Iterator[tuple[Path, Path]]:
    """Each manifest with the directory its entries' files live in."""
    yield MANIFESTS_DIR / MANIFEST_NAME, textures_dir / SURFACES_SUBDIR
    # Depth 1 is a bodyless asset (star-map/), depth 2 a per-body one
    # (night/earth/).
    extra = sorted(
        list(MANIFESTS_DIR.glob(f"*/{MANIFEST_NAME}"))
        + list(MANIFESTS_DIR.glob(f"*/*/{MANIFEST_NAME}"))
    )
    for manifest in extra:
        yield manifest, textures_dir / manifest.parent.relative_to(MANIFESTS_DIR)


# Suffix marking a bundle that is not its body's best map: `naif-299_alt-usgs`.
# Parallel to the `_clouds` / `_night` sibling convention, so the loaders that
# already split siblings off a body's own directory keep working.
ALT_INFIX = "_alt-"


def bundle_id(entry: dict, is_best: bool) -> str | None:
    """Export directory name for one manifest entry.

    The best map of a body keeps the body's own id, so ranking a new map above
    an old one doesn't move the old bundle. Anything below it needs a
    ``variant`` slug to be told apart; without one there is nowhere to put it
    and the entry is dropped.
    """
    body = entry["body"]
    if is_best:
        return body
    variant = entry.get("variant")
    if not variant:
        logger.warning(
            "%s: ranked below the best map of %s but names no variant, dropping",
            entry.get("file"),
            body,
        )
        return None
    return f"{body}{ALT_INFIX}{variant}"


def rank_by_body(entries: list[dict]) -> dict[str, str]:
    """``{manifest file: bundle id}`` for every surface entry worth processing.

    Entries are ranked per body by ``preference`` (default 0), highest first;
    ties keep manifest order. Only plain and monthly cylindrical maps compete —
    the sibling layers (clouds, night, specular, displacement) are one per body
    by construction.
    """
    by_body: dict[str, list[dict]] = {}
    for entry in entries:
        if not builds_tiers(entry) or entry.get("type") not in _RANKED_TYPES:
            continue
        by_body.setdefault(entry["body"], []).append(entry)
    result: dict[str, str] = {}
    for ranked in by_body.values():
        ranked.sort(key=lambda e: -(e.get("preference") or 0))
        for position, entry in enumerate(ranked):
            name = bundle_id(entry, is_best=position == 0)
            if name is not None:
                result[entry["file"]] = name
    return result
