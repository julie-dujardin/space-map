"""The orbit sources in their normal form, for the star systems.

ORBITS has one row per orbit of one pair, as a source gives it. A pair can
have several rows in one source, and the sources overlap: the MSC repeats
ORB6 orbits ("VB6" in its note), SB9 orbits and Gaia DR3 ones. COMPONENTS
has one row per star of a pair, with the values that a source gives for it:
the stars of the papers and of OEC, and the two masses of each MSC pair.

The values keep the source's numbers in fixed units: P in d, times as full
JD in the source's time scale, a in arcsec (`semi_major_axis`) or AU
(`semi_major_axis_au`), angles in deg, velocities in km/s, masses in solar
masses, radii in nominal solar radii, Teff in K. An error is positive, and
`<name>_error_upper` equals `<name>_error_lower` for a symmetric one. `row`
is the row of the source's own table, which holds the columns that are no
orbit elements.

How a row reaches our objects:
- msc: its WDS id, and the MSC id `<WDS id> <secondary>` of the member whose
  orbit it is, as in the MSC tree source. Its masses reach the pair so too.
- orb6: its WDS id with `designation` (the discoverer code) and `pair`, as
  in the WDS, and its HIP and HD numbers.
- sbx: the HIP, HD, HR, Gaia DR3 and WDS ids of its alias table, and its
  SBX system number.
- oec: no ids. `names` holds the names of the binary, and its stars in
  COMPONENTS have their OEC star ids.
- literature: the key of the point that holds the pair.
"""

import gzip
import logging
import math
import re
import xml.etree.ElementTree as ET
from collections import Counter, defaultdict
from collections.abc import Iterable
from pathlib import Path

import pyarrow as pa

from space_map_data.constants.stars import binaries
from space_map_data.download.providers.stars import msc, orb6, sbx
from space_map_data.extrasolar.exoplanets.catalogues import (
    OEC,
    OEC_SYSTEMS,
    julian_date,
    number,
    sexagesimal,
)
from space_map_data.extrasolar.systems.msc import PERIOD_UNITS as MSC_PERIOD_DAYS
from space_map_data.extrasolar.systems.msc import refuted
from space_map_data.extrasolar.systems.nodes import (
    ASTROMETRIC_ORBIT,
    GAIA_DR3,
    HD,
    HIP,
    HR,
    MSC_ID,
    SPECTROSCOPIC_ORBIT,
    VISUAL_ORBIT,
    WDS_ID,
)
from space_map_data.extrasolar.tables import CROSS_ID

logger = logging.getLogger(__name__)

MSC, ORB6, SBX, LITERATURE = "msc", "orb6", "sbx", "literature"
# Papers first. Among the catalogues, the MSC first, as in the trees.
ORBIT_SOURCES = (LITERATURE, MSC, ORB6, SBX, OEC)
SBX_ID = ("sbx", "sn")
OEC_STAR = (OEC, "systems")

# `epoch_event` values beside those of the paper table.
TRANSIT = "transit"
# SBX marks a T0 of another event, such as an eclipse.
OTHER_EVENT = "other event"

JULIAN_YEAR = 365.25
J2000 = 2451545.0
TROPICAL_YEAR = 365.242198781
B1900 = 2415020.31352
SOLAR_RADIUS_AU = 695_700.0 / 149_597_870.7
# MSC: a T of this size or more is JD − 2,400,000, else a Julian year.
MSC_DAY_NUMBER = 10_000.0
# The MSC's mass code of the minimum mass of an SB1 secondary. It is a lower
# bound, so it gives no mass ratio.
MSC_MINIMUM_MASS = "m"

_MEASURED = (
    "period",
    "epoch",
    "eccentricity",
    "semi_major_axis",
    "semi_major_axis_au",
    "inclination",
    "node",
    "arg_periastron",
    "mean_longitude",
    "k1",
    "k2",
    "systemic_velocity",
)


def _measured(names: Iterable[str]) -> list[pa.Field]:
    return [
        pa.field(f"{name}{suffix}", pa.float64())
        for name in names
        for suffix in ("", "_error_upper", "_error_lower")
    ]


