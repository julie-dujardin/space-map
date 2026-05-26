"""Plan/contribution/record types shared by the three writer passes.

`ProbeMeta` snapshots a probe's row in the DB. `ProbePlan` carries the
classify-pass output (which (zone, chunk) pairs the probe touches, and
which kernels are needed to fit them). `ChunkProbeRecord` is the fit-pass
output, packing-ready. The fit-pass forward type `LandedFit` is defined
in `landed.py` to keep SPICE deps out of this leaf module.
"""

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from space_map_data.export.position.format import (
    MISSING_ID_TYPE,
    MISSING_INT32,
    OBJECT_TYPE_ORDINAL,
)
from space_map_data.export.position.probes.sizing import SubChunkFit
from space_map_data.models.object import Object, OrbitalSource
from space_map_data.probes.zones import ALL_ZONES, ZONES_BY_KEY, Zone

if TYPE_CHECKING:
    from space_map_data.export.position.probes.landed import LandedFit


@dataclass(frozen=True)
class ProbeMeta:
    """Per-probe info needed at pack time."""

    probe_id: int
    obj_id: str
    object_type_ordinal: int
    has_localized: bool


@dataclass(frozen=True)
class ChunkContribution:
    """One probe's contribution to one (zone, chunk_idx): the time slice
    it covers.

    `kind="flying"` contributions go through `size_chunk` (Kepler/Chebyshev
    sub-chunks, sub-chunk-grid-aligned).

    `kind="landed"` contributions carry the landing body's NAIF; the fit
    pass samples lat/lng at fine cadence + decimates to daily-00:00-UTC
    anchors + 100 m motion thresholds, packing as a single trailing
    `METHOD_LANDED` record. Landed contributions don't snap to the sub-
    chunk grid — they cover the literal phase-within-chunk window.
    """

    zone_key: str
    chunk_idx: int
    c_start_et: float
    c_end_et: float
    kind: str = "flying"  # "flying" | "landed"
    landed_body_naif_id: int | None = None


@dataclass
class ProbePlan:
    """All chunks one probe touches + the kernels needed to fit them.
    Built in the classify pass; consumed in the fit pass."""

    probe_id: int
    naif_id: int
    kernels: list[Path]
    contributions: list[ChunkContribution] = field(default_factory=list)


@dataclass
class ChunkProbeRecord:
    """One probe's contribution to one chunk, packing-ready. Holds the
    fitted flying sub-chunks (may be empty if landed-only), an optional
    trailing `METHOD_LANDED`, and the fit center to encode in the header
    (sentinel pair = stay on the zone's stored center)."""

    probe_id: int
    first_offset: int
    fit_center_id_value: int = MISSING_INT32
    fit_center_id_type: int = MISSING_ID_TYPE
    flying: list[SubChunkFit] = field(default_factory=list)
    landed: "LandedFit | None" = None


def build_probe_metas(
    session: Session, has_localized: dict[str, bool]
) -> dict[int, ProbeMeta]:
    """Map probe_id → ProbeMeta for every probe Object row in the DB."""
    rows = session.execute(
        select(Object.id, Object.probe_id, Object.object_type).where(
            Object.orbital_source == OrbitalSource.spice_probe
        )
    ).all()
    metas: dict[int, ProbeMeta] = {}
    for row in rows:
        if row.probe_id is None:
            continue
        metas[row.probe_id] = ProbeMeta(
            probe_id=row.probe_id,
            obj_id=row.id,
            object_type_ordinal=OBJECT_TYPE_ORDINAL.get(row.object_type, 255),
            has_localized=bool(has_localized.get(row.id, False)),
        )
    return metas


# Bodies whose IAU-frame landed phases route to a zone whose `fit_center_naif_id`
# is *not* the body itself. Map: body_naif → zone key. Mercury/Venus/Earth/Mars
# match their planet zone directly via `fit_center_naif_id`; Moon and Titan
# need the explicit mapping (Moon→earth-moon, Titan→saturn — the zones we
# stream chunks for).
LANDED_BODY_TO_ZONE: dict[int, str] = {
    301: "earth-moon",
    606: "saturn",
}


def zone_for_landed_body(body_naif_id: int) -> Zone | None:
    """Return the streaming-chunk zone a landed phase on `body_naif_id`
    contributes to. Direct planet match if its fit_center matches the body
    (Mars 499, Earth 399, Venus 299, Mercury 199), else the explicit moon
    map; None if neither (no rendering path yet for the asteroid landers
    we'd want for Hayabusa/OSIRIS-REx)."""
    for z in ALL_ZONES:
        if z.fit_center_naif_id == body_naif_id:
            return z
    if body_naif_id in LANDED_BODY_TO_ZONE:
        return ZONES_BY_KEY.get(LANDED_BODY_TO_ZONE[body_naif_id])
    return None
