"""Write a position file with the elements columnar payload.

The 32-byte header (common 24 + elements extension 8) is written first; then
columns 0–N follow exactly as in v6, with no other on-disk change. The format
byte at offset 6 is `FORMAT_ELEMENTS`; the sub_format at offset 24 picks
Keplerian / Parabolic / SGP4 column layouts.
"""

import gzip
import io
import logging
import struct
from datetime import date
from pathlib import Path

from space_map_data.constants.providers import ID_TYPES
from space_map_data.export.position.format import (
    ELEMENTS_FLAG_NEO,
    ELEMENTS_FLAG_PHA,
    ID_TYPE_ORDINAL,
    MISSING_FLOAT32,
    MISSING_FLOAT64,
    MISSING_ID_TYPE,
    MISSING_INT32,
    MISSING_UINT8,
    OBJECT_TYPE_ORDINAL,
    SCALE_ORDINAL,
    SOURCE_ORDINAL,
    SUBFORMAT_PARABOLIC,
    SUBFORMAT_SGP4,
    UNBOUNDED_END_JD,
    UNBOUNDED_START_JD,
    align8,
    pack_elements_header,
)
from space_map_data.models.object import Object, OrbitalSource
from space_map_data.utils.convert import date_to_julian
from space_map_data.utils.time import J2000_JD, year_to_jd

logger = logging.getLogger(__name__)

_REQUIRED_KEPLERIAN = {"epoch_jd", "a", "e", "i", "om", "w", "ma", "n"}
_REQUIRED_SGP4 = ("BSTAR", "MEAN_MOTION_DOT", "MEAN_MOTION_DDOT")

_AU_KM = 149_597_870.7


def _kepler_attr(o: Object, attr: str, file_source: OrbitalSource) -> float | None:
    """Read a unified-name kepler element off the right sub-table.

    Kepler elements live on the sub-tables; ``orbital_source`` says which to
    join. Horizons sub-table exposes unified-name properties (a, e, i, om, w,
    ma, n, epoch_jd) over its native column names; SBDB columns already match
    unified except for ``epoch`` (aliased to ``epoch_jd``). CelesTrak and
    Space-Track rows don't persist elements — the snapshot overlay attaches
    them as a transient ``_daily_kepler`` dict at export time. SBDBMoon stores ``a`` in
    km natively (``a_km``); we convert to AU on read so the small_body_moons
    zone ships system-scale values in the same units as the moons zone.

    Rows with ``orbital_source is None`` inherit the file source — that
    matches the assertion in :func:`_source_ordinal` (None rows are accepted
    and treated as the file's declared source).
    """
    src = o.orbital_source or file_source
    if src in (OrbitalSource.celestrak, OrbitalSource.spacetrack):
        daily = getattr(o, "_daily_kepler", None)
        return daily[attr] if daily is not None else None
    if src == OrbitalSource.sbdb:
        return getattr(o.sbdb, attr, None) if o.sbdb is not None else None
    if src == OrbitalSource.sbdb_moon:
        if o.sbdb_moon is None:
            return None
        if attr == "a":
            a_km = o.sbdb_moon.a_km
            return a_km / _AU_KM if a_km is not None else None
        return getattr(o.sbdb_moon, attr, None)
    if src == OrbitalSource.spice:
        return getattr(o.horizons, attr, None) if o.horizons is not None else None
    return None


def _drift_rate(o: Object, attr: str, file_source: OrbitalSource) -> float | None:
    """Read om_dot/w_dot off the Horizons sub-table (where SPICE writes them).

    Other sources don't fit secular drift, so they read as None.
    """
    src = o.orbital_source or file_source
    if src == OrbitalSource.spice:
        return getattr(o.horizons, attr, None) if o.horizons is not None else None
    return None