_KEYS = [
    pa.field("source", pa.string()),
    # The source's key of the system.
    pa.field("system", pa.string()),
    # The source's name of the pair: a WDS discoverer code, an OEC name.
    pa.field("designation", pa.string()),
    # The components as the source writes them, and the two sides when the
    # pair splits into them.
    pa.field("pair", pa.string()),
    pa.field("primary", pa.string()),
    pa.field("secondary", pa.string()),
    pa.field("row", pa.int32()),
    pa.field("ids", pa.list_(CROSS_ID)),
    pa.field("names", pa.list_(pa.string())),
]
ORBITS = pa.schema(
    [
        *_KEYS,
        # Degrees, the source's position of the system.
        pa.field("ra", pa.float64()),
        pa.field("dec", pa.float64()),
        pa.field("known", pa.list_(pa.string())),
        *_measured(_MEASURED),
        # What `epoch` marks, a value of `binaries` or TRANSIT or OTHER_EVENT.
        pa.field("epoch_event", pa.string()),
        pa.field("time_scale", pa.string()),
        # The JD at which osculating elements hold. `mean_longitude` is then.
        pa.field("osculating_epoch", pa.float64()),
        pa.field("frame", pa.string()),
        # Whose ω the source gives: binaries.PRIMARY or SECONDARY, or null.
        pa.field("arg_periastron_of", pa.string()),
        # True when the source names Ω as the ascending node.
        pa.field("node_ascending", pa.bool_()),
        # The MSC's Nodeflag: the component to which the node refers.
        pa.field("node_component", pa.string()),
        # Of the node, as a year.
        pa.field("equinox", pa.float32()),
        # The values computed here from others the source gives.
        pa.field("derived", pa.list_(pa.string())),
        pa.field("grade", pa.string()),
        pa.field("reference", pa.string()),
    ]
)
COMPONENTS = pa.schema(
    [
        *_KEYS,
        # The component letter or, for OEC, the star's first name.
        pa.field("label", pa.string()),
        *_measured(("mass", "radius", "teff", "metallicity")),
        # How the source found the mass: the MSC's mass code.
        pa.field("mass_method", pa.string()),
        pa.field("spectral_type", pa.string()),
        pa.field("reference", pa.string()),
    ]
)


class _Rows:
    """Collects the rows of one source."""

    def __init__(self, schema: pa.Schema, source: str) -> None:
        self.schema = schema
        self.source = source
        self.columns: dict[str, list] = {name: [] for name in schema.names}

    def add(self, ids: Iterable[tuple[str, str, str]] = (), /, **values) -> None:
        unknown = set(values) - set(self.schema.names)
        if unknown:
            raise ValueError(f"unknown columns {sorted(unknown)}")
        values["source"] = self.source
        values["ids"] = [dict(zip(CROSS_ID.names, i)) for i in ids] or None
        for name, column in self.columns.items():
            column.append(values.get(name))

    def table(self) -> pa.Table:
        return pa.table(self.columns, schema=self.schema)


def _value(
    name: str,
    value: float | None,
    upper: float | None = None,
    lower: float | None = None,
    scale: float = 1.0,
) -> dict[str, float | None]:
    """A value and its errors, times `scale`. A symmetric error has no `lower`."""

    def scaled(x: float | None) -> float | None:
        return None if x is None else x * scale

    if value is None:
        return {}
    return {
        name: scaled(value),
        f"{name}_error_upper": scaled(upper),
        f"{name}_error_lower": scaled(upper if lower is None else lower),
    }


def _sides(pair: str | None) -> tuple[str | None, str | None]:
    """The two sides of "A,B", "Aa.Ab" or "AB"; None when it does not split."""
    if not pair:
        return None, None
    parts = re.split(r"[,.]", pair)
    if len(parts) == 2 and all(parts):
        return parts[0], parts[1]
    if len(pair) == 2 and pair.isalpha() and pair.isupper():
        return pair[0], pair[1]
    return None, None


def julian_year_jd(year: float) -> float:
    return J2000 + (year - 2000.0) * JULIAN_YEAR


def besselian_year_jd(year: float) -> float:
    return B1900 + (year - 1900.0) * TROPICAL_YEAR


def _known(value: float | None) -> float | None:
    """None for the zero that the MSC writes for "unknown"."""
    return value if value else None


