"""Readers of the three exoplanet catalogues.

Each reader gives the stars and planets of one catalogue in one form. Values
keep the catalogue's units, which agree across the three: days, AU, degrees,
Jupiter masses and radii, solar masses and radii, kelvin, dex, parsecs. A
time is a Julian date: the readers add the offset of a shortened date.

ω is the argument of periastron as each paper gives it. Some papers give the
star's ω, which is the planet's plus 180°, and no catalogue says which.
"""

import csv
import gzip
import logging
import math
import re
import xml.etree.ElementTree as ET
from collections.abc import Iterable, Iterator
from dataclasses import dataclass, field
from pathlib import Path

from space_map_data.download.providers.exoplanets import (
    exoplanet_eu,
    nasa_archive,
    open_catalogue,
)

logger = logging.getLogger(__name__)

ARCHIVE = "nasa-exoplanet-archive"
EU = "exoplanet-eu"
OEC = "open-exoplanet-catalogue"
CATALOGUES = (ARCHIVE, EU, OEC)
_NOT_ALNUM = re.compile(r"[^a-z0-9]")
# The lens letter of a microlensing designation, "OGLE-2005-BLG-390L".
LENS = re.compile(r"(BLG-\d+)L\b")


def reduced(name: str) -> str:
    """A name in ASCII letters and digits only, without case.

    The joins of stars and planets compare names this way.
    """
    return _NOT_ALNUM.sub("", name.lower())


def close(a: float | None, b: float | None, tolerance: float) -> bool:
    """Whether two values differ by less than `tolerance` of the larger."""
    return a is not None and b is not None and abs(a - b) / max(a, b) < tolerance


# Greek letters as the catalogues abbreviate them in Bayer designations.
GREEK = {
    "alpha": "alf",
    "beta": "bet",
    "gamma": "gam",
    "delta": "del",
    "epsilon": "eps",
    "zeta": "zet",
    "eta": "eta",
    "theta": "tet",
    "iota": "iot",
    "kappa": "kap",
    "lambda": "lam",
    "mu": "mu",
    "nu": "nu",
    "xi": "ksi",
    "omicron": "omi",
    "pi": "pi",
    "rho": "rho",
    "sigma": "sig",
    "tau": "tau",
    "upsilon": "ups",
    "phi": "phi",
    "chi": "chi",
    "psi": "psi",
    "omega": "ome",
}

CONFIRMED, CONTROVERSIAL, OTHER = "confirmed", "controversial", "other"
TRUE_MASS, MINIMUM_MASS, ESTIMATED_MASS = "true", "minimum", "estimate"
S_TYPE, P_TYPE = "S-type", "P-type"
UPPER_LIMIT, LOWER_LIMIT = "<", ">"

PSCOMPPARS = nasa_archive.OUT_DIR / "pscomppars.csv"
EU_CATALOG = exoplanet_eu.OUT_DIR / exoplanet_eu.CATALOG_FILE
OEC_SYSTEMS = open_catalogue.OUT_DIR / open_catalogue.SYSTEMS_FILE

# A Julian date of the catalogues falls in these years (JD 2400000 is 1858).
JD_RANGE = (2_400_000.0, 2_480_000.0)
# The archive marks its own estimates in the reference cell.
CALCULATED = "Calculated Value"
# The planet letter after an optional component: `b`, `A b`, `Ab`, `(AB) b`.
_LETTER = re.compile(r"(?:\s|^|\))(?:[A-D]{1,2}|\([A-D]+\))?\s?([b-z])$")
# OEC and exoplanet.eu name some companions with a capital: `WD 0806-661 B`.
_CAPITAL_LETTER = re.compile(r"\s([B-Z])$")
_GAIA = re.compile(r"Gaia DR([23]) (\d+)")
_HIP = re.compile(r"HIP (\d+)\b")

METHODS = {
    "primary transit": "Transit",
    "transit": "Transit",
    "secondary transit": "Transit",
    "radial velocity": "Radial Velocity",
    "rv": "Radial Velocity",
    "imaging": "Imaging",
    "microlensing": "Microlensing",
    "astrometry": "Astrometry",
    "ttv": "Transit Timing Variations",
    "timing": "Timing",
    "kinematic": "Disk Kinematics",
    "other": "Other",
}
MICROLENSING = "Microlensing"
PULSAR_TIMING = "Pulsar Timing"


