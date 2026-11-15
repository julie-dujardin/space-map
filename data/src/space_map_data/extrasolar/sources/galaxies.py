"""The galaxy list as an ingest source.

A row holds one galaxy of the list (`constants/galaxies/literature.py`). It
mints: no catalogue here holds these galaxies. Its id is the key of its
entry, which never changes, so each ingest finds the galaxy that an earlier
one minted. A row never matches by position, and its kind agrees only with
itself, so no star at its point joins it. The point of a galaxy is at
J2016.0, as every position of the registry.

The Wikidata item of a galaxy is a row of the Wikidata pass (`with_items`).
It claims the galaxy by its key, as the item of a star claims its star.

`facts` gives the values of a galaxy that no table holds: those of the list,
and the estimates that follow from its cited values. The range of an estimate
takes each of its inputs at the end of its range. Each end is then rounded to
the nearest digit that the inputs support, so it is not a bound. A count is
that range alone: its inputs do not support one number.
"""

import math
from collections.abc import Mapping

import numpy as np
import pyarrow as pa
import pyarrow.compute as pc

from space_map_data.constants.galaxies.literature import GALAXIES, Galaxy, Value
from space_map_data.extrasolar import sky
from space_map_data.extrasolar.engine import MATCH_FIELDS, Source
from space_map_data.extrasolar.ids import cell_of
from space_map_data.extrasolar.match import GALAXY_KIND
from space_map_data.extrasolar.measured_radius import KM_PER_PC
from space_map_data.extrasolar.registry import Registry
from space_map_data.extrasolar.sources.hipparcos import to_gaia_epoch
from space_map_data.extrasolar.tables import (
    CROSS_ID,
    GALAXY_CATALOGUE,
    GALAXY_LITERATURE,
    METADATA,
    REDSHIFT,
    REDSHIFT_TABLE,
)


class GalaxyMoved(ValueError):
    """The registry holds the galaxy of the Sun outside the region of its
    point in the list."""


GALAXY_LIST = Source(
    name=GALAXY_LITERATURE,
    catalogue=GALAXY_CATALOGUE,
    release="key",
    home=REDSHIFT_TABLE,
    kind=GALAXY_KIND,
)
CLASS = "galaxy"
# The fields with bounds. Each fills the group and the columns of its name.
BOUNDED = ("stellar_mass", "total_mass", "star_formation_rate")
# The field of a `Galaxy` that fills each Redshift group.
GROUP_FIELDS = {
    "position": "position",
    "distance": "distance",
    "morphology": "morphological_type",
    **{name: name for name in BOUNDED},
}
SECONDS_PER_MYR = 365.25 * 86400 * 1e6
# The digits of an estimate: the ends of the range of a count, and a period,
# whose speed is good to three in a hundred.
COUNT_DIGITS = 1
PERIOD_DIGITS = 3
_MATCH = {column.name: column for column in MATCH_FIELDS}
SCHEMA = pa.schema(
    [
        *(_MATCH[name] for name in ("catalogue_id", "mint", "match_ra", "match_dec")),
        *(
            column
            for table in (METADATA, REDSHIFT)
            for group in table.groups_of(GALAXY_LITERATURE)
            for column in group.columns
        ),
    ]
)
ITEM_SCHEMA = pa.schema(
    [
        *(_MATCH[name] for name in ("catalogue_id", "match_ra", "match_dec", "claims")),
        METADATA.group("name").columns[0],
        _MATCH["mint"],
    ]
)


def position(galaxy: Galaxy) -> tuple[float, float]:
    """The point of the galaxy at J2016.0: ICRS, deg."""
    given = galaxy.position
    ra, dec = to_gaia_epoch(
        np.array([given.ra]),
        np.array([given.dec]),
        np.array([given.pmra]),
        np.array([given.pmdec]),
        given.epoch,
    )
    return float(ra[0]), float(dec[0])


def home_galaxy(
    registry: Registry, galaxies: Mapping[str, Galaxy] = GALAXIES
) -> int | None:
    """The ID of the galaxy of the Sun, None when the list or the registry
    has none. Raises `GalaxyMoved` when its ID is not in the region of its
    point: the list then gives another point than the ingest had."""
    for key, galaxy in galaxies.items():
        if not galaxy.holds_sun:
            continue
        ra, dec = position(galaxy)
        source = (GALAXY_LIST.catalogue, GALAXY_LIST.release)
        region = int(sky.region_of(sky.cells(np.array([ra]), np.array([dec])))[0])
        if found := int(registry.lookup(*source, [key], [region])[0]):
            return found
        # Only a region with a Redshift row can hold the ID.
        others = [r for r in registry.table_regions(REDSHIFT.slug) if r != region]
        if moved := int(registry.lookup(*source, [key], others)[0]):
            raise GalaxyMoved(
                f"the galaxy of the Sun, {key}, is ID {moved} of region"
                f" {sky.region_of(cell_of(moved))}, and its point in the galaxy"
                f" list is in region {region}"
            )
        return None
    return None


