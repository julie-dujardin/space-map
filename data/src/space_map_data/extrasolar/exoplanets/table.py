"""The planets table: one row per planet, keyed by (host, number).

The host is the star the planet orbits, and the pair's star for a planet
around both stars of a binary. `system` is the ID of the star that keys the
planetary system, one for all planets of the system, around either star.

Its column groups each come whole from one source, the first in the group's
source order with a value in the group. Mass and radius put a measured value
before an estimate, and the mass a true mass before a minimum mass: an
archive m sin i or mass–radius estimate loses to an exoplanet.eu true mass.
Names, class and flags are computed.

Units: days, AU, degrees, Jupiter masses and radii, kelvin, Earth
insolation, g/cm³, solar masses and radii, dex. Times are Julian dates as
published, mostly BJD; `time_system` names the system of the transit time
(BJD, BJD-TDB, HJD, JD) when the catalogue gives it. The systems differ by
minutes, so the orbit elements take every time as JD TDB. An error is
positive. A value `<name>` has `<name>_error_upper` and `<name>_error_lower`.

Flags, as lists of value names:
- assumed: a default, or an eccentricity of exactly 0 with no error;
- estimated: a catalogue's estimate (the archive's "Calculated Value", the
  mass–radius relation, exoplanet.eu's "Theoretical");
- computed: derived here (Kepler's third law, a projected separation);
- limits: `<name><` or `<name>>` when the value is an upper or lower limit.

Defaults for unknown values:
- period from the semi-major axis and the masses, and the reverse; a
  semi-major axis from the angular separation and the distance;
- eccentricity 0, argument of periastron 90°;
- inclination of a transiting planet of the same host, else 90°;
- node: one angle per system from a hash of its key ID (`default_node`), so
  the assumed orbits of a system share one plane;
- periastron at J2000.0 when no transit or periastron time is known.
"""

import csv
import hashlib
import math
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path

import pyarrow as pa

from space_map_data.extrasolar.exoplanets.catalogues import (
    ARCHIVE,
    EU,
    MINIMUM_MASS,
    OEC,
    TRUE_MASS,
    UPPER_LIMIT,
    Measure,
)
from space_map_data.extrasolar.exoplanets.iau import (
    JUPITER_IN_SUNS,
    MAX_MASS,
    classify,
)
from space_map_data.extrasolar.exoplanets.join import Joined
from space_map_data.extrasolar.exoplanets.sources import BY_NAME
from space_map_data.extrasolar.tables import CROSS_ID, ColumnGroup

SLUG = "planets"
GAIA = "gaia-dr3"
IAU_NAMES = "iau-nameexoworlds"

# Days in a year of Kepler's third law with masses in solar masses: 2π/k,
# with k the Gaussian gravitational constant.
KEPLER_YEAR = 2 * math.pi / 0.01720209895
J2000 = 2_451_545.0
DEFAULT_OMEGA = 90.0
EDGE_ON = 90.0
TRANSIT = "Transit"
# A Gaia orbit gives the node of a planet whose period it matches this well.
NSS_PERIOD_TOLERANCE = 0.05

ORBIT = (
    "period",
    "semi_major_axis",
    "eccentricity",
    "inclination",
    "omega",
    "periastron_time",
    "transit_time",
)
PHYSICAL = ("equilibrium_temperature", "insolation", "density")
STELLAR = ("star_mass", "star_radius", "star_teff", "star_metallicity")


def _measured(*names: str) -> tuple[pa.Field, ...]:
    fields = []
    for name in names:
        fields += [
            pa.field(name, pa.float64()),
            pa.field(f"{name}_error_upper", pa.float64()),
            pa.field(f"{name}_error_lower", pa.float64()),
        ]
    return tuple(fields)


