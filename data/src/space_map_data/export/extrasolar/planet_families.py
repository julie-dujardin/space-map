"""The planet families of the planet records, from their values.

`families` lists the published families of a planet, `families_estimated`
the families that need an estimate and are not published. Both list slugs in
the order of `constants.planets.families.FAMILIES`, with the parents of each
family. The thresholds are in that constants module.

Evidence:
- A value is measured when it is not in `estimated` or `assumed`. A computed
  period or semi-major axis is measured. An assumed value is never used.
- An estimated mass or radius is used only when neither the mass nor the
  radius is measured (`mass_and_radius`). A family that it decides is
  estimated.
- A limit `x<` puts the value in [0, x], and `x>` in [x, ∞). A limit settles
  a rule only when the whole interval is inside or outside the range.
- A minimum mass is a lower bound. It settles "at least" as published. For
  "at most", the minimum mass stands in for the mass, as an estimate. An
  upper limit on a minimum mass gives no bound.
- A size rule needs a mass or a radius that settles it. Each one that settles
  it must be in range.
- A density rule uses a measured density, else one from a measured mass and
  radius.
- A rule of several parts is published when every part is published, and
  estimated when one part is estimated and none fails.
- Only the IAU class `planet` gets families.
- `heavy_element_fraction` is the mass fraction of everything but hydrogen
  and helium. Only the records of the Solar System planets have it.
"""

import math
from collections.abc import Iterable
from dataclasses import dataclass
from enum import IntEnum

from space_map_data.constants.planets import families as rules
from space_map_data.extrasolar.exoplanets.catalogues import (
    LOWER_LIMIT,
    MINIMUM_MASS,
    P_TYPE,
    UPPER_LIMIT,
)
from space_map_data.extrasolar.exoplanets.iau import PLANET
from space_map_data.extrasolar.exoplanets.simbad import PULSAR

type Range = tuple[float, float]


class Verdict(IntEnum):
    """What the values say of a rule. The worst verdict of the parts of a
    rule is the verdict of the rule."""

    PUBLISHED = 0
    ESTIMATED = 1
    UNKNOWN = 2
    NO = 3


@dataclass(frozen=True)
class Known:
    """What a record says of a value: it is in [lo, hi]. `point` stands in
    for the value when the interval does not settle a rule."""

    lo: float
    hi: float
    measured: bool
    point: float | None


def judge(value: Known | None, bounds: Range) -> Verdict:
    """Whether `value` is in lo <= x < hi."""
    lo, hi = bounds
    if value is None:
        return Verdict.UNKNOWN
    if value.measured:
        if lo <= value.lo and (value.hi < hi or value.hi == hi == math.inf):
            return Verdict.PUBLISHED
        if value.hi < lo or value.lo >= hi:
            return Verdict.NO
    if value.point is None:
        return Verdict.UNKNOWN
    return Verdict.ESTIMATED if lo <= value.point < hi else Verdict.NO


def known(record: dict, name: str, scale: float = 1.0) -> Known | None:
    """The value `name` of a planet record, times `scale`."""
    value = record["values"].get(name)
    if value is None or name in record["assumed"]:
        return None
    x = value * scale
    if name in record["estimated"]:
        return Known(x, x, False, x)
    if f"{name}{UPPER_LIMIT}" in record["limits"]:
        return Known(0.0, x, True, None)
    if f"{name}{LOWER_LIMIT}" in record["limits"]:
        return Known(x, math.inf, True, None)
    return Known(x, x, True, x)


def _mass(record: dict) -> Known | None:
    """M⊕. A minimum mass is the lower bound of the mass."""
    found = known(record, "mass", rules.EARTH_MASSES_PER_JUPITER)
    if (
        found is None
        or not found.measured
        or record["values"].get("mass_kind") != MINIMUM_MASS
    ):
        return found
    if f"mass{UPPER_LIMIT}" in record["limits"]:
        return Known(0.0, math.inf, True, None)
    return Known(found.lo, math.inf, True, found.lo)