def msc_orbits(directory: Path = msc.OUT_DIR) -> pa.Table:
    """Every orbit of the MSC's orb.tsv.

    A zero is unknown (Readme note 4), except an eccentricity. T has no unit
    code: a value of MSC_DAY_NUMBER or more is JD − 2,400,000, a smaller one
    a Julian year. The MSC copies each orbit with the angles of its own
    source, so `arg_periastron_of` is null.
    """
    out = _Rows(ORBITS, MSC)
    counts: Counter = Counter()
    for at, row in enumerate(msc.read_table(msc.ORB_FILE, directory).to_pylist()):
        wds_id = row["WDS"]
        primary, secondary = _sides(row["System"])
        ids = [(*WDS_ID, wds_id)]
        if secondary:
            ids.append((*MSC_ID, f"{wds_id} {secondary}"))
        period = _known(row["Period"])
        days = MSC_PERIOD_DAYS.get(row["Punit"] or "")
        if period and days is None:
            counts["period with no known unit"] += 1
            logger.debug(
                "MSC %s %s: period unit %r", wds_id, row["System"], row["Punit"]
            )
        epoch = _known(row["T"])
        if epoch is not None:
            epoch = (
                epoch + 2_400_000.0
                if epoch >= MSC_DAY_NUMBER
                else julian_year_jd(epoch)
            )
        a, k1 = _known(row["a"]), _known(row["K1"])
        known = []
        if a or _known(row["Incl"]):
            known.append(VISUAL_ORBIT)
        if k1:
            known.append(SPECTROSCOPIC_ORBIT)
        out.add(
            ids,
            system=wds_id,
            pair=row["System"],
            primary=primary,
            secondary=secondary,
            row=at,
            known=known or None,
            **_value("period", period if days else None, scale=days or 1.0),
            **_value("epoch", epoch),
            **_value("eccentricity", row["e"]),
            **_value("semi_major_axis", a),
            **_value("inclination", _known(row["Incl"])),
            **_value("node", _known(row["Node"])),
            **_value("arg_periastron", _known(row["LongP"])),
            **_value("k1", k1),
            **_value("k2", _known(row["K2"])),
            **_value("systemic_velocity", _known(row["V0"])),
            epoch_event=binaries.PERIASTRON if epoch is not None else None,
            time_scale="JD" if epoch is not None else None,
            node_component=row["Nodeflag"],
            reference=row["Note"],
        )
    table = out.table()
    logger.info("MSC: %d orbits; %s", table.num_rows, dict(counts))
    return table


def msc_masses(pairs: list[dict]) -> pa.Table:
    """The two masses of each pair of the MSC's sys.tsv, as COMPONENTS, the
    primary first.

    A pair has rows only when both masses are known: a zero is unknown
    (Readme note 4). A refuted or optical pair has none, and a pair with a
    minimum mass (code m) has none. `mass_method` is the MSC's code: r
    published, v, k or a estimated from the absolute V or K magnitude or the
    spectral type, s the sum of a subsystem, q from the primary's mass and the
    mass ratio.
    """
    out = _Rows(COMPONENTS, MSC)
    for at, row in enumerate(pairs):
        wds_id, primary, secondary = row["WDS"], row["Primary"], row["Secondary"]
        masses = _known(row["Mass1"]), _known(row["Mass2"])
        codes = [(row[name] or "").strip() or None for name in ("MCode1", "MCode2")]
        if not (primary and secondary and all(masses)) or refuted(row):
            continue
        if MSC_MINIMUM_MASS in codes:
            continue
        ids = [(*WDS_ID, wds_id), (*MSC_ID, f"{wds_id} {secondary}")]
        for label, mass, code in (
            (primary, masses[0], codes[0]),
            (secondary, masses[1], codes[1]),
        ):
            out.add(
                ids,
                system=wds_id,
                pair=f"{primary},{secondary}",
                primary=primary,
                secondary=secondary,
                row=at,
                label=label,
                **_value("mass", mass),
                mass_method=code,
            )
    return out.table()


def _orb6_epoch(value: float | None, unit: str | None) -> tuple[float | None, float]:
    """A JD from a T of ORB6, and the days per unit of its error."""
    if value is None:
        return None, 1.0
    match unit:
        case "d":
            return value + 2_400_000.0, 1.0
        case "m":
            return value + 2_400_000.5, 1.0
        case "y":
            return besselian_year_jd(value), TROPICAL_YEAR
        case "j":
            return julian_year_jd(value), JULIAN_YEAR
        case "c":
            return besselian_year_jd(100 * value), 100 * TROPICAL_YEAR
    return None, 1.0