GROUPS = (
    ColumnGroup("status", (pa.field("status", pa.string()),), (ARCHIVE, EU, OEC)),
    ColumnGroup(
        "discovery",
        (
            pa.field("discovery_method", pa.string()),
            pa.field("discovery_year", pa.int16()),
            pa.field("discovery_facility", pa.string()),
        ),
        (ARCHIVE, EU, OEC),
    ),
    ColumnGroup(
        "orbit",
        (*_measured(*ORBIT), pa.field("time_system", pa.string())),
        (ARCHIVE, EU, OEC),
    ),
    # The node on the sky, with the inclination of the same solution.
    ColumnGroup(
        "sky",
        (
            *_measured("node"),
            pa.field("node_inclination", pa.float64()),
            pa.field("node_solution", pa.string()),
        ),
        (GAIA, OEC),
    ),
    ColumnGroup(
        "mass",
        (*_measured("mass"), pa.field("mass_kind", pa.string())),
        (ARCHIVE, EU),
    ),
    ColumnGroup("radius", _measured("radius"), (ARCHIVE, EU)),
    ColumnGroup("physical", _measured(*PHYSICAL), (ARCHIVE,)),
    ColumnGroup("atmosphere", (pa.field("molecules", pa.list_(pa.string())),), (EU,)),
    # The star of the fits that gave the orbit and the mass.
    ColumnGroup("stellar", _measured(*STELLAR), (ARCHIVE, EU)),
    ColumnGroup("binary", (pa.field("binary_type", pa.string()),), (OEC, ARCHIVE)),
)
KEY_FIELDS = (
    pa.field("host", pa.int64(), nullable=False),
    pa.field("number", pa.uint16(), nullable=False),
    pa.field("system", pa.int64(), nullable=False),
)
NAME_FIELDS = (
    pa.field("name", pa.string()),
    pa.field("name_source", pa.string()),
    pa.field("designation", pa.string()),
    pa.field("letter", pa.string()),
    pa.field("aliases", pa.list_(pa.string())),
    pa.field("cross_ids", pa.list_(CROSS_ID)),
)
CLASS_FIELDS = (
    pa.field("class", pa.string()),
    pa.field("class_basis", pa.string()),
    pa.field("mass_ratio", pa.float64()),
)
FLAG_FIELDS = tuple(
    pa.field(name, pa.list_(pa.string()))
    for name in ("assumed", "estimated", "computed", "limits")
)


def schema() -> pa.Schema:
    fields = [*KEY_FIELDS, *NAME_FIELDS, *CLASS_FIELDS]
    for group in GROUPS:
        fields += [*group.columns, pa.field(group.source_column, pa.string())]
    return pa.schema(fields + list(FLAG_FIELDS))


SCHEMA = schema()


@dataclass(frozen=True)
class SkyOrbit:
    """A Gaia DR3 two-body orbit with its node and inclination."""

    source_id: int
    solution: str
    period: float
    node: float
    inclination: float


def campbell(
    a: float, b: float, f: float, g: float
) -> tuple[float, float, float, float]:
    """Semi-major axis, inclination, ω and Ω from Thiele–Innes A, B, F, G.

    Angles in degrees. An astrometric orbit cannot tell Ω from Ω + 180° and ω
    from ω + 180°, so Ω is taken in [0°, 180°).
    """
    u = (a * a + b * b + f * f + g * g) / 2
    v = a * g - b * f
    axis = math.sqrt(u + math.sqrt(max(u * u - v * v, 0.0)))
    plus = math.atan2(b - f, a + g)
    minus = math.atan2(-b - f, a - g)
    omega, node = (plus + minus) / 2, (plus - minus) / 2
    if node < 0:
        node, omega = node + math.pi, omega + math.pi
    elif node >= math.pi:
        node, omega = node - math.pi, omega - math.pi
    inclination = math.acos(max(-1.0, min(1.0, v / axis**2)))
    return (
        axis,
        math.degrees(inclination),
        math.degrees(omega) % 360,
        math.degrees(node),
    )


def read_sky_orbits(path: Path) -> dict[int, list[SkyOrbit]]:
    """The Gaia DR3 orbits with Thiele–Innes elements, by source."""
    found: dict[int, list[SkyOrbit]] = defaultdict(list)
    with path.open(newline="") as fh:
        for row in csv.DictReader(fh):
            elements = [row[f"{n}_thiele_innes"] for n in "abfg"]
            if not all(elements) or not row["period"]:
                continue
            _, inclination, _, node = campbell(*map(float, elements))
            found[int(row["source_id"])].append(
                SkyOrbit(
                    int(row["source_id"]),
                    row["nss_solution_type"],
                    float(row["period"]),
                    node,
                    inclination,
                )
            )
    return dict(found)


@dataclass
class Record:
    """The values of one planet before it has a host ID and a number."""

    joined: Joined
    # Identity of its star and the key identity of its system.
    star: int
    key: int
    system: int
    values: dict[str, object] = field(default_factory=dict)
    assumed: set[str] = field(default_factory=set)
    estimated: set[str] = field(default_factory=set)
    computed: set[str] = field(default_factory=set)
    limits: set[str] = field(default_factory=set)

    def get(self, name: str) -> float | None:
        value = self.values.get(name)
        return value if isinstance(value, float) else None

    def text(self, name: str) -> str | None:
        value = self.values.get(name)
        return value if isinstance(value, str) else None

    @property
    def year(self) -> int | None:
        value = self.values.get("discovery_year")
        return value if isinstance(value, int) else None


def _put(record: Record, name: str, measure: Measure) -> None:
    record.values[name] = measure.value
    record.values[f"{name}_error_upper"] = measure.upper
    record.values[f"{name}_error_lower"] = measure.lower
    if measure.estimated:
        record.estimated.add(name)
    if measure.limit is not None:
        record.limits.add(name + measure.limit)


