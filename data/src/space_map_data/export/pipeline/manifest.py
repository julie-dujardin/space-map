"""Build the unified ``position.zones`` manifest from per-zone snapshot streams."""

from collections.abc import Mapping
from dataclasses import dataclass, field

from space_map_data.export.pipeline.zone import SnapshotResult


@dataclass
class ZoomSnapshots:
    """All snapshots produced for one (zone, zoom). The discriminator on
    `build_position_metadata`'s output shape lives entirely in the snapshots — empty
    means a hole, one with ``time is None`` is the static case, otherwise the
    list is the chunk-indexed or date-segmented stream depending on
    `SnapshotResult.chunk_days`.
    """

    snapshots: list[SnapshotResult] = field(default_factory=list)
    parent_id_type: str | None = None  # ID_TYPES value of col-2 ids in this zoom


def _build_position_zoom(snaps: list[SnapshotResult], zone: str, zoom: int) -> dict:
    """Build one position/zones/{zone}/zooms/{zoom} entry from its snapshots.

    Three shapes, dispatched on the snapshot stream:

    * ``parted`` — single snapshot with ``time is None``. URL:
      ``position/{zone}/{zoom}/{part}.bin.gz``. Entry: ``{shape, parts}``.
    * ``chunked-parted`` with ``label="index"`` — chunk-indexed elements
      (the moons elements zone). URL:
      ``position/{zone}/{zoom}/{chunk_idx}/{part}.bin.gz``. Entry:
      ``{shape, label, chunks, chunk_days, start_jd, parts}``.
    * ``chunked-parted`` with ``label="date"`` — date-segmented elements
      (the earth zone). URL: ``position/{zone}/{zoom}/{date}/{part}.bin.gz``.
      Entry: ``{shape, label, start_date, end_date, parts}``.

    The chebyshev-only shape (``chunked``, no parts axis) is folded in
    separately by the caller — it doesn't go through the snapshot pipeline.
    """
    if len(snaps) == 1 and snaps[0].time is None:
        return {"shape": "parted", "parts": snaps[0].num_parts}
    # Multi-snapshot zooms only carry timestamped streams. A bare `None`-time
    # entry mixed with timed ones means the producer is confused about shape.
    if any(s.time is None for s in snaps):
        raise ValueError(
            f"{zone} zoom={zoom} mixes timed snapshots with a None-time "
            f"snapshot; one zoom must be all-timed or single-static"
        )
    parts_set = {s.num_parts for s in snaps}
    if len(parts_set) != 1:
        raise ValueError(
            f"{zone} zoom={zoom} has uneven parts across snapshots "
            f"{parts_set}; the slim metadata shape assumes uniform parts"
        )
    parts = next(iter(parts_set))
    chunk_days_set = {s.chunk_days for s in snaps}
    if len(chunk_days_set) > 1:
        raise ValueError(
            f"{zone} zoom={zoom} mixes chunk_days values "
            f"{chunk_days_set}; one snapshot stream must use a single cadence"
        )
    chunk_days = next(iter(chunk_days_set))
    if chunk_days is not None:
        # Chunk-indexed: derive start_jd from the earliest snapshot's
        # validity window. Sorting by validity_start_jd avoids relying on
        # label format.
        snaps_sorted = sorted(snaps, key=lambda s: s.validity_start_jd)
        return {
            "shape": "chunked-parted",
            "label": "index",
            "chunks": len(snaps_sorted),
            "chunk_days": chunk_days,
            "start_jd": snaps_sorted[0].validity_start_jd,
            "parts": parts,
        }
    # Date-segmented: labels are ISO dates, sort lexicographically.
    dated = sorted(s.time for s in snaps if s.time is not None)
    return {
        "shape": "chunked-parted",
        "label": "date",
        "start_date": dated[0],
        "end_date": dated[-1],
        "parts": parts,
    }


def build_position_metadata(
    zone_structure: Mapping[str, Mapping[int, ZoomSnapshots]],
    chebyshev_zones: Mapping[str, dict],
    probe_zones: Mapping[str, dict] | None = None,
) -> dict:
    """Build the unified ``position.zones`` metadata block.

    Folds the elements-side `zone_structure` (one entry per zone+zoom that
    emitted snapshots) and the chebyshev-side `chebyshev_zones` (one entry
    per zone that emitted chebyshev chunks; always at zoom 0) into a single
    map keyed by zone name. Each zoom carries a `shape` discriminator so
    consumers can build URLs without sniffing field presence:

    * ``parted`` — `{zone}/{zoom}/{part}.bin.gz`
    * ``chunked-parted`` — `{zone}/{zoom}/{label}/{part}.bin.gz`
    * ``chunked`` — `{zone}/{zoom}/{chunk}.bin.gz` (chebyshev)

    Each zone also carries `parent_id_type` (e.g. ``"naif"``, ``"spkid"``)
    naming the prefix the frontend should apply to col-2 numeric parent ids
    when rebuilding full ``Object.id`` strings. Chebyshev zones are always
    NAIF-keyed.
    """
    zones: dict[str, dict] = {}
    for zone, zoom_map in zone_structure.items():
        zooms: dict[str, dict] = {}
        parent_id_type: str | None = None
        for zoom, zoom_snaps in zoom_map.items():
            zooms[str(zoom)] = _build_position_zoom(zoom_snaps.snapshots, zone, zoom)
            if zoom_snaps.parent_id_type is not None:
                if parent_id_type is None:
                    parent_id_type = zoom_snaps.parent_id_type
                elif parent_id_type != zoom_snaps.parent_id_type:
                    raise ValueError(
                        f"{zone}: zooms disagree on parent_id_type "
                        f"({parent_id_type!r} vs {zoom_snaps.parent_id_type!r}) — "
                        f"the manifest emits one value per zone"
                    )
        if zooms:
            entry: dict = {"zooms": zooms}
            if parent_id_type is not None:
                entry["parent_id_type"] = parent_id_type
            zones[zone] = entry
    for zone, params in chebyshev_zones.items():
        # Chebyshev always sits at zoom 0; nothing else can land at the same
        # zone+zoom, so there's no collision to resolve.
        zone_entry = zones.setdefault(zone, {"zooms": {}})
        if "0" in zone_entry["zooms"]:
            raise ValueError(
                f"{zone}: chebyshev tried to claim zoom 0 but elements already "
                f"emitted there; one format per zone+zoom"
            )
        zone_entry["zooms"]["0"] = {
            "shape": "chunked",
            "chunks": params["chunks"],
            "chunk_days": params["chunk_days"],
            "start_jd": params["start_jd"],
            "end_jd": params["end_jd"],
        }
        zone_entry.setdefault("parent_id_type", "naif")
    # Probe zones have no zoom levels — emit the shape fields directly at
    # zone level (no `zooms` wrapper) so the URL is
    # `position/{zone}/{chunk}.bin.gz` without an interpolated zoom segment.
    for zone, params in (probe_zones or {}).items():
        if zone in zones:
            raise ValueError(
                f"{zone}: probes tried to claim a zone already in use by "
                f"elements/chebyshev"
            )
        zones[zone] = {
            "shape": "chunked",
            "chunks": params["chunks"],
            "chunk_days": params["chunk_days"],
            "start_jd": params["start_jd"],
            "end_jd": params["end_jd"],
            "subchunk_days": params["subchunk_days"],
            "float64_coeffs": params["float64_coeffs"],
            "fit_center_naif_id": params["fit_center_naif_id"],
            "parent_id_type": "probe",
            "present": params["present"],
        }
    return {"zones": dict(sorted(zones.items()))}