@dataclass(frozen=True)
class Measure:
    """A value with its errors. Errors are positive or None."""

    value: float
    upper: float | None = None
    lower: float | None = None
    # UPPER_LIMIT or LOWER_LIMIT when the value is a limit.
    limit: str | None = None
    # The catalogue estimated it from other values.
    estimated: bool = False


@dataclass
class Star:
    """A star as one catalogue lists it."""

    catalogue: str
    # The catalogue id: the archive's hostid, else the first name.
    key: str
    name: str
    names: tuple[str, ...]
    # The catalogue's name for its system.
    system: str | None = None
    ra: float | None = None
    dec: float | None = None
    # Julian year of ra and dec.
    epoch: float | None = None
    gaia_dr3: int | None = None
    gaia_dr2: int | None = None
    hip: int | None = None
    values: dict[str, Measure] = field(default_factory=dict)
    spectral_type: str | None = None
    # Order of the star in its OEC system.
    order: int = 0


@dataclass
class Planet:
    """A planet as one catalogue lists it."""

    catalogue: str
    # The catalogue id: the archive's objectid, else the first name.
    key: str
    name: str
    names: tuple[str, ...]
    status: str
    # The key of its star in the same catalogue. None: no host star.
    star: str | None
    letter: str | None = None
    method: str | None = None
    year: int | None = None
    facility: str | None = None
    # S_TYPE or P_TYPE when OEC puts it in a binary.
    binary: str | None = None
    values: dict[str, Measure] = field(default_factory=dict)
    mass_kind: str | None = None
    molecules: tuple[str, ...] = ()
    # The time system of the transit and periastron times, as published.
    time_system: str | None = None


@dataclass
class Catalogue:
    name: str
    stars: dict[str, Star]
    planets: list[Planet]


def number(text: str | None) -> float | None:
    if text is None:
        return None
    try:
        value = float(text)
    except ValueError:
        return None
    return value if math.isfinite(value) else None


def letter_of(name: str, capital: bool = False) -> str | None:
    """The planet letter at the end of a designation, if any.

    With `capital`, a final capital B to Z after a space counts as its small
    letter.
    """
    found = _LETTER.search(name.strip())
    if found:
        return found[1]
    found = _CAPITAL_LETTER.search(name.strip()) if capital else None
    return found[1].lower() if found else None


def julian_date(value: float | None) -> float | None:
    """A full Julian date from a full or shortened one; None when out of range."""
    if value is None:
        return None
    if 0 < value < 10_000:
        value += 2_450_000
    elif 10_000 <= value < 100_000:
        value += 2_400_000
    return value if JD_RANGE[0] <= value <= JD_RANGE[1] else None


def method_of(text: str | None) -> str | None:
    """The first method of a list, in the archive's words."""
    if not text or not text.strip():
        return None
    first = text.split(",")[0].strip()
    return METHODS.get(first.lower(), first)


def _error(text: str | None) -> float | None:
    value = number(text)
    return None if value is None else abs(value)


def _split(text: str) -> list[str]:
    return [part.strip() for part in text.split(",") if part.strip()]


def _unique(names: Iterable[str]) -> tuple[str, ...]:
    return tuple(dict.fromkeys(n.strip() for n in names if n and n.strip()))


def _rows(path: Path) -> Iterator[dict[str, str]]:
    csv.field_size_limit(1 << 30)
    with path.open(newline="") as fh:
        yield from csv.DictReader(fh)


# The NASA Exoplanet Archive


def _archive_measure(row: dict[str, str], column: str) -> Measure | None:
    value = number(row.get(column))
    if value is None:
        return None
    limit = {"1": UPPER_LIMIT, "-1": LOWER_LIMIT}.get(row.get(f"{column}lim", ""))
    return Measure(
        value,
        _error(row.get(f"{column}err1")),
        _error(row.get(f"{column}err2")),
        limit,
        CALCULATED in row.get(f"{column}_reflink", ""),
    )


