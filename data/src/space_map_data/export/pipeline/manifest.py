"""Build the unified ``position.zones`` manifest from per-zone snapshot streams."""

from collections.abc import Mapping
from dataclasses import dataclass, field

from space_map_data.export.pipeline.zone import SnapshotResult
from space_map_data.export.position.layout import zone_has_zoom_segment


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
    """Build one shape entry for a (zone, zoom) from its snapshots.

    The caller nests this under ``zooms/{zoom}`` for multi-zoom zones or splats
    it at zone level for flat single-zoom zones, so the ``{zoom}`` segment in
    the URLs below is present only for the former.

    Three shapes, dispatched on the snapshot stream:

    * ``parted`` — single snapshot with ``time is None``. URL:
      ``position/{zone}/[{zoom}/]{part}.bin.gz``. Entry: ``{shape, parts}``.
    * ``chunked-parted`` with ``label="index"`` — chunk-indexed elements
      (the moons elements zone). URL:
      ``position/{zone}/[{zoom}/]{chunk_idx}/{part}.bin.gz``. Entry:
      ``{shape, label, chunks, chunk_days, start_jd, parts}``.
    * ``chunked-parted`` with ``label="date"`` — date-segmented elements
      (the earth zone). URL: ``position/{zone}/[{zoom}/]{date}/{part}.bin.gz``.
      Entry: ``{shape, label, start_date, end_date, parts, parts_by_date}`` —
      ``parts_by_date`` maps each date to its part count (counts vary across
      dates); ``parts`` is the max as a convenience bound.

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
    chunk_days_set = {s.chunk_days for s in snaps}
    if len(chunk_days_set) > 1:
        raise ValueError(
            f"{zone} zoom={zoom} mixes chunk_days values "
            f"{chunk_days_set}; one snapshot stream must use a single cadence"
        )
    chunk_days = next(iter(chunk_days_set))
    if chunk_days is not None:
        # Chunk-indexed (moons): every chunk fits the same body set, so part
        # counts are uniform and the slim shape carries a single `parts`.
        parts_set = {s.num_parts for s in snaps}
        if len(parts_set) != 1:
            raise ValueError(
                f"{zone} zoom={zoom} has uneven parts across chunk snapshots "
                f"{parts_set}; the chunk-indexed shape assumes uniform parts"
            )
        # Derive start_jd from the earliest snapshot's validity window. Sorting
        # by validity_start_jd avoids relying on label format.
        snaps_sorted = sorted(snaps, key=lambda s: s.validity_start_jd)
        return {
            "shape": "chunked-parted",
            "label": "index",
            "chunks": len(snaps_sorted),
            "chunk_days": chunk_days,
            "start_jd": snaps_sorted[0].validity_start_jd,
            "parts": next(iter(parts_set)),
        }
    # Date-segmented (earth): part counts vary per date — historical weekly
    # snapshots carry the full decayed catalog while recent dailies are
    # smaller — so the manifest carries the count for each date. `parts` keeps
    # the max as a convenience bound.
    parts_by_date = {s.time: s.num_parts for s in snaps if s.time is not None}
    dated = sorted(parts_by_date)
    return {
        "shape": "chunked-parted",
        "label": "date",
        "start_date": dated[0],
        "end_date": dated[-1],
        "parts": max(parts_by_date.values()),
        "parts_by_date": parts_by_date,
    }


def build_position_metadata(
    zone_structure: Mapping[str, Mapping[int, ZoomSnapshots]],
    chebyshev_zones: Mapping[str, dict],
    probe_zones: Mapping[str, dict] | None = None,
) -> dict:
    """Build the unified ``position.zones`` metadata block.

    Folds the elements-side `zone_structure` (one entry per zone+zoom that
    emitted snapshots) and the chebyshev-side `chebyshev_zones` (one entry per
    zone that emitted chebyshev chunks; always at zoom 0) into a single map
    keyed by zone name.

    Multi-zoom zones (`major`, `small_bodies/{class}`) nest their shapes under
    a `zooms` map and keep a `{zoom}` URL segment. Structurally single-zoom
    zones are flat — the `shape` fields sit at zone level and the URL drops the
    segment (like probes). Each carries a `shape` discriminator so consumers
    build URLs without sniffing field presence (`[{zoom}/]` present only when
    the entry has a `zooms` wrapper):

    * ``parted`` — `{zone}/[{zoom}/]{part}.bin.gz`
    * ``chunked-parted`` — `{zone}/[{zoom}/]{label}/{part}.bin.gz`
    * ``chunked`` — `{zone}/[{zoom}/]{chunk}.bin.gz` (chebyshev)
    * ``probes`` — `{zone}/{chunk}.bin.gz` (always flat)

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
        if not zooms:
            continue
        if zone_has_zoom_segment(zone):
            entry: dict = {"zooms": zooms}
        else:
            if len(zooms) != 1:
                raise ValueError(
                    f"{zone}: flat zone emitted {len(zooms)} zooms; structurally "
                    f"single-zoom zones carry exactly one"
                )
            entry = next(iter(zooms.values()))
        if parent_id_type is not None:
            entry["parent_id_type"] = parent_id_type
        zones[zone] = entry
    for zone, params in chebyshev_zones.items():
        cheb_entry = {
            "shape": "chunked",
            "chunks": params["chunks"],
            "chunk_days": params["chunk_days"],
            "start_jd": params["start_jd"],
            "end_jd": params["end_jd"],
        }
        if zone_has_zoom_segment(zone):
            # `major` shares its zone with the Horizons elements tiers at zoom
            # 1/2, so chebyshev keeps zoom 0; nothing else can land there.
            zone_entry = zones.setdefault(zone, {"zooms": {}})
            if "0" in zone_entry["zooms"]:
                raise ValueError(
                    f"{zone}: chebyshev tried to claim zoom 0 but elements "
                    f"already emitted there; one format per zone+zoom"
                )
            zone_entry["zooms"]["0"] = cheb_entry
            zone_entry.setdefault("parent_id_type", "naif")
        else:
            # Flat single-tier zone (`major_asteroids`, `moons/<parent>`).
            if zone in zones:
                raise ValueError(
                    f"{zone}: chebyshev tried to claim a zone already in use by "
                    f"elements"
                )
            cheb_entry["parent_id_type"] = "naif"
            zones[zone] = cheb_entry
    # Probe zones are flat (no `zooms` wrapper). The distinct `probes` shape tag
    # separates them from flat chebyshev zones, which also sit at zone level.
    for zone, params in (probe_zones or {}).items():
        if zone in zones:
            raise ValueError(
                f"{zone}: probes tried to claim a zone already in use by "
                f"elements/chebyshev"
            )
        zones[zone] = {
            "shape": "probes",
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