def _first_with(joined: Joined, sources: tuple[str, ...], names: tuple[str, ...]):
    for source in sources:
        row = joined.rows.get(source)
        if row is not None and any(n in row.values for n in names):
            return row
    return None


# A true mass comes before a minimum mass, and both before an estimate.
MASS_RANK = {TRUE_MASS: 0, MINIMUM_MASS: 1}


def _measured_first(joined: Joined, sources: tuple[str, ...], name: str):
    """The row with `name`: measured before estimated, then by source order.

    For the mass, a true mass comes before a minimum mass.
    """
    found = []
    for at, source in enumerate(sources):
        row = joined.rows.get(source)
        if row is None or name not in row.values:
            continue
        estimated = row.values[name].estimated
        rank = 2 if estimated else MASS_RANK.get(row.mass_kind or "", 1)
        found.append((rank if name == "mass" else int(estimated), at, row))
    return min(found, key=lambda t: t[:2])[2] if found else None


def merge(
    joined: Joined,
    star: int,
    key: int,
    system: int,
    orbits: list[SkyOrbit],
    star_mass: float | None,
    star_names: tuple[str, ...] = (),
) -> Record:
    """The values of a joined planet, each group from its first source.

    `orbits` are the Gaia orbits of its star, `star_mass` the mass of its
    star from the star's catalogues, for a planet whose fit gives none, and
    `star_names` the names of its star, which are not aliases of the planet.
    """
    record = Record(joined, star, key, system)
    values = record.values
    first = joined.first
    values["status"], values["status_source"] = first.status, first.catalogue

    row = next(
        (
            joined.rows[s]
            for s in (ARCHIVE, EU, OEC)
            if s in joined.rows and (joined.rows[s].method or joined.rows[s].year)
        ),
        None,
    )
    if row is not None:
        values["discovery_method"] = row.method
        values["discovery_year"] = row.year
        values["discovery_facility"] = row.facility
        values["discovery_source"] = row.catalogue

    row = _first_with(joined, (ARCHIVE, EU, OEC), ORBIT)
    if row is not None:
        for name in ORBIT:
            if name in row.values:
                _put(record, name, row.values[name])
        values["time_system"] = row.time_system
        values["orbit_source"] = row.catalogue

    period = record.get("period")
    gaia = [
        o
        for o in orbits
        if period is not None
        and abs(o.period - period) / max(o.period, period) < NSS_PERIOD_TOLERANCE
    ]
    oec = joined.rows.get(OEC)
    if gaia:
        orbit = gaia[0]
        values["node"] = orbit.node
        values["node_inclination"] = orbit.inclination
        values["node_solution"] = orbit.solution
        values["sky_source"] = GAIA
    elif oec is not None and "node" in oec.values:
        _put(record, "node", oec.values["node"])
        if "inclination" in oec.values:
            values["node_inclination"] = oec.values["inclination"].value
        values["sky_source"] = OEC

    row = _measured_first(joined, (ARCHIVE, EU), "mass")
    if row is not None:
        _put(record, "mass", row.values["mass"])
        values["mass_kind"] = row.mass_kind
        values["mass_source"] = row.catalogue
    row = _measured_first(joined, (ARCHIVE, EU), "radius")
    if row is not None:
        _put(record, "radius", row.values["radius"])
        values["radius_source"] = row.catalogue

    row = joined.rows.get(ARCHIVE)
    if row is not None and any(n in row.values for n in PHYSICAL):
        for name in PHYSICAL:
            if name in row.values:
                _put(record, name, row.values[name])
        values["physical_source"] = ARCHIVE

    row = joined.rows.get(EU)
    if row is not None and row.molecules:
        values["molecules"] = list(row.molecules)
        values["atmosphere_source"] = EU

    row = _first_with(joined, (ARCHIVE, EU), STELLAR)
    if row is not None:
        for name in STELLAR:
            if name in row.values:
                _put(record, name, row.values[name])
        values["stellar_source"] = row.catalogue

    for source in (OEC, ARCHIVE):
        row = joined.rows.get(source)
        if row is not None and row.binary:
            values["binary_type"] = row.binary
            values["binary_source"] = source
            break

    central = record.get("star_mass") or star_mass
    values["class"], values["class_basis"], values["mass_ratio"] = classify(
        record.get("mass"), record.text("mass_kind"), central
    )
    _names(record, star_names)
    return record


def _folded(name: str) -> str:
    # Unlike `catalogues.reduced`, this keeps non-ASCII letters: "α Cen" and
    # "β Cen" stay apart, and a name in another script does not become "".
    return "".join(c for c in name.casefold() if c.isalnum())