ARCHIVE_PLANET = {
    "period": "pl_orbper",
    "semi_major_axis": "pl_orbsmax",
    "eccentricity": "pl_orbeccen",
    "inclination": "pl_orbincl",
    "omega": "pl_orblper",
    "periastron_time": "pl_orbtper",
    "transit_time": "pl_tranmid",
    "mass": "pl_bmassj",
    "radius": "pl_radj",
    "equilibrium_temperature": "pl_eqt",
    "insolation": "pl_insol",
    "density": "pl_dens",
    "star_mass": "st_mass",
    "star_radius": "st_rad",
    "star_teff": "st_teff",
    "star_metallicity": "st_met",
    "angular_separation": "pl_angsep",
}
ARCHIVE_STAR = {
    "distance": "sy_dist",
    "parallax": "sy_plx",
    "pmra": "sy_pmra",
    "pmdec": "sy_pmdec",
    "teff": "st_teff",
    "radius": "st_rad",
    "mass": "st_mass",
    "metallicity": "st_met",
    "logg": "st_logg",
    "age": "st_age",
    "v_mag": "sy_vmag",
    "g_mag": "sy_gaiamag",
    "k_mag": "sy_kmag",
}
ARCHIVE_MASS_KINDS = {
    "Mass": TRUE_MASS,
    "Msin(i)/sin(i)": TRUE_MASS,
    "Msini": MINIMUM_MASS,
    "M-R relationship": ESTIMATED_MASS,
}
# The archive's positions are Gaia DR2's for nearly every star.
ARCHIVE_EPOCH = 2015.5


def _gaia_id(text: str, release: str) -> int | None:
    found = _GAIA.fullmatch(text.strip())
    return int(found[2]) if found and found[1] == release else None


def read_archive(path: Path = PSCOMPPARS) -> Catalogue:
    """The planets of `pscomppars` and their host stars."""
    stars: dict[str, Star] = {}
    planets = []
    rows = sorted(_rows(path), key=lambda row: row["pl_name"])
    for row in rows:
        host = row["hostid"]
        if host not in stars:
            hip = _HIP.fullmatch(row["hip_name"].strip())
            stars[host] = Star(
                catalogue=ARCHIVE,
                key=host,
                name=row["hostname"],
                names=_unique(
                    [row["hostname"], row["hd_name"], row["hip_name"], row["tic_id"]]
                ),
                system=row["sy_name"] or None,
                ra=number(row["ra"]),
                dec=number(row["dec"]),
                epoch=ARCHIVE_EPOCH,
                gaia_dr3=_gaia_id(row["gaia_dr3_id"], "3"),
                gaia_dr2=_gaia_id(row["gaia_dr2_id"], "2"),
                hip=int(hip[1]) if hip else None,
                values={
                    name: found
                    for name, column in ARCHIVE_STAR.items()
                    if (found := _archive_measure(row, column)) is not None
                },
                spectral_type=row["st_spectype"] or None,
            )
        values = {
            name: found
            for name, column in ARCHIVE_PLANET.items()
            if (found := _archive_measure(row, column)) is not None
        }
        kind = ARCHIVE_MASS_KINDS.get(row["pl_bmassprov"])
        if "mass" in values and kind == ESTIMATED_MASS:
            mass = values["mass"]
            values["mass"] = Measure(
                mass.value, mass.upper, mass.lower, mass.limit, True
            )
        planets.append(
            Planet(
                catalogue=ARCHIVE,
                key=row["objectid"],
                name=row["pl_name"],
                names=(row["pl_name"],),
                status=CONTROVERSIAL if row["pl_controv_flag"] == "1" else CONFIRMED,
                star=host,
                letter=row["pl_letter"] or letter_of(row["pl_name"]),
                method=method_of(row["discoverymethod"]),
                year=int(row["disc_year"]) if row["disc_year"] else None,
                facility=row["disc_facility"] or None,
                binary=P_TYPE if row["cb_flag"] == "1" else None,
                values=values,
                mass_kind=kind if "mass" in values else None,
                time_system=row["pl_tranmid_systemref"] or None,
            )
        )
    logger.info("archive: %d planets around %d stars", len(planets), len(stars))
    return Catalogue(ARCHIVE, stars, planets)


# exoplanet.eu


def _eu_measure(
    row: dict[str, str], column: str, estimated: bool = False
) -> Measure | None:
    value = number(row.get(column))
    if value is None:
        return None
    return Measure(
        value,
        _error(row.get(f"{column}_error_max")),
        _error(row.get(f"{column}_error_min")),
        estimated=estimated,
    )


def _eu_time(row: dict[str, str], column: str) -> Measure | None:
    found = _eu_measure(row, column)
    if found is None:
        return None
    value = julian_date(found.value)
    if value is None:
        return None
    return Measure(value, found.upper, found.lower)