def orb6_orbits(path: Path = orb6.OUT_DIR / orb6.ORBITS_FILE) -> pa.Table:
    """Every orbit of ORB6.

    ORB6 does not say whose ω it gives. A visual orbit is that of the
    secondary about the primary, so `arg_periastron_of` is SECONDARY. An
    astrometric orbit (grade 9) is that of the photocentre, and has none.
    """
    out = _Rows(ORBITS, ORB6)
    counts: Counter = Counter()
    for at, row in enumerate(orb6.read_orbits(path).to_pylist()):
        ids = [(*WDS_ID, row["wds_id"])]
        if row["hip"]:
            ids.append((*HIP, str(row["hip"])))
        if row["hd"]:
            ids.append((*HD, str(row["hd"])))
        days = orb6.PERIOD_DAYS.get(row["period_unit"] or "")
        arcsec = orb6.AXIS_ARCSEC.get(row["semi_major_axis_unit"] or "")
        epoch, epoch_days = _orb6_epoch(row["t_periastron"], row["t_periastron_unit"])
        error = row["t_periastron_error"]
        epoch_error = None if error is None else error * epoch_days
        for name, value, scale in (
            ("period", row["period"], days),
            ("semi-major axis", row["semi_major_axis"], arcsec),
            ("epoch", row["t_periastron"], epoch),
        ):
            if value is not None and scale is None:
                counts[f"{name} with no known unit"] += 1
                logger.debug(
                    "ORB6 %s %s: %s with no unit",
                    row["wds_id"],
                    row["components"],
                    name,
                )
        astrometric = row["grade"] == orb6.ASTROMETRIC_GRADE
        primary, secondary = _sides(row["components"])
        out.add(
            ids,
            system=row["wds_id"],
            designation=row["discoverer"],
            pair=row["components"],
            primary=primary,
            secondary=secondary,
            row=at,
            ra=row["ra"],
            dec=row["dec"],
            known=[ASTROMETRIC_ORBIT if astrometric else VISUAL_ORBIT],
            **_value(
                "period",
                row["period"] if days else None,
                row["period_error"],
                scale=days or 1.0,
            ),
            **_value("epoch", epoch, epoch_error),
            **_value("eccentricity", row["eccentricity"], row["eccentricity_error"]),
            **_value(
                "semi_major_axis",
                row["semi_major_axis"] if arcsec else None,
                row["semi_major_axis_error"],
                scale=arcsec or 1.0,
            ),
            **_value("inclination", row["inclination"], row["inclination_error"]),
            **_value("node", row["node"], row["node_error"]),
            **_value(
                "arg_periastron", row["arg_periastron"], row["arg_periastron_error"]
            ),
            epoch_event=binaries.PERIASTRON if epoch is not None else None,
            time_scale="JD" if epoch is not None else None,
            arg_periastron_of=None if astrometric else binaries.SECONDARY,
            node_ascending=None
            if row["node"] is None
            else row["node_flag"] == orb6.ASCENDING_NODE,
            equinox=row["equinox"],
            grade=None if row["grade"] is None else str(row["grade"]),
            reference=row["reference"],
        )
    table = out.table()
    logger.info("ORB6: %d orbits; %s", table.num_rows, dict(counts))
    return table


# The SBX alias catalogues that the trees know, by (catalog, version).
SBX_ALIASES = {
    ("HIP", None): HIP,
    ("HD", None): HD,
    ("HR", None): HR,
    ("Gaia", "DR3"): GAIA_DR3,
}
SBX_WDS = "WDS"
# Days to add to a shortened T0 of each `epoch_reference`.
SBX_OFFSETS = {"JD": 2_400_000.0, "RJD": 2_400_000.0, "MJD": 2_400_000.5}
FULL_JD = 2_000_000.0


def _sbx_epoch(value: float | None, reference: str | None) -> float | None:
    if value is None or value >= FULL_JD:
        return value
    offset = SBX_OFFSETS.get(reference or "")
    return None if offset is None else value + offset


def sbx_ids(directory: Path = sbx.OUT_DIR) -> dict[int, list[tuple[str, str, str]]]:
    """The ids of each SBX system: its number and its aliases in SBX_ALIASES.

    A WDS alias is "J" and the WDS id, then the component letters.
    """
    ids: dict[int, list[tuple[str, str, str]]] = defaultdict(list)
    for row in sbx.read_table(sbx.ALIAS, directory).to_pylist():
        catalogue, identifier = row["catalog"], row["identifier"]
        if identifier is None:
            continue
        kind = SBX_ALIASES.get((catalogue, row["version"]))
        if kind is None and catalogue == SBX_WDS and identifier.startswith("J"):
            kind, identifier = WDS_ID, identifier[1:11]
        if kind is not None and (*kind, identifier) not in ids[row["sn"]]:
            ids[row["sn"]].append((*kind, identifier))
    return ids


