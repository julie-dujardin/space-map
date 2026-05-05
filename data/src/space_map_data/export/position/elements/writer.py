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
from pathlib import Path

from space_map_data.constants.providers import ID_TYPES
from space_map_data.export.position.format import (
    ID_TYPE_ORDINAL,
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

logger = logging.getLogger(__name__)

_REQUIRED_KEPLERIAN = {"epoch_jd", "a", "e", "i", "om", "w", "ma", "n"}
_REQUIRED_SGP4 = ("BSTAR", "MEAN_MOTION_DOT", "MEAN_MOTION_DDOT")


def _source_ordinal(objects: list[Object], orbital_source: OrbitalSource) -> int:
    """Assert that every row's `orbital_source` matches (or is None) and return the ordinal.

    Enforces the one-provider-per-file invariant: if an object disagrees with
    the declared file source, export fails loud rather than writing a
    mis-attributed file.
    """
    for o in objects:
        if o.orbital_source is not None and o.orbital_source != orbital_source:
            raise ValueError(
                f"{o.id}: orbital_source {o.orbital_source!r} does not match "
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

    # TODO: drop naif it can be not NAIF
    # TODO: move to header when possible (most times, need another export type)
    _write_int32(
        buf,
        n,
        [
            o.parent_naif_id if o.parent_naif_id is not None else MISSING_INT32
            for o in objects
        ],
    )

    _write_uint8(
        buf,
        n,
        [SCALE_ORDINAL.get(o.scale, MISSING_UINT8) for o in objects],
    )

    _write_float64(buf, n, [_float_value(o, "epoch_jd") for o in objects])

    for attr in ("a", "e", "i", "om", "w", "ma", "n"):
        _write_float32(
            buf,
            n,
            [_float_value(o, attr) for o in objects],
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
    _write_keplerian_columns(buf, objects, radius_km_overrides)

    for attr in ("om_dot", "w_dot"):
        _write_float32(
            buf,
            n,
            [_optional_float(o, attr) for o in objects],
        )

    _write_has_localized(buf, objects, has_localized)

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
    _write_keplerian_columns(buf, objects, radius_km_overrides)

    for attr in _REQUIRED_SGP4:
        _write_float32(buf, n, [_required_celestrak_float(o, attr) for o in objects])

    _write_int32(
        buf,
        n,
        [_celestrak_int(o, "ELEMENT_SET_NO") for o in objects],
    )

    _write_int32(
        buf,
        n,
        [_celestrak_int(o, "REV_AT_EPOCH") for o in objects],
    )

    _write_has_localized(buf, objects, has_localized)

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
    radius_km, has_localized. `has_localized` (uint8 0/1) gates localized
    object-detail fetches in the frontend. `start_jd`/`end_jd` bound the
    file's validity; ±inf means unbounded. Raises ValueError if a required
    element (q, tp, e, i, om, w) is missing, or if any row's `orbital_source`
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
        [
            o.parent_naif_id if o.parent_naif_id is not None else MISSING_INT32
            for o in objects
        ],
    )
    _write_uint8(
        buf,
        n,
        [SCALE_ORDINAL.get(o.scale, MISSING_UINT8) for o in objects],
    )

    _write_float64(buf, n, [_required_float(o, "epoch_jd") for o in objects])

    _write_float32(buf, n, [_required_sbdb_float(o, "q") for o in objects])

    for attr in ("e", "i", "om", "w"):
        _write_float32(buf, n, [_required_float(o, attr) for o in objects])

    _write_float64(buf, n, [_required_sbdb_float(o, "tp") for o in objects])

    _write_float32(buf, n, [_radius_km(o, radius_km_overrides) for o in objects])

    _write_has_localized(buf, objects, has_localized)

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


def _float_value(o: Object, attr: str) -> float:
    """Get the float64 value for a Keplerian column.

    Raises ValueError if a required element is missing, unless the orbit
    quality is known-bad (condition_code 9).
    """
    if attr in _REQUIRED_KEPLERIAN:
        val = getattr(o, attr)
        if val is None:
            sbdb = o.sbdb if o.spkid is not None else None
            if sbdb and sbdb.condition_code == "9":
                logger.warning("%s: missing required orbital element '%s'", o.id, attr)
            else:
                raise ValueError(f"{o.id}: missing required orbital element '{attr}'")
            return MISSING_FLOAT64
        return val
    val = getattr(o, attr)
    return val if val is not None else MISSING_FLOAT64


def _required_float(o: Object, attr: str) -> float:
    """Get a required float64 attribute, raising ValueError if missing."""
    val = getattr(o, attr)
    if val is None:
        raise ValueError(f"{o.id}: missing required element '{attr}'")
    return val


def _optional_float(o: Object, attr: str) -> float:
    """Get an optional float attribute, returning 0.0 when missing.

    Used for secular drift columns (om_dot, w_dot) that SPICE populates only
    for moons. Treating None as zero rather than NaN means the frontend's
    `angle += rate·dt` step is a no-op for sources that didn't fit them.
    """
    val = getattr(o, attr, None)
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


def _required_celestrak_float(o: Object, attr: str) -> float:
    """Get a required float from the CelesTrak relation, raising ValueError if missing."""
    celestrak = o.celestrak if o.norad_cat_id is not None else None
    if celestrak is None:
        raise ValueError(f"{o.id}: no CelesTrak data for SGP4 field '{attr}'")
    val = getattr(celestrak, attr)
    if val is None:
        raise ValueError(f"{o.id}: CelesTrak missing required SGP4 field '{attr}'")
    return val


def _celestrak_int(o: Object, attr: str) -> int:
    """Get an optional int from the CelesTrak relation, returning MISSING_INT32 if absent."""
    celestrak = o.celestrak if o.norad_cat_id is not None else None
    if celestrak is None:
        return MISSING_INT32
    val = getattr(celestrak, attr)
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
    """Write the trailing `has_localized` uint8 column (last column of every sub-format)."""
    n = len(objects)
    _write_uint8(f, n, [1 if has_localized.get(o.id) else 0 for o in objects])


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
