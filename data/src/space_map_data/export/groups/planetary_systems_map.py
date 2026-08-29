"""Planetary system minimaps: every system's moons on a log distance axis in
primary radii, for the tiles of the Planetary Systems collection page.

The system page builds the same picture from the live scene, which only
holds the active system's moons; the collection page needs all of them at
once, so the geometry is baked here. Background tiles carry no labels, so
no names ride along.
"""

import gzip
import logging
import math
from dataclasses import dataclass
from pathlib import Path

import orjson
from sqlalchemy.orm import Session

from space_map_data.export.notable import render_size
from space_map_data.export.objects.writer import _orbit_elements
from space_map_data.export.quantities import UnitConverter
from space_map_data.export.small_body_color import resolve_moon_color
from space_map_data.export.wikidata import WikidataEntityCache
from space_map_data.models.object.main import Object, ObjectType

logger = logging.getLogger(__name__)

_AU_KM = 149_597_870.7
_OBLIQUITY_RAD = math.radians(23.4392911)


@dataclass
class SystemMoon:
    id: str
    a_rp: float  # semi-major axis in primary equatorial radii
    tilt_deg: float  # orbit tilt to the primary's equator; > 90 is retrograde
    radius_km: float  # 0 → designation-only, drawn at the floor
    color: str | None


@dataclass
class SystemMap:
    barycenter_id: str
    primary_id: str
    primary_radius_km: float
    moons: list[SystemMoon]
    rings: dict | None  # {"inner_rp", "outer_rp"} across every ring bundle
    moon_count: int


def _pole_ecliptic(orientation: dict) -> tuple[float, float, float]:
    """The IAU pole as a unit vector in ecliptic J2000, the frame the moons'
    elements are in."""
    ra = math.radians(orientation["pole_ra_0"])
    dec = math.radians(orientation["pole_dec_0"])
    x = math.cos(dec) * math.cos(ra)
    y = math.cos(dec) * math.sin(ra)
    z = math.sin(dec)
    return (
        x,
        y * math.cos(_OBLIQUITY_RAD) + z * math.sin(_OBLIQUITY_RAD),
        -y * math.sin(_OBLIQUITY_RAD) + z * math.cos(_OBLIQUITY_RAD),
    )


def _tilt_to_equator(
    i_deg: float, om_deg: float, pole: tuple[float, float, float] | None
) -> float:
    """Angle between the orbit normal and the primary's pole; the ecliptic
    inclination itself when the primary's pole is unknown."""
    if pole is None:
        return i_deg
    i = math.radians(i_deg)
    om = math.radians(om_deg)
    n = (math.sin(i) * math.sin(om), -math.sin(i) * math.cos(om), math.cos(i))
    dot = sum(a * b for a, b in zip(n, pole))
    return math.degrees(math.acos(max(-1.0, min(1.0, dot))))


def _ring_span(metas: list[dict] | None, radius_km: float) -> dict | None:
    if not metas:
        return None
    inner = min(float(m["inner_radius_km"]) for m in metas)
    outer = max(float(m["outer_radius_km"]) for m in metas)
    if outer <= inner:
        return None
    return {"inner_rp": inner / radius_km, "outer_rp": outer / radius_km}


def build_planetary_systems_map(
    session: Session,
    radii: dict[int, dict],
    orientation: dict[int, dict],
    ring_metadata: dict[str, list[dict]],
    units: UnitConverter,
    entities: WikidataEntityCache,
) -> list[SystemMap]:
    """One map per barycenter with a moon, in heliocentric order."""
    hosts = (
        session.query(Object.parent_id, Object.id, Object.naif_id, Object.wikidata_qid)
        .filter(
            Object.object_type.in_((ObjectType.planet, ObjectType.dwarf_planet)),
            Object.parent_id.isnot(None),
        )
        .all()
    )
    out: list[SystemMap] = []
    for bary_id, host_id, host_naif, host_qid in sorted(hosts, key=lambda r: r[2]):
        triaxial, _ = render_size(host_naif, host_qid, radii, None, None)
        if triaxial is None:
            continue
        radius_km = max(triaxial["a"], triaxial["b"], triaxial["c"])
        pole = (
            _pole_ecliptic(orientation[host_naif]) if host_naif in orientation else None
        )
        # SPICE hangs a system's moons off the barycenter, but a few sit on the
        # planet itself; take both so no system draws short.
        moon_rows = (
            session.query(Object)
            .filter(
                Object.object_type == ObjectType.moon,
                Object.parent_id.in_((bary_id, host_id)),
            )
            .all()
        )
        if not moon_rows:
            continue
        moons: list[SystemMoon] = []
        for obj in moon_rows:
            el = _orbit_elements(obj, ("a", "i", "om"))
            a_au = el.get("a")
            if a_au is None or a_au <= 0:
                continue
            moon_radii, moon_radius = render_size(
                obj.naif_id, obj.wikidata_qid, radii, units, entities
            )
            if moon_radii is not None:
                moon_radius = max(moon_radii["a"], moon_radii["b"], moon_radii["c"])
            moons.append(
                SystemMoon(
                    id=obj.id,
                    a_rp=a_au * _AU_KM / radius_km,
                    tilt_deg=_tilt_to_equator(
                        el.get("i", 0.0), el.get("om", 0.0), pole
                    ),
                    radius_km=moon_radius or 0.0,
                    color=resolve_moon_color(obj.naif_id)[0],
                )
            )
        if not moons:
            continue
        moons.sort(key=lambda m: m.a_rp)
        out.append(
            SystemMap(
                barycenter_id=bary_id,
                primary_id=host_id,
                primary_radius_km=radius_km,
                moons=moons,
                rings=_ring_span(ring_metadata.get(host_id), radius_km),
                moon_count=len(moon_rows),
            )
        )
    logger.info(
        "Planetary system maps: %d systems, %d moons",
        len(out),
        sum(len(s.moons) for s in out),
    )
    return out


def write_planetary_systems_map(out_dir: Path, systems: list[SystemMap]) -> None:
    payload = {
        s.barycenter_id: {
            "primary": {"id": s.primary_id, "radius_km": s.primary_radius_km},
            "moons": [
                {
                    "id": m.id,
                    "a_rp": m.a_rp,
                    "tilt_deg": m.tilt_deg,
                    "radius_km": m.radius_km,
                    **({"color": m.color} if m.color else {}),
                }
                for m in s.moons
            ],
            "rings": s.rings,
            "moon_count": s.moon_count,
        }
        for s in systems
    }
    path = out_dir / "groups" / "__planetary_systems_map__.json.gz"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(gzip.compress(orjson.dumps(payload)))
    logger.info("Wrote planetary system maps: %d systems → %s", len(payload), path.name)