def sbx_orbits(directory: Path = sbx.OUT_DIR) -> pa.Table:
    """Every orbit of SBX.

    A T0 under FULL_JD is shortened as its `epoch_reference` says. ω and K1
    are taken as the primary's, as in a spectroscopic orbit.
    """
    systems = {
        row["sn"]: row for row in sbx.read_table(sbx.SYSTEMS, directory).to_pylist()
    }
    ids = sbx_ids(directory)
    out = _Rows(ORBITS, SBX)
    counts: Counter = Counter()
    for at, row in enumerate(sbx.read_table(sbx.ORBITS, directory).to_pylist()):
        sn = row["sn"]
        system = systems.get(sn, {})
        if not system:
            counts["orbits of no system"] += 1
            logger.debug(
                "SBX: orbit %d of system %d, which is not listed", row["on"], sn
            )
        epoch = _sbx_epoch(row["periastron_time"], row["epoch_reference"])
        flag = row["periastron_time_flag"]
        primary, secondary = _sides(system.get("component"))
        out.add(
            [*ids.get(sn, []), (*SBX_ID, str(sn))],
            system=str(sn),
            pair=system.get("component"),
            primary=primary,
            secondary=secondary,
            row=at,
            ra=system.get("ra"),
            dec=system.get("dec"),
            known=[SPECTROSCOPIC_ORBIT],
            **_value("period", row["period"], row["period_error"]),
            **_value("epoch", epoch, row["periastron_time_error"]),
            **_value("eccentricity", row["eccentricity"], row["eccentricity_error"]),
            **_value(
                "arg_periastron",
                row["periastron_argument"],
                row["periastron_argument_error"],
            ),
            **_value("k1", row["K1"], row["K1_error"]),
            **_value("k2", row["K2"], row["K2_error"]),
            **_value(
                "systemic_velocity",
                row["systemic_velocity"],
                row["systemic_velocity_error"],
            ),
            epoch_event=None
            if epoch is None
            else binaries.PERIASTRON
            if not flag
            else OTHER_EVENT,
            time_scale=None if epoch is None else "JD",
            arg_periastron_of=binaries.PRIMARY,
            grade=row["grade_legacy"],
            reference=row["bibcode"],
        )
    table = out.table()
    logger.info("SBX: %d orbits; %s", table.num_rows, dict(counts))
    return table


def _names(element: ET.Element) -> list[str]:
    return [
        n.text.strip() for n in element.findall("name") if n.text and n.text.strip()
    ]


def _oec_value(element: ET.Element, tag: str, name: str) -> dict[str, float | None]:
    found = element.find(tag)
    if found is None:
        return {}
    return _value(
        name,
        number(found.text),
        number(found.get("errorplus")),
        number(found.get("errorminus")),
    )


def read_oec(
    path: Path = OEC_SYSTEMS,
) -> tuple[pa.Table, pa.Table]:
    """The binaries of OEC as ORBITS, and their stars as COMPONENTS.

    P is in d and a in AU. A T of periastron comes first, else a time of
    transit. The XML has no row number, so `row` counts the binaries and
    the stars in document order.
    """
    orbits, stars = _Rows(ORBITS, OEC), _Rows(COMPONENTS, OEC)
    root = ET.fromstring(gzip.decompress(path.read_bytes()))
    for system in root.iter("system"):
        system_names = _names(system)
        key = system_names[0] if system_names else None
        ra = sexagesimal(system.findtext("rightascension"), hours=True)
        dec = sexagesimal(system.findtext("declination"), hours=False)
        for binary in system.iter("binary"):
            names = _names(binary)
            designation = names[0] if names else None
            epoch, binary_event = None, None
            for tag, kind in (
                ("periastrontime", binaries.PERIASTRON),
                ("transittime", TRANSIT),
            ):
                found = binary.find(tag)
                if found is not None and julian_date(number(found.text)) is not None:
                    epoch, binary_event = found, kind
                    break
            orbits.add(
                system=key,
                designation=designation,
                row=len(orbits.columns["row"]),
                names=names or None,
                ra=ra,
                dec=dec,
                **_oec_value(binary, "period", "period"),
                **_oec_value(binary, "semimajoraxis", "semi_major_axis_au"),
                **_oec_value(binary, "eccentricity", "eccentricity"),
                **_oec_value(binary, "inclination", "inclination"),
                **_oec_value(binary, "ascendingnode", "node"),
                **_oec_value(binary, "periastron", "arg_periastron"),
                **(
                    {}
                    if epoch is None
                    else _value(
                        "epoch",
                        julian_date(number(epoch.text)),
                        number(epoch.get("errorplus")),
                        number(epoch.get("errorminus")),
                    )
                ),
                epoch_event=binary_event,
                time_scale=None if epoch is None else epoch.get("unit") or "JD",
                node_ascending=True
                if binary.find("ascendingnode") is not None
                else None,
            )
            for star in binary.findall("star"):
                star_names = _names(star)
                label = star_names[0] if star_names else None
                stars.add(
                    [(*OEC_STAR, label)] if label else (),
                    system=key,
                    designation=designation,
                    row=len(stars.columns["row"]),
                    names=star_names or None,
                    label=label,
                    **_oec_value(star, "mass", "mass"),
                    **_oec_value(star, "radius", "radius"),
                    **_oec_value(star, "temperature", "teff"),
                    **_oec_value(star, "metallicity", "metallicity"),
                    spectral_type=star.findtext("spectraltype") or None,
                )
    orbit_table, star_table = orbits.table(), stars.table()
    logger.info(
        "OEC: %d binaries, %d of their stars", orbit_table.num_rows, star_table.num_rows
    )
    return orbit_table, star_table


