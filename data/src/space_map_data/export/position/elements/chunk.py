"""Write one (zone, zoom, part) chunk: position file with elements payload."""

import logging
from pathlib import Path

from space_map_data.export.position.elements import sidecar
from space_map_data.export.position.elements.writer import (
    write_elements,
    write_parabolic_elements,
    write_sgp4_elements,
)
from space_map_data.export.position.format import (
    UNBOUNDED_END_JD,
    UNBOUNDED_START_JD,
)
from space_map_data.export.objects.wikidata_claims import radius_km_from_claims
from space_map_data.export.quantities import UnitConverter
from space_map_data.export.wikidata import WikidataEntity
from space_map_data.models.object import Object, OrbitalSource
from space_map_data.utils.paths import DOWNLOAD_DIR, SOURCES_POSITION_DIR

logger = logging.getLogger(__name__)

CHUNK_SIZE = 10_000

# Days of slack to add around the spread of TLE epochs when bounding an SGP4
# file's validity window. TLE accuracy degrades quickly and the SGP4
# propagator itself errors out a year or two past epoch — ±14d is the
# conventional "still reasonably accurate" window for LEO.
SGP4_VALIDITY_SLACK_DAYS = 14.0


def _earth_day_dir(date_iso: str) -> Path:
    """Map a snapshot's `YYYY-MM-DD` label to its CelesTrak day-dir on disk.

    The downloader stores each day at
    `sources/position/celestrak/{YYYY}/{MM}/{DD}/` (zero-padded month/day).
    The sidecar fingerprints the CSVs in that dir to decide whether to
    re-encode a part.
    """
    year, month, day = date_iso.split("-")
    return SOURCES_POSITION_DIR / "celestrak" / year / month / day


def _sgp4_validity_window(objects: list[Object]) -> tuple[float, float]:
    """Derive [start_jd, end_jd] for an SGP4 file from the epoch spread.

    Earth satellites are celestrak-source — kepler elements (including
    epoch_jd) are attached as a transient ``_daily_kepler`` dict by the
    overlay. Falls back to unbounded when no object carries an epoch
    (shouldn't happen for valid TLEs but keeps behaviour defined).
    """
    epochs: list[float] = []
    for o in objects:
        daily = getattr(o, "_daily_kepler", None)
        epoch = daily["epoch_jd"] if daily is not None else None
        if epoch is not None:
            epochs.append(epoch)
    if not epochs:
        return UNBOUNDED_START_JD, UNBOUNDED_END_JD
    return min(epochs) - SGP4_VALIDITY_SLACK_DAYS, max(
        epochs
    ) + SGP4_VALIDITY_SLACK_DAYS


def write_chunk(
    objects: list[Object],
    out_dir: Path,
    zone: str,
    zoom: int,
    part: int,
    chunk_entities: dict[str, WikidataEntity | None],
    has_localized: dict[str, bool],
    units: UnitConverter,
    orbital_source: OrbitalSource,
    time: str | None = None,
    validity_start_jd: float = UNBOUNDED_START_JD,
    validity_end_jd: float = UNBOUNDED_END_JD,
) -> int:
    """Write the position file for one (zone, zoom, part[, time]) chunk.

    `has_localized` is keyed by object id (built once per zone by
    :func:`build_chunk_object_data`); each row's bit goes into the binary's
    last column so the frontend can skip detail-bundle fetches for objects
    with no Wikidata at all.

    `orbital_source` is stamped in the file header; writer raises if any row
    disagrees. The file's id-type is also stamped in the header so the
    frontend can rebuild full `<prefix>-<numeric>` IDs from binary column 0.
    `time` is the per-snapshot directory between zoom and part — ISO date
    (Earth) or a numeric chunk index (time-chunked moons).
    `validity_start_jd`/`validity_end_jd` go into the binary header so
    consumers know when the file's elements are accurate. Earth zone
    overrides them with the SGP4-specific epoch-spread window (those need a
    tighter bound than 6 months); moons keep the chunk's [start, end].
    Returns the size of the binary file in bytes.
    """
    chunk_dir = out_dir / "position" / zone / str(zoom)
    if time is not None:
        chunk_dir = chunk_dir / time
    out_path = chunk_dir / f"{part}.bin.gz"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    radius_km_overrides: dict[str, float] = {}
    for obj in objects:
        qid = obj.wikidata_qid or (
            obj.satcat.wikidata_qid
            if obj.norad_cat_id is not None and obj.satcat
            else None
        )
        if qid and (wd := chunk_entities.get(qid)):
            try:
                r = radius_km_from_claims(wd["claims"], units, qid=qid)
            except Exception as exc:
                logger.error(
                    "Error extracting radius for %s (%s): %s",
                    obj.id,
                    qid,
                    exc,
                )
                r = None
            if r is not None:
                radius_km_overrides[obj.id] = r
    # SGP4 (Earth satellites) needs a tight validity window — the propagator
    # blows up past ~a year from epoch and spammy warnings are not useful.
    # Kepler/parabolic orbits are mathematical solutions with no hard cutoff,
    # so they default to whatever the caller passed (unbounded for static
    # zones, the time-chunk's [start, end] for time-chunked moons).
    start_jd = validity_start_jd
    end_jd = validity_end_jd
    sidecar_path: Path | None = None
    signature: dict | None = None
    if zone == "small_bodies/PAR":
        write_fn = write_parabolic_elements
    elif zone == "earth":
        write_fn = write_sgp4_elements
        start_jd, end_jd = _sgp4_validity_window(objects)
        # Earth parts come from per-day CelesTrak CSVs that the downloader
        # writes once and never edits. If the CSV fingerprints + the encoding
        # version match an existing binary's sidecar, the part contents are
        # determined entirely by those inputs — skip the encode + gzip.
        assert time is not None, "earth zone snapshots must carry a date label"
        signature = sidecar.build_earth_part_signature(_earth_day_dir(time))
    else:
        write_fn = write_elements
    if zone.startswith("small_bodies/"):
        # SBDB ships its full catalog as one snapshot; the sidecar fingerprint
        # is shared across every small_bodies/* part. A re-download invalidates
        # all of them at once. No CelesTrak-style per-day variance.
        signature = sidecar.build_sbdb_part_signature(DOWNLOAD_DIR)
    if signature is not None:
        sidecar_path = sidecar.mirror_path(chunk_dir / f"{part}.meta.json")
        if out_path.exists() and sidecar.matches(sidecar_path, signature):
            return out_path.stat().st_size
    write_fn(
        objects,
        out_path,
        orbital_source,
        radius_km_overrides or None,
        has_localized=has_localized,
        start_jd=start_jd,
        end_jd=end_jd,
    )
    if sidecar_path is not None and signature is not None:
        sidecar.write_sidecar(sidecar_path, signature)
    return out_path.stat().st_size