EU_STATUS = {"Confirmed": CONFIRMED, "Controversial": CONTROVERSIAL}
EU_PLANET = {
    "period": "orbital_period",
    "semi_major_axis": "semi_major_axis",
    "eccentricity": "eccentricity",
    "inclination": "inclination",
    "omega": "omega",
    "star_mass": "star_mass",
    "star_radius": "star_radius",
    "star_teff": "star_teff",
    "star_metallicity": "star_metallicity",
}
EU_STAR = {
    "distance": "star_distance",
    "teff": "star_teff",
    "radius": "star_radius",
    "mass": "star_mass",
    "metallicity": "star_metallicity",
    "age": "star_age",
    "v_mag": "mag_v",
    "k_mag": "mag_k",
}
EU_THEORETICAL = "Theoretical"
# exoplanet.eu gives J2000 positions to about an arcsecond.
EU_EPOCH = 2000.0


def _eu_mass(row: dict[str, str]) -> tuple[Measure | None, str | None]:
    mass, sini = _eu_measure(row, "mass"), _eu_measure(row, "mass_sini")
    if mass is not None:
        if row["mass_measurement_type"] == EU_THEORETICAL:
            return _eu_measure(row, "mass", estimated=True), ESTIMATED_MASS
        # Some rows repeat m sin i as the mass.
        if sini is not None and sini.value == mass.value:
            return sini, MINIMUM_MASS
        return mass, TRUE_MASS
    if sini is not None:
        return sini, MINIMUM_MASS
    return None, None


def read_eu(path: Path = EU_CATALOG) -> Catalogue:
    """The objects of exoplanet.eu that have a host star, and those stars."""
    stars: dict[str, Star] = {}
    planets = []
    without_star = 0
    for row in sorted(_rows(path), key=lambda row: row["name"]):
        star_name = row["star_name"].strip()
        if not star_name:
            without_star += 1
            continue
        if star_name not in stars:
            stars[star_name] = Star(
                catalogue=EU,
                key=star_name,
                name=star_name,
                names=_unique([star_name, *_split(row["star_alternate_names"])]),
                ra=number(row["ra"]),
                dec=number(row["dec"]),
                epoch=EU_EPOCH,
                values={
                    name: found
                    for name, column in EU_STAR.items()
                    if (found := _eu_measure(row, column)) is not None
                },
                spectral_type=row["star_sp_type"] or None,
            )
        values = {
            name: found
            for name, column in EU_PLANET.items()
            if (found := _eu_measure(row, column)) is not None
        }
        for name, columns in (
            ("periastron_time", ("tperi",)),
            ("transit_time", ("tzero_tr", "tconj")),
        ):
            for column in columns:
                if (found := _eu_time(row, column)) is not None:
                    values[name] = found
                    break
        mass, kind = _eu_mass(row)
        if mass is not None:
            values["mass"] = mass
        radius = _eu_measure(
            row, "radius", row["radius_measurement_type"] == EU_THEORETICAL
        )
        if radius is not None:
            values["radius"] = radius
        name = row["name"].strip()
        year = number(row["discovered"])
        planets.append(
            Planet(
                catalogue=EU,
                key=name,
                name=name,
                names=_unique([name, *_split(row["alternate_names"])]),
                status=EU_STATUS.get(row["planet_status"], OTHER),
                star=star_name,
                letter=letter_of(name, capital=True),
                method=method_of(row["detection_type"]),
                year=int(year) if year else None,
                values=values,
                mass_kind=kind,
                molecules=tuple(_split(row["molecules"])),
            )
        )
    logger.info(
        "exoplanet.eu: %d objects around %d stars, %d without a star",
        len(planets),
        len(stars),
        without_star,
    )
    return Catalogue(EU, stars, planets)


# The Open Exoplanet Catalogue

OEC_CONFIRMED = "Confirmed planets"
OEC_CONTROVERSIAL = "Controversial"
OEC_PLANET = {
    "period": "period",
    "semi_major_axis": "semimajoraxis",
    "eccentricity": "eccentricity",
    "inclination": "inclination",
    "omega": "periastron",
    "periastron_time": "periastrontime",
    "transit_time": "transittime",
    "node": "ascendingnode",
}
OEC_STAR = {
    "teff": "temperature",
    "radius": "radius",
    "mass": "mass",
    "metallicity": "metallicity",
    "age": "age",
    "v_mag": "magV",
    "k_mag": "magK",
}
OEC_EPOCH = 2000.0


def _names(element: ET.Element) -> list[str]:
    return [
        n.text.strip() for n in element.findall("name") if n.text and n.text.strip()
    ]