def _source_ordinal(objects: list[Object], orbital_source: OrbitalSource) -> int:
    """Assert that every row's `orbital_source` matches (or is None) and return the ordinal.

    Enforces the one-provider-per-file invariant: if an object disagrees with
    the declared file source, export fails loud rather than writing a
    mis-attributed file.
    """
    for o in objects:
        source = getattr(o, "_source_override", None) or o.orbital_source
        if source is not None and source != orbital_source:
            raise ValueError(
                f"{o.id}: orbital_source {source!r} does not match "
                f"file source {orbital_source!r}"
            )
    return SOURCE_ORDINAL[orbital_source]


def _id_type_ordinal(objects: list[Object]) -> int:
    """Pick the file's id-type ordinal from the first row and assert uniformity.

    Each (zone, zoom) query in export/common.py is single-typed by construction
    (the filters select on the id-type-defining column), so the prefix can ride
    in the file header — frontend rebuilds `<prefix>-<column0>` from this byte.
    A mixed file would route bundle lookups to the wrong hash bucket on the
    frontend, so fail loud rather than ship wrong IDs.

    Empty file → MISSING_ID_TYPE; no rows means nothing to reconstruct.
    Unknown prefix on the first row → MISSING_ID_TYPE (preserves the existing
    `_parse_numeric_id` warn-and-continue behaviour for ID types we don't ship).
    """
    if not objects:
        return MISSING_ID_TYPE
    first_prefix = _id_prefix(objects[0])
    expected = ID_TYPE_ORDINAL.get(ID_TYPES(first_prefix)) if first_prefix else None
    if expected is None:
        return MISSING_ID_TYPE
    for o in objects[1:]:
        prefix = _id_prefix(o)
        if prefix != first_prefix:
            raise ValueError(
                f"{o.id}: id type {prefix!r} does not match file id type "
                f"{first_prefix!r} (rows in one file must share an id type)"
            )
    return expected


def _id_prefix(obj: Object) -> str | None:
    """Return the `<prefix>` portion of `Object.id`, or None on malformed IDs."""
    pos = obj.id.find("-")
    if pos == -1:
        return None
    return obj.id[:pos]


def _write_keplerian_columns(
    buf: io.BytesIO,
    objects: list[Object],
    radius_km_overrides: dict[str, float] | None,
    file_source: OrbitalSource,
) -> None:
    """Write columns 0–12 shared by the Keplerian and SGP4 sub-formats.

    The trailing `has_localized` byte (last column of every sub-format) is
    written by the format-specific function, not here, since it sits past
    sub-format-specific columns.
    """
    n = len(objects)

    _write_int32(buf, n, [_parse_numeric_id(o) for o in objects])

    _write_uint8(
        buf,
        n,
        [OBJECT_TYPE_ORDINAL.get(o.object_type, MISSING_UINT8) for o in objects],
    )

    # TODO: move to header when possible (most times, need another export type)
    _write_int32(
        buf,
        n,
        [_parent_numeric_id(o) for o in objects],
    )

    _write_uint8(
        buf,
        n,
        [SCALE_ORDINAL.get(o.scale, MISSING_UINT8) for o in objects],
    )

    _write_float64(buf, n, [_float_value(o, "epoch_jd", file_source) for o in objects])

    for attr in ("a", "e", "i", "om", "w", "ma", "n"):
        _write_float32(
            buf,
            n,
            [_float_value(o, attr, file_source) for o in objects],
        )

    _write_float32(buf, n, [_radius_km(o, radius_km_overrides) for o in objects])