def mass_and_radius(record: dict) -> tuple[Known | None, Known | None]:
    """The mass (M⊕) and the radius (R⊕) that the rules read. When one of
    them is measured, an estimate of the other is dropped."""
    m = _mass(record)
    r = known(record, "radius", rules.EARTH_RADII_PER_JUPITER)
    if (m and m.measured) or (r and r.measured):
        m = m if m and m.measured else None
        r = r if r and r.measured else None
    return m, r


def density(record: dict, m: Known | None, r: Known | None) -> Known | None:
    """g/cm³: the catalogue's measured density, else one from the measured
    mass and radius."""
    found = known(record, "density")
    if found is not None and found.measured:
        return found
    if m is None or r is None or not m.measured or not r.measured or r.lo != r.hi:
        return None
    volume = 4 / 3 * math.pi * (r.lo / rules.EARTH_RADII_PER_JUPITER) ** 3
    k = (
        rules.JUPITER_MASS_G
        / rules.EARTH_MASSES_PER_JUPITER
        / (volume * rules.JUPITER_RADIUS_CM**3)
    )
    return Known(m.lo * k, m.hi * k, True, None if m.point is None else m.point * k)


def size(m: Known | None, r: Known | None, masses: Range, radii: Range) -> Verdict:
    """The mass or the radius must settle the rule, and each one that
    settles it must be in range."""
    settled = [
        verdict
        for verdict in (judge(m, masses), judge(r, radii))
        if verdict is not Verdict.UNKNOWN
    ]
    return max(settled, default=Verdict.UNKNOWN)


def terrestrial(m: Known | None, r: Known | None) -> Verdict:
    """By radius, else by mass."""
    verdict = judge(r, rules.TERRESTRIAL_RADIUS)
    if verdict is Verdict.UNKNOWN:
        return judge(m, rules.TERRESTRIAL_MASS)
    return verdict


def _host_value(record: dict, host: dict, name: str) -> float | None:
    """`star_<name>` of the planet's catalogue, else `name` of the host
    record. An upper limit is no value."""
    value = None
    if f"star_{name}{UPPER_LIMIT}" not in record["limits"]:
        value = record["values"].get(f"star_{name}")
    return value or host[name]


def habitable(record: dict, host: dict) -> Verdict:
    """The insolation against the conservative habitable zone of the star's
    Teff. Without a catalogue insolation, one from the star's radius and Teff
    and the semi-major axis, as an estimate."""
    teff = _host_value(record, host, "teff")
    lo, hi = rules.HABITABLE_TEFF
    if not teff or not lo <= teff < hi:
        return Verdict.UNKNOWN
    t = teff - rules.HABITABLE_TEFF_ZERO
    inner, outer = (
        sum(c * t**n for n, c in enumerate(edge))
        for edge in (rules.HABITABLE_INNER, rules.HABITABLE_OUTER)
    )
    insolation = known(record, "insolation")
    if insolation is None:
        a = record["values"].get("semi_major_axis")
        star_radius = _host_value(record, host, "radius")
        if not (a and star_radius):
            return Verdict.UNKNOWN
        flux = star_radius**2 * (teff / rules.SUN_TEFF) ** 4 / a**2
        insolation = Known(flux, flux, False, flux)
    return judge(insolation, (outer, math.nextafter(inner, math.inf)))