def _names(record: Record, star_names: tuple[str, ...]) -> None:
    joined = record.joined
    first = joined.first
    values = record.values
    values["designation"] = first.name
    values["name"] = first.name
    values["name_source"] = first.catalogue
    values["letter"] = next(
        (row.letter for row in joined.rows.values() if row.letter), None
    )
    stars = {_folded(name) for name in star_names}
    aliases: list[str] = []
    for source in (ARCHIVE, EU, OEC):
        row = joined.rows.get(source)
        if row is not None:
            aliases += [
                n for n in row.names if n not in aliases and _folded(n) not in stars
            ]
    values["aliases"] = aliases
    values["cross_ids"] = [
        {
            "catalogue": source,
            "release": BY_NAME[source].release,
            "catalogue_id": row.key,
        }
        for source in (ARCHIVE, EU, OEC)
        if (row := joined.rows.get(source)) is not None
    ]


def name_planet(record: Record, name: str) -> None:
    """Make an IAU name the planet's name."""
    values = record.values
    values["name"], values["name_source"] = name, IAU_NAMES
    aliases = values["aliases"]
    assert isinstance(aliases, list)
    values["aliases"] = [name, *[a for a in aliases if a != name]]
    cross_ids = values["cross_ids"]
    assert isinstance(cross_ids, list)
    cross_ids.append(
        {"catalogue": "iau", "release": "nameexoworlds", "catalogue_id": name}
    )


def too_massive(record: Record) -> bool:
    """Above the 60 MJ that the scheme keeps. An upper limit does not count."""
    mass = record.get("mass")
    return (
        mass is not None
        and mass > MAX_MASS
        and f"mass{UPPER_LIMIT}" not in record.limits
    )


def kepler(record: Record, star_mass: float | None, distance: float | None) -> None:
    """Fill a missing period or semi-major axis, flagged as computed."""
    central = record.get("star_mass") or star_mass
    planet = record.get("mass")
    if central is not None:
        central += (planet or 0.0) * JUPITER_IN_SUNS
    period, axis = record.get("period"), record.get("semi_major_axis")
    if axis is None and period is None:
        separation = _angular_separation(record)
        if separation is not None and distance is not None:
            axis = separation / 1000 * distance
            record.values["semi_major_axis"] = axis
            record.computed.add("semi_major_axis")
    if central is None or central <= 0:
        return
    if period is None and axis is not None:
        record.values["period"] = KEPLER_YEAR * math.sqrt(axis**3 / central)
        record.computed.add("period")
    elif axis is None and period is not None:
        record.values["semi_major_axis"] = (central * (period / KEPLER_YEAR) ** 2) ** (
            1 / 3
        )
        record.computed.add("semi_major_axis")


def _angular_separation(record: Record) -> float | None:
    for row in record.joined.rows.values():
        found = row.values.get("angular_separation")
        if found is not None:
            return found.value
    return None


def is_transiting(record: Record) -> bool:
    return record.get("transit_time") is not None or any(
        row.method == TRANSIT for row in record.joined.rows.values()
    )


def fill_defaults(records: list[Record]) -> None:
    """Fill eccentricity, ω, inclination and phase, flagged as assumed.

    The node needs the host ID, so `default_node` fills it at commit.
    """
    sibling_inclination: dict[int, float] = {}
    for record in records:
        inclination = record.get("inclination")
        if inclination is not None and is_transiting(record):
            sibling_inclination.setdefault(record.star, inclination)
    for record in records:
        values = record.values
        e = record.get("eccentricity")
        if e is None:
            values["eccentricity"] = 0.0
            record.assumed.add("eccentricity")
        elif e == 0 and values.get("eccentricity_error_upper") is None:
            record.assumed.add("eccentricity")
        if record.get("omega") is None:
            values["omega"] = DEFAULT_OMEGA
            record.assumed.add("omega")
        if record.get("inclination") is None:
            values["inclination"] = sibling_inclination.get(record.star, EDGE_ON)
            record.assumed.add("inclination")
        if record.get("periastron_time") is None and record.get("transit_time") is None:
            values["periastron_time"] = J2000
            record.assumed.add("periastron_time")


def default_node(system: int) -> float:
    """One node angle per system, in degrees, from a hash of its decimal ID."""
    digest = hashlib.blake2b(str(system).encode(), digest_size=8).digest()
    return int.from_bytes(digest, "big") % 360_000 / 1000


def to_row(record: Record, host: int, number: int, system: int) -> dict:
    values = dict(record.values)
    assumed = set(record.assumed)
    if values.get("node") is None:
        values["node"] = default_node(system)
        assumed.add("node")
    row = {name: values.get(name) for name in SCHEMA.names}
    row.update(host=host, number=number, system=system)
    row["assumed"] = sorted(assumed)
    row["estimated"] = sorted(record.estimated)
    row["computed"] = sorted(record.computed)
    row["limits"] = sorted(record.limits)
    return row
