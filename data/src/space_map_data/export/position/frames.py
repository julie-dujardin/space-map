"""Reference-frame normalisation for small-body moon orbits.

Everything the system-scale zones ship is ecliptic J2000, but the moon
sources don't agree on a frame: SBDB tags each satellite orbit ``EC`` or
``EQ`` and carries both, and AsterSat publishes every orbit as
``geoequat J2000``. The angles are rotated here, at the export boundary, so
the database keeps each source's numbers as published.
"""

import math

from space_map_data.models.object import AsterSatMoon, Object, OrbitalSource, SBDBMoon
from space_map_data.probes.propagation import AU_KM

# IAU 2006 mean obliquity of the ecliptic at J2000.
_OBLIQUITY_RAD = math.radians(23.4392911)
_COS_OBLIQUITY = math.cos(_OBLIQUITY_RAD)
_SIN_OBLIQUITY = math.sin(_OBLIQUITY_RAD)
_HOURS_PER_DAY = 24.0
# MJD 0 as a Julian Date; AsterSat prints epochs as MJD.
_MJD_OFFSET = 2_400_000.5

# Which sub-table an orbital source keeps its moon elements on. A new moon
# provider is an entry here rather than a branch in each of the two writers.
MOON_ORBIT_ATTR: dict[OrbitalSource, str] = {
    OrbitalSource.sbdb_moon: "sbdb_moon",
    OrbitalSource.astersat: "astersat_moon",
}


def is_equatorial(frame: str | None) -> bool:
    """True when a source's frame label means the Earth equator, not the ecliptic.

    SBDB writes ``EQ``/``EC``; AsterSat writes ``geoequat J2000``. An unlabelled
    orbit is read as ecliptic, which is what SBDB's element titles claim and
    what the export has always assumed.
    """
    if not frame:
        return False
    return frame.upper().startswith("EQ") or "EQUAT" in frame.upper()


def equatorial_to_ecliptic_vector(
    v: tuple[float, float, float],
) -> tuple[float, float, float]:
    """Rotate a vector from the Earth equator of J2000 onto the ecliptic."""
    return (
        v[0],
        v[1] * _COS_OBLIQUITY + v[2] * _SIN_OBLIQUITY,
        -v[1] * _SIN_OBLIQUITY + v[2] * _COS_OBLIQUITY,
    )


def equatorial_to_ecliptic(
    i_deg: float, om_deg: float, w_deg: float | None = None
) -> tuple[float, float, float | None]:
    """Rotate an orbit's orientation angles from the equator to the ecliptic.

    Only the orientation moves: a, e, the mean anomaly and the mean motion are
    in-plane or temporal and are the same in both frames. ``w`` is optional —
    plenty of SBDB satellite orbits give the plane but not the apse line, and
    the plane alone is still worth stating correctly.
    """
    i, om = math.radians(i_deg), math.radians(om_deg)
    w = math.radians(w_deg if w_deg is not None else 0.0)
    sin_i, cos_i = math.sin(i), math.cos(i)
    sin_om, cos_om = math.sin(om), math.cos(om)
    sin_w, cos_w = math.sin(w), math.cos(w)

    # Periapsis direction and orbit normal in the source frame.
    peri = (
        cos_om * cos_w - sin_om * sin_w * cos_i,
        sin_om * cos_w + cos_om * sin_w * cos_i,
        sin_w * sin_i,
    )
    normal = (sin_om * sin_i, -cos_om * sin_i, cos_i)

    peri, normal = (
        equatorial_to_ecliptic_vector(peri),
        equatorial_to_ecliptic_vector(normal),
    )

    i_out = math.acos(max(-1.0, min(1.0, normal[2])))
    if math.sin(i_out) < 1e-12:
        # An equatorial orbit has no node to measure from; fold the whole
        # orientation into w so peri still points the right way.
        om_out = 0.0
        w_out = math.atan2(peri[1], peri[0])
    else:
        om_out = math.atan2(normal[0], -normal[1])
        w_out = math.atan2(
            peri[2] / math.sin(i_out),
            peri[0] * math.cos(om_out) + peri[1] * math.sin(om_out),
        )
    return (
        math.degrees(i_out) % 360.0,
        math.degrees(om_out) % 360.0,
        math.degrees(w_out) % 360.0 if w_deg is not None else None,
    )


def moon_orbit(obj: Object, source: OrbitalSource | None) -> dict[str, float]:
    """Canonical ecliptic-J2000 elements for one small-body moon.

    Returns only the elements the source actually has, so a caller can test
    for the full Keplerian set by membership; a body with no moon row, or one
    from a source that isn't a moon provider, yields nothing.
    """
    attr = MOON_ORBIT_ATTR.get(source) if source is not None else None
    moon: SBDBMoon | AsterSatMoon | None = getattr(obj, attr) if attr else None
    if moon is None:
        return {}

    out: dict[str, float] = {}
    # AsterSat prints its epoch as an MJD; SBDB ships a Julian Date already.
    epoch = (
        moon.epoch_mjd + _MJD_OFFSET
        if isinstance(moon, AsterSatMoon)
        else moon.epoch_jd
    )
    if epoch is not None:
        out["epoch_jd"] = epoch
    if moon.a_km is not None:
        out["a"] = moon.a_km / AU_KM
    for key in ("e", "i", "om", "w", "ma", "n"):
        value = getattr(moon, key)
        if value is not None:
            out[key] = value
    # SBDB satellite orbits ship a period but never a mean motion.
    if "n" not in out and getattr(moon, "per_h", None):
        out["n"] = 360.0 * _HOURS_PER_DAY / moon.per_h

    if is_equatorial(moon.frame) and {"i", "om"} <= out.keys():
        i_out, om_out, w_out = equatorial_to_ecliptic(out["i"], out["om"], out.get("w"))
        out["i"], out["om"] = i_out, om_out
        if w_out is not None:
            out["w"] = w_out
    return out


def measured_moon_radius_km(obj: Object) -> float | None:
    """A small-body moon's published radius, where a source measured one.

    AsterSat prints a radius per component; Johnston a diameter. Neither body
    is likely to have the Wikidata item the usual radius override reads, so
    without this they render at the nominal size for an unknown body.

    Only the moon zones eager-load these rows, and the position writers run on
    objects the session has expunged, so a body from any other source has to
    return before a relationship is touched or the lazy load raises.
    """
    if obj.orbital_source not in MOON_ORBIT_ATTR:
        return None
    if obj.orbital_source is OrbitalSource.astersat:
        astersat = obj.astersat_moon
        if astersat is not None and astersat.satellite_radius_km is not None:
            return astersat.satellite_radius_km
    johnston = obj.johnston_moon
    if johnston is not None and johnston.diameter_km is not None:
        return johnston.diameter_km / 2
    return None


def moon_orbit_cached(obj: Object, source: OrbitalSource | None) -> dict[str, float]:
    """``moon_orbit`` memoised on the row.

    The elements file is written column by column, so an element accessor is
    reached once per column — eight times per moon, each redoing a frame
    rotation that couples i, om and w. Cached on the object like the
    ``_daily_kepler`` overlay the earth-satellite writers read.
    """
    cached = getattr(obj, "_moon_orbit", None)
    if cached is None:
        cached = moon_orbit(obj, source)
        obj._moon_orbit = cached  # type: ignore[attr-defined]
    return cached