def write_elements(
    objects: list[Object],
    out_file: Path,
    orbital_source: OrbitalSource,
    radius_km_overrides: dict[str, float] | None = None,
    *,
    has_localized: dict[str, bool],
    start_jd: float = UNBOUNDED_START_JD,
    end_jd: float = UNBOUNDED_END_JD,
) -> None:
    """Write a Keplerian elements file (sub_format=0).

    Columns 0–12 are the shared Keplerian layout. Columns 13–14 (`om_dot`,
    `w_dot`, float32, deg/day) carry the secular drift rates that SPICE
    populates for non-whitelisted moons via the Method C mean-element fit.
    Other sources (Horizons, SBDB) leave them as zero and the frontend's
    Kepler propagation reduces to plain mean-anomaly drift. Column 15
    (`has_localized`, uint8 0/1) tells the frontend whether to even attempt
    a localized object-detail bundle fetch — set when any language has data.
    Column 16 (`flags`, uint8) packs per-point SBDB bits (NEO, PHA). Column 17
    (`visible_from_days`, float32) is days from J2000 to when the object came
    into existence (SBDB discovery here), or NaN when it should always be
    visible (see `_visible_from_days`).

    `start_jd`/`end_jd` bound the file's validity; ±inf means unbounded.
    Raises ValueError if a required orbital element is None, or if any row's
    `orbital_source` disagrees with the file source.
    """
    n = len(objects)
    source = _source_ordinal(objects, orbital_source)
    id_type = _id_type_ordinal(objects)
    buf = io.BytesIO()
    buf.write(
        pack_elements_header(
            n,
            source_ordinal=source,
            id_type_ordinal=id_type,
            start_jd=start_jd,
            end_jd=end_jd,
        )
    )
    _write_keplerian_columns(buf, objects, radius_km_overrides, orbital_source)

    for attr in ("om_dot", "w_dot"):
        _write_float32(
            buf,
            n,
            [_optional_float(o, attr, orbital_source) for o in objects],
        )

    _write_has_localized(buf, objects, has_localized)
    _write_flags(buf, objects)
    _write_visible_from_days(buf, objects, start_jd)

    out_file.write_bytes(gzip.compress(buf.getvalue()))


def write_sgp4_elements(
    objects: list[Object],
    out_file: Path,
    orbital_source: OrbitalSource,
    radius_km_overrides: dict[str, float] | None = None,
    *,
    has_localized: dict[str, bool],
    start_jd: float = UNBOUNDED_START_JD,
    end_jd: float = UNBOUNDED_END_JD,
) -> None:
    """Write an SGP4 elements file (sub_format=2).

    Columns 0–12 match the Keplerian layout; columns 13–17 carry the extra
    TLE/OMM fields needed by satellite.js `json2satrec`: BSTAR, MEAN_MOTION_DOT,
    MEAN_MOTION_DDOT (float32), ELEMENT_SET_NO, REV_AT_EPOCH (int32). Column
    18 (`has_localized`, uint8 0/1) gates localized object-detail fetches.
    Column 19 (`flags`, uint8) is always zero for SGP4 (no SBDB sub-table)
    but is emitted for layout uniformity with the Keplerian sub-format.
    Column 20 (`visible_from_days`, float32) is days from J2000 to the
    satellite's SATCAT launch date, or NaN when unknown/always-visible.

    `start_jd`/`end_jd` bound the file's validity. TLEs lose accuracy fast
    past their epoch and the SGP4 propagator blows up entirely a year or two
    out, so callers should pass a tight window (typically ±14 days around the
    epoch spread).

    Raises ValueError when a required SGP4 field is missing on any row, or if
    any row's `orbital_source` disagrees with the file source.
    """
    n = len(objects)
    source = _source_ordinal(objects, orbital_source)
    id_type = _id_type_ordinal(objects)
    buf = io.BytesIO()
    buf.write(
        pack_elements_header(
            n,
            SUBFORMAT_SGP4,
            source_ordinal=source,
            id_type_ordinal=id_type,
            start_jd=start_jd,
            end_jd=end_jd,
        )
    )
    _write_keplerian_columns(buf, objects, radius_km_overrides, orbital_source)

    for attr in _REQUIRED_SGP4:
        _write_float32(buf, n, [_required_sgp4_float(o, attr) for o in objects])

    _write_int32(
        buf,
        n,
        [_sgp4_int(o, "ELEMENT_SET_NO") for o in objects],
    )

    _write_int32(
        buf,
        n,
        [_sgp4_int(o, "REV_AT_EPOCH") for o in objects],
    )

    _write_has_localized(buf, objects, has_localized)
    _write_flags(buf, objects)
    _write_visible_from_days(buf, objects, start_jd)

    out_file.write_bytes(gzip.compress(buf.getvalue()))