def cited(galaxy: Galaxy) -> dict[str, tuple[str, ...]]:
    """The works of each Redshift group that the galaxy has a value of, by
    group."""
    return {
        group: value.references
        for group, name in GROUP_FIELDS.items()
        if (value := getattr(galaxy, name)) is not None
    }


def _estimate(
    value: float | None,
    lower: float,
    upper: float,
    digits: int,
    *works: tuple[str, ...],
) -> Value:
    """The estimate over this range, with this value when it has one. Each
    number is rounded to the nearest of `digits` digits, so an end of the
    range is not a bound. It cites `works`, each work once."""

    def rounded(number: float) -> float:
        return float(f"{number:.{digits}g}")

    cited = tuple(dict.fromkeys(work for found in works for work in found))
    return Value(
        None if value is None else rounded(value),
        rounded(lower),
        rounded(upper),
        cited,
        estimate=True,
    )


def _range(value: Value) -> tuple[float, float, float]:
    """The value, then its bounds. A bound that the work does not give is the
    value."""
    if value.value is None:
        raise ValueError(f"an estimate needs a value, and {value} is a limit")
    return (
        value.value,
        value.value if value.lower is None else value.lower,
        value.value if value.upper is None else value.upper,
    )


def estimates(galaxy: Galaxy) -> dict[str, Value]:
    """The facts that follow from the cited values of the galaxy, where it
    has them: the range of its stars from its stellar mass and the mean mass
    of a star, the range of its planets from its stars and the planets of a
    star, and the period of a circular orbit at the Sun's radius from that
    radius and the circular speed of one fit."""
    out: dict[str, Value] = {}
    mass, mean = galaxy.stellar_mass, galaxy.mean_star_mass
    rate = galaxy.facts.get("planets_per_star")
    if mass is not None and mean is not None:
        (_, m_low, m_high), (_, s_low, s_high) = _range(mass), _range(mean)
        fewest, most = m_low / s_high, m_high / s_low
        works = (mass.references, mean.references)
        out["star_count"] = _estimate(None, fewest, most, COUNT_DIGITS, *works)
        if rate is not None:
            _, r_low, r_high = _range(rate)
            out["planet_count"] = _estimate(
                None,
                fewest * r_low,
                most * r_high,
                COUNT_DIGITS,
                *works,
                rate.references,
            )
    radius, speed = galaxy.sun_orbit_radius, galaxy.facts.get("circular_speed")
    if radius is not None and speed is not None:
        (r, r_low, r_high), (v, v_low, v_high) = _range(radius), _range(speed)
        turn = 2 * math.pi * KM_PER_PC / SECONDS_PER_MYR
        out["orbital_period"] = _estimate(
            turn * r / v,
            turn * r_low / v_high,
            turn * r_high / v_low,
            PERIOD_DIGITS,
            radius.references,
            speed.references,
        )
    return out


def facts(galaxy: Galaxy) -> dict[str, Value]:
    """The values of the galaxy that no table holds, by a name of FACTS: the
    facts of the list, then the estimates."""
    return {**galaxy.facts, **estimates(galaxy)}


def engine_rows(galaxies: Mapping[str, Galaxy] = GALAXIES) -> pa.Table:
    """A row for each galaxy of the list, with its Redshift values."""
    rows = []
    for key, galaxy in galaxies.items():
        ra, dec = position(galaxy)
        distance = galaxy.distance
        kind = galaxy.morphological_type
        row = {
            "catalogue_id": key,
            "mint": True,
            "match_ra": ra,
            "match_dec": dec,
            "name": galaxy.name,
            "class": CLASS,
            "ra": ra,
            "dec": dec,
            "distance": distance.value,
            "distance_lower": distance.lower,
            "distance_upper": distance.upper,
            "distance_method": distance.method,
            "morphological_type": None if kind is None else kind.value,
        }
        for name in BOUNDED:
            value = getattr(galaxy, name)
            if value is not None:
                row |= {
                    name: value.value,
                    f"{name}_lower": value.lower,
                    f"{name}_upper": value.upper,
                }
        rows.append(row)
    return pa.Table.from_pylist(rows, SCHEMA)


def with_items(rows: pa.Table, galaxies: Mapping[str, Galaxy] = GALAXIES) -> pa.Table:
    """The rows of the Wikidata pass and a row for the item of each galaxy.
    The list names the galaxy, so the row gives no name. The engine refuses an
    id that is in a pass twice, so a row of the star list with an item of the
    list goes."""
    items = []
    for key, galaxy in galaxies.items():
        if galaxy.qid is None:
            continue
        ra, dec = position(galaxy)
        claim = (GALAXY_LIST.catalogue, GALAXY_LIST.release, key)
        items.append(
            {
                "catalogue_id": galaxy.qid,
                "match_ra": ra,
                "match_dec": dec,
                "claims": [dict(zip(CROSS_ID.names, claim))],
                "mint": False,
            }
        )
    added = pa.Table.from_pylist(items, ITEM_SCHEMA)
    kept = rows.filter(
        pc.invert(pc.is_in(rows["catalogue_id"], value_set=added["catalogue_id"]))
    )
    return pa.concat_tables([kept, added], promote_options="default")