def _literature_value(
    name: str, value: binaries.Value | None, scale: float = 1.0
) -> dict[str, float | None]:
    if value is None:
        return {}
    return _value(name, value.value, value.upper, value.lower, scale=scale)


def read_literature(
    table: dict[tuple[str, str, str], binaries.Binary] = binaries.BINARIES,
) -> tuple[pa.Table, pa.Table]:
    """The paper table as ORBITS and COMPONENTS.

    `system` is the key as `catalogue/release/id`. a in solar radii goes to
    AU. Where a paper prints only e cos ω and e sin ω, ω is computed from
    them and named in `derived`.
    """
    orbits, stars = _Rows(ORBITS, LITERATURE), _Rows(COMPONENTS, LITERATURE)
    for at, (key, binary) in enumerate(table.items()):
        system = "/".join(key)
        first, second = binary.stars
        pair = f"{first.label},{second.label}"
        derived = []
        omega = _literature_value("arg_periastron", binary.arg_periastron)
        if not omega and binary.e_cos_omega and binary.e_sin_omega:
            angle = math.degrees(
                math.atan2(binary.e_sin_omega.value, binary.e_cos_omega.value)
            )
            omega = {"arg_periastron": angle % 360.0}
            derived.append("arg_periastron")
        scale = SOLAR_RADIUS_AU if binary.axis_unit == binaries.SOLAR_RADIUS else 1.0
        orbits.add(
            [key],
            system=system,
            pair=pair,
            primary=first.label,
            secondary=second.label,
            row=at,
            **_literature_value("period", binary.period),
            **_literature_value("epoch", binary.epoch),
            **_literature_value("eccentricity", binary.eccentricity),
            **_literature_value("semi_major_axis_au", binary.semi_major_axis, scale),
            **_literature_value("inclination", binary.inclination),
            **_literature_value("node", binary.node),
            **omega,
            **_literature_value("mean_longitude", binary.mean_longitude),
            epoch_event=binary.epoch_event if binary.epoch else None,
            time_scale=binary.time_scale,
            osculating_epoch=binary.osculating_epoch,
            frame=binary.frame,
            arg_periastron_of=None
            if binary.arg_periastron_of == binaries.NOT_STATED
            else binary.arg_periastron_of,
            derived=derived or None,
            reference=binary.reference,
        )
        for star in binary.stars:
            stars.add(
                [key],
                system=system,
                pair=pair,
                row=at,
                label=star.label,
                **_literature_value("mass", star.mass),
                **_literature_value("radius", star.radius),
                **_literature_value("teff", star.teff),
                reference=binary.reference,
            )
    return orbits.table(), stars.table()


def read_orbits() -> tuple[pa.Table, pa.Table]:
    """ORBITS and COMPONENTS of every source, in ORBIT_SOURCES order."""
    literature, literature_stars = read_literature()
    oec, oec_stars = read_oec()
    orbits = pa.concat_tables(
        [literature, msc_orbits(), orb6_orbits(), sbx_orbits(), oec]
    )
    masses = msc_masses(msc.read_table(msc.SYS_FILE).to_pylist())
    return orbits, pa.concat_tables([literature_stars, oec_stars, masses])