def write_parabolic_elements(
    objects: list[Object],
    out_file: Path,
    orbital_source: OrbitalSource,
    radius_km_overrides: dict[str, float] | None = None,
    *,
    has_localized: dict[str, bool],
    start_jd: float = UNBOUNDED_START_JD,
    end_jd: float = UNBOUNDED_END_JD,
) -> None:
    """Write a parabolic elements file (sub_format=1).

    Columns: id, object_type, parent_id, scale, epoch_jd, q, e, i, om, w, tp,
    radius_km, has_localized, flags, visible_from_days. `has_localized` (uint8
    0/1) gates localized object-detail fetches in the frontend; `flags` (uint8)
    packs per-point SBDB bits (NEO, PHA); `visible_from_days` (float32) is days
    from J2000 to the SBDB discovery date, NaN when always-visible. `start_jd`/
    `end_jd` bound the file's validity; ±inf means unbounded. Raises ValueError
    if a required element
    (q, tp, e, i, om, w) is missing, or if any row's `orbital_source`
    disagrees with the file source.
    """
    n = len(objects)
    source = _source_ordinal(objects, orbital_source)
    id_type = _id_type_ordinal(objects)
    buf = io.BytesIO()

    buf.write(
        pack_elements_header(
            n,
            SUBFORMAT_PARABOLIC,
            source_ordinal=source,
            id_type_ordinal=id_type,
            start_jd=start_jd,
            end_jd=end_jd,
        )
    )

    _write_int32(buf, n, [_parse_numeric_id(o) for o in objects])
    _write_uint8(
        buf,
        n,
        [OBJECT_TYPE_ORDINAL.get(o.object_type, MISSING_UINT8) for o in objects],
    )
    _write_int32(
        buf,
        n,
        [_parent_numeric_id(o) for o in objects],
    )
    _write_uint8(
        buf,
        n,
        [SCALE_ORDINAL.get(o.scale, MISSING_UINT8) for o in objects],
    )

    _write_float64(
        buf, n, [_required_float(o, "epoch_jd", orbital_source) for o in objects]
    )

    _write_float32(buf, n, [_required_sbdb_float(o, "q") for o in objects])

    for attr in ("e", "i", "om", "w"):
        _write_float32(
            buf, n, [_required_float(o, attr, orbital_source) for o in objects]
        )

    _write_float64(buf, n, [_required_sbdb_float(o, "tp") for o in objects])

    _write_float32(buf, n, [_radius_km(o, radius_km_overrides) for o in objects])

    _write_has_localized(buf, objects, has_localized)
    _write_flags(buf, objects)
    _write_visible_from_days(buf, objects, start_jd)

    out_file.write_bytes(gzip.compress(buf.getvalue()))


_ID_TYPE_ATTR: dict[str, str] = {
    "naif": "naif_id",
    "spkid": "spkid",
    "norad_satcat": "norad_cat_id",
}


def _parse_numeric_id(obj: Object) -> int:
    """Return the source-specific numeric ID for the binary export.

    Uses the proper column (naif_id, spkid, or norad_cat_id) based on the
    Object.id prefix (ID_TYPE).
    """
    pos = obj.id.find("-")
    if pos == -1:
        logger.warning("%s: no separator in object ID", obj.id)
        return MISSING_INT32
    id_type = obj.id[:pos]

    attr = _ID_TYPE_ATTR.get(id_type)
    if attr is not None:
        val = getattr(obj, attr)
        if val is not None:
            return val
        logger.warning("%s: missing %s for binary export", obj.id, attr)
    else:
        logger.warning("%s: unknown ID type '%s' for numeric ID", obj.id, id_type)
    return MISSING_INT32