def verdicts(record: dict, host: dict) -> dict[str, Verdict]:
    """The verdict of each family's own rule, without its parents."""
    m, r = mass_and_radius(record)
    rho = density(record, m, r)
    period = known(record, "period")
    axis = known(record, "semi_major_axis")
    giant = size(m, r, rules.GIANT_MASS, rules.GIANT_RADIUS)
    gas = size(m, r, rules.GAS_GIANT_MASS, rules.GAS_GIANT_RADIUS)
    return {
        "terrestrial-planet": terrestrial(m, r),
        "sub-earth": size(m, r, rules.SUB_EARTH_MASS, rules.SUB_EARTH_RADIUS),
        "mega-earth": max(
            judge(m, rules.MEGA_EARTH_MASS),
            judge(r, rules.MEGA_EARTH_RADIUS),
            judge(rho, rules.MEGA_EARTH_DENSITY),
        ),
        "super-earth": size(m, r, rules.SUPER_EARTH_MASS, rules.SUPER_EARTH_RADIUS),
        "mini-neptune": judge(r, rules.MINI_NEPTUNE_RADIUS),
        "super-puff": max(
            judge(m, rules.SUPER_PUFF_MASS), judge(r, rules.SUPER_PUFF_RADIUS)
        ),
        "giant-planet": giant,
        "ice-giant": max(
            giant,
            judge(
                known(record, "heavy_element_fraction"), rules.ICE_GIANT_HEAVY_ELEMENTS
            ),
        ),
        "super-neptune": size(
            m, r, rules.SUPER_NEPTUNE_MASS, rules.SUPER_NEPTUNE_RADIUS
        ),
        "hot-neptune": max(
            size(m, r, rules.HOT_NEPTUNE_MASS, rules.HOT_NEPTUNE_RADIUS),
            judge(period, rules.HOT_PERIOD),
        ),
        "gas-giant": gas,
        "super-jupiter": max(gas, judge(m, rules.SUPER_JUPITER_MASS)),
        "hot-jupiter": max(gas, judge(period, rules.HOT_PERIOD)),
        "warm-jupiter": max(gas, judge(period, rules.WARM_PERIOD)),
        "cold-jupiter": max(gas, judge(axis, rules.COLD_SEMI_MAJOR_AXIS)),
        "jupiter-analogue": max(
            gas,
            judge(m, rules.JUPITER_ANALOGUE_MASS),
            judge(axis, rules.JUPITER_ANALOGUE_SEMI_MAJOR_AXIS),
        ),
        "eccentric-jupiter": max(
            gas, judge(known(record, "eccentricity"), rules.ECCENTRIC)
        ),
        "puffy-planet": max(gas, judge(rho, rules.PUFFY_DENSITY)),
        "ultra-short-period-planet": judge(period, rules.ULTRA_SHORT_PERIOD),
        "circumbinary-planet": Verdict.PUBLISHED
        if record["values"].get("binary_type") == P_TYPE
        else Verdict.NO,
        "pulsar-planet": Verdict.PUBLISHED if host["class"] == PULSAR else Verdict.NO,
        "goldilocks-planet": habitable(record, host),
    }


def _closed(families: Iterable[str]) -> set[str]:
    """`families` with all of their parents."""
    out: set[str] = set()
    todo = list(families)
    while todo:
        family = todo.pop()
        if family not in out:
            out.add(family)
            todo.extend(rules.PARENTS.get(family, ()))
    return out


def families_of(record: dict, host: dict) -> tuple[list[str], list[str]]:
    """The published and the estimated families of a planet record around
    `host`, its host record."""
    if record["class"] != PLANET:
        return [], []
    found = verdicts(record, host)
    published = _closed(f for f, v in found.items() if v is Verdict.PUBLISHED)
    estimated = _closed(f for f, v in found.items() if v is Verdict.ESTIMATED)
    estimated -= published
    return (
        [f for f in rules.FAMILIES if f in published],
        [f for f in rules.FAMILIES if f in estimated],
    )


def listed(published: dict[str, int], estimated: dict[str, int]) -> list[dict]:
    """The families of `metadata.json`, in order, with their planet counts."""
    return [
        {
            "slug": family,
            "wikidata": list(rules.PLANET_FAMILY_PAGES[family]),
            "parents": list(rules.PARENTS.get(family, ())),
            "published": published.get(family, 0),
            "estimated": estimated.get(family, 0),
        }
        for family in rules.FAMILIES
    ]