def _oec_measure(element: ET.Element, tag: str) -> Measure | None:
    node = element.find(tag)
    if node is None:
        return None
    value = number(node.text)
    if value is None:
        return None
    return Measure(value, _error(node.get("errorplus")), _error(node.get("errorminus")))


def sexagesimal(text: str | None, hours: bool) -> float | None:
    """Degrees from `hh mm ss.s` or `±dd mm ss.s`."""
    if not text or not text.strip():
        return None
    parts = text.split()
    try:
        values = [abs(float(part)) for part in parts]
    except ValueError:
        return None
    degrees = sum(value / 60**i for i, value in enumerate(values))
    sign = -1.0 if parts[0].startswith("-") else 1.0
    return sign * degrees * (15.0 if hours else 1.0)


def _oec_status(planet: ET.Element) -> str:
    lists = {node.text for node in planet.findall("list")}
    if OEC_CONFIRMED in lists:
        return CONFIRMED
    if OEC_CONTROVERSIAL in lists:
        return CONTROVERSIAL
    return OTHER


def _unit(element: ET.Element, tag: str) -> str | None:
    node = element.find(tag)
    return None if node is None else node.get("unit")


def _first_star(element: ET.Element) -> ET.Element | None:
    """The first star of a binary, depth first."""
    return next(element.iter("star"), None)


def read_oec(path: Path = OEC_SYSTEMS) -> Catalogue:
    """The planets of OEC that orbit a star or a binary, and their stars."""
    root = ET.fromstring(gzip.decompress(path.read_bytes()))
    stars: dict[str, Star] = {}
    planets = []
    without_star = 0
    for system in root.iter("system"):
        system_names = _names(system)
        system_name = system_names[0] if system_names else None
        ra = sexagesimal(system.findtext("rightascension"), hours=True)
        dec = sexagesimal(system.findtext("declination"), hours=False)
        distance = _oec_measure(system, "distance")
        for order, element in enumerate(system.iter("star")):
            names = _names(element)
            if not names or names[0] in stars:
                continue
            values = {
                name: found
                for name, tag in OEC_STAR.items()
                if (found := _oec_measure(element, tag)) is not None
            }
            if distance is not None:
                values["distance"] = distance
            stars[names[0]] = Star(
                catalogue=OEC,
                key=names[0],
                name=names[0],
                names=_unique(names),
                system=system_name,
                ra=ra,
                dec=dec,
                epoch=OEC_EPOCH,
                values=values,
                spectral_type=element.findtext("spectraltype") or None,
                order=order,
            )
        planets += _oec_planets(system, None, None)
    for planet in planets:
        if planet.star is None:
            without_star += 1
    logger.info(
        "OEC: %d planets around %d stars, %d without a star",
        len(planets),
        len(stars),
        without_star,
    )
    return Catalogue(OEC, stars, planets)


def _oec_planets(
    element: ET.Element, star: str | None, binary: str | None
) -> list[Planet]:
    found = []
    for child in element:
        if child.tag == "planet":
            names = _names(child)
            if not names:
                continue
            values = {
                name: measure
                for name, tag in OEC_PLANET.items()
                if (measure := _oec_measure(child, tag)) is not None
            }
            for name in ("periastron_time", "transit_time"):
                if name in values:
                    jd = julian_date(values[name].value)
                    if jd is None:
                        del values[name]
                    else:
                        values[name] = Measure(
                            jd, values[name].upper, values[name].lower
                        )
            year = number(child.findtext("discoveryyear"))
            planet_type = binary
            host = star
            if element.tag == "binary":
                first = _first_star(element)
                first_names = _names(first) if first is not None else []
                host = first_names[0] if first_names else None
                planet_type = P_TYPE
            found.append(
                Planet(
                    catalogue=OEC,
                    key=names[0],
                    name=names[0],
                    names=_unique(names),
                    status=_oec_status(child),
                    star=host,
                    letter=letter_of(names[0], capital=True),
                    method=method_of(child.findtext("discoverymethod")),
                    year=int(year) if year else None,
                    binary=planet_type,
                    values=values,
                    time_system=_unit(child, "transittime"),
                )
            )
        elif child.tag == "star":
            names = _names(child)
            inside = binary or (S_TYPE if element.tag == "binary" else None)
            found += _oec_planets(child, names[0] if names else None, inside)
        elif child.tag == "binary":
            found += _oec_planets(child, None, S_TYPE)
    return found