def _parent_numeric_id(obj: Object) -> int:
    """Extract the numeric portion of the parent's Object.id for col 2.

    The parent id-type is uniform per zone (currently always ``naif`` —
    a per-zone parent_id_type override is planned). Frontend rebuilds the
    parent's full Object.id from this column plus the zone's parent id-type.
    """
    if obj.parent_id is None:
        return MISSING_INT32
    pos = obj.parent_id.rfind("-")
    if pos == -1:
        logger.warning("%s: no separator in parent_id %r", obj.id, obj.parent_id)
        return MISSING_INT32
    tail = obj.parent_id[pos + 1 :]
    try:
        return int(tail)
    except ValueError:
        logger.warning("%s: non-numeric parent_id tail %r", obj.id, tail)
        return MISSING_INT32


def _float_value(o: Object, attr: str, file_source: OrbitalSource) -> float:
    """Get the float64 value for a Keplerian column.

    Reads from the per-source sub-table (or transient daily-overlay for
    celestrak). Raises ValueError if a required element is missing, unless
    the orbit quality is known-bad (condition_code 9).
    """
    val = _kepler_attr(o, attr, file_source)
    if attr in _REQUIRED_KEPLERIAN and val is None:
        sbdb = o.sbdb if o.spkid is not None else None
        if sbdb and sbdb.condition_code == "9":
            logger.warning("%s: missing required orbital element '%s'", o.id, attr)
        else:
            raise ValueError(f"{o.id}: missing required orbital element '{attr}'")
        return MISSING_FLOAT64
    return val if val is not None else MISSING_FLOAT64


def _required_float(o: Object, attr: str, file_source: OrbitalSource) -> float:
    """Get a required float64 element from the appropriate sub-table."""
    val = _kepler_attr(o, attr, file_source)
    if val is None:
        raise ValueError(f"{o.id}: missing required element '{attr}'")
    return val


def _optional_float(o: Object, attr: str, file_source: OrbitalSource) -> float:
    """Get an optional secular drift rate (om_dot/w_dot), returning 0.0 when missing.

    SPICE populates these on the Horizons sub-table for non-whitelisted moons;
    other sources don't fit them. Treating None as zero rather than NaN means
    the frontend's `angle += rate·dt` step is a no-op for sources that didn't
    fit them.
    """
    val = _drift_rate(o, attr, file_source)
    return val if val is not None else 0.0


def _required_sbdb_float(o: Object, attr: str) -> float:
    """Get a required float64 from the SBDB relation, raising ValueError if missing."""
    sbdb = o.sbdb if o.spkid is not None else None
    if sbdb is None:
        raise ValueError(f"{o.id}: no SBDB data for parabolic element '{attr}'")
    val = getattr(sbdb, attr)
    if val is None:
        raise ValueError(f"{o.id}: parabolic comet missing '{attr}'")
    return val


def _required_sgp4_float(o: Object, key: str) -> float:
    """Required SGP4 float from the transient ``_daily_kepler`` overlay dict.

    The overlay (CelesTrak daily or Space-Track archive) attaches every SGP4
    field there, so satcat-only Objects with no CelesTrak sub-table row still
    export. Raises if the overlay didn't run or the field is absent.
    """
    daily = getattr(o, "_daily_kepler", None)
    val = daily.get(key) if daily is not None else None
    if val is None:
        raise ValueError(f"{o.id}: missing required SGP4 field '{key}'")
    return val


def _sgp4_int(o: Object, key: str) -> int:
    """Optional SGP4 int from ``_daily_kepler``; MISSING_INT32 when absent."""
    daily = getattr(o, "_daily_kepler", None)
    val = daily.get(key) if daily is not None else None
    return val if val is not None else MISSING_INT32


def _radius_km(o: Object, overrides: dict[str, float] | None = None) -> float:
    """Get object radius in km from SBDB diameter or overrides."""
    if o.spkid is not None and o.sbdb is not None and o.sbdb.diameter is not None:
        return o.sbdb.diameter / 2.0
    if overrides and (r := overrides.get(o.id)):
        return r
    return MISSING_FLOAT64


def _write_has_localized(
    f, objects: list[Object], has_localized: dict[str, bool]
) -> None:
    """Write the `has_localized` uint8 column."""
    n = len(objects)
    _write_uint8(f, n, [1 if has_localized.get(o.id) else 0 for o in objects])


def _flags_byte(o: Object) -> int:
    """Pack SBDB-derived per-point flags. Zero for rows without an SBDB row."""
    sbdb = o.sbdb if o.spkid is not None else None
    if sbdb is None:
        return 0
    bits = 0
    if sbdb.neo:
        bits |= ELEMENTS_FLAG_NEO
    if sbdb.pha:
        bits |= ELEMENTS_FLAG_PHA
    return bits


def _write_flags(f, objects: list[Object]) -> None:
    """Write the `flags` uint8 column (precedes `visible_from_days` on v11+)."""
    n = len(objects)
    _write_uint8(f, n, [_flags_byte(o) for o in objects])


def _iso_date_to_jd(value: str) -> float | None:
    """Parse a `YYYY-MM-DD` or bare `YYYY` date string to a JD."""
    s = value.strip()
    try:
        return date_to_julian(date.fromisoformat(s))
    except ValueError:
        pass
    try:
        return year_to_jd(int(s))
    except ValueError:
        return None


def _origin_date(o: Object) -> str | None:
    """Origin date as an ISO date or bare year: discovery for small bodies
    (SBDB `first_obs`) and their moons (SBDBMoon `year`), launch for Earth sats
    (SATCAT `launch_date`).

    Each relation is eager-loaded only in its own zone, so gate on a scalar
    column first — a bare access would lazy-load in a worker thread.
    """
    if o.spkid is not None and o.sbdb is not None:
        return o.sbdb.first_obs
    if o.satcat_norad_cat_id is not None and o.satcat is not None:
        return o.satcat.launch_date
    if o.orbital_source == OrbitalSource.sbdb_moon and o.sbdb_moon is not None:
        year = o.sbdb_moon.year
        return str(year) if year is not None else None
    return None


def _visible_from_days(o: Object, start_jd: float) -> float:
    """Days from J2000 to when `o` first exists, or NaN ("always visible").

    NaN means no gating: missing/unparseable date, or one at/before `start_jd`
    (already existed when the chunk opens). The compare only bites bounded zones
    (Earth sats); SBDB files are unbounded.
    """
    origin = _origin_date(o)
    if origin is None:
        return MISSING_FLOAT32
    jd = _iso_date_to_jd(origin)
    if jd is None or jd <= start_jd:
        return MISSING_FLOAT32
    return jd - J2000_JD


def _write_visible_from_days(f, objects: list[Object], start_jd: float) -> None:
    """Write the trailing `visible_from_days` float32 column (last on v11+)."""
    n = len(objects)
    _write_float32(f, n, [_visible_from_days(o, start_jd) for o in objects])


def _write_int32(f, n: int, values: list[int]) -> None:
    f.write(struct.pack(f"<{n}i", *values))
    _pad8(f, n * 4)


def _write_uint8(f, n: int, values: list[int]) -> None:
    f.write(struct.pack(f"<{n}B", *values))
    _pad8(f, n)


def _write_float32(f, n: int, values: list[float]) -> None:
    f.write(struct.pack(f"<{n}f", *values))
    _pad8(f, n * 4)


def _write_float64(f, n: int, values: list[float]) -> None:
    f.write(struct.pack(f"<{n}d", *values))


def _pad8(f, written: int) -> None:
    pad = align8(written) - written
    if pad:
        f.write(b"\x00" * pad)
