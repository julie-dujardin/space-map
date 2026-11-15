"""Galaxies that no catalogue here holds, with their values read from papers.

An entry is keyed by a name of ours that never changes: the registry keeps it
as the id of the galaxy, so each ingest finds the ID that an earlier one
minted. The ingest mints each galaxy in the Redshift table as the source
`galaxy-literature` and gives the values to their column groups. `facts`
holds the values that no column takes, because no galaxy catalogue gives
them, by a name of FACTS. Each value cites works of REFERENCES by their keys.
The galaxy's object entry cites them beside the value.

No paper counts the stars or the planets of the Milky Way. The export
estimates each as a range from the cited values
(`extrasolar/sources/galaxies.facts`).
"""

import math
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import NamedTuple

from space_map_data.constants.stars.literature import Reference
from space_map_data.galaxy.geometry import R0


class Position(NamedTuple):
    """The point of a galaxy: ICRS at `epoch` (Julian year), in deg, with the
    proper motion in mas/yr, `pmra` on ra·cos dec."""

    ra: float
    dec: float
    epoch: float
    pmra: float
    pmdec: float
    references: tuple[str, ...]


class Distance(NamedTuple):
    # pc, from the Sun to the point, with the 1σ bounds.
    value: float
    lower: float
    upper: float
    # A value of the Redshift `distance_method`.
    method: str
    references: tuple[str, ...]


class Value(NamedTuple):
    """A value with the lower and upper bound of its work, None where the
    work gives none. A lower limit has `lower` alone, a range both bounds
    and no value."""

    value: float | None
    lower: float | None
    upper: float | None
    references: tuple[str, ...]
    # True for a value that the export works out from cited values. Its
    # `lower` and `upper` are then the rounded ends of a range, not bounds.
    estimate: bool = False


class Text(NamedTuple):
    value: str
    references: tuple[str, ...]


@dataclass(frozen=True)
class Galaxy:
    name: str
    # The Wikidata item, checked against Wikidata.
    qid: str | None
    position: Position
    distance: Distance
    morphological_type: Text | None = None
    # Solar masses.
    stellar_mass: Value | None = None
    total_mass: Value | None = None
    # Solar masses per year.
    star_formation_rate: Value | None = None
    # Solar masses per star or stellar remnant. With the stellar mass it
    # gives the count of the stars.
    mean_star_mass: Value | None = None
    # True for the galaxy of the Sun.
    holds_sun: bool = False
    # pc, the radius of the Sun's orbit in the fit that gives
    # `circular_speed`. The period takes both from that fit: it measures
    # their ratio.
    sun_orbit_radius: Value | None = None
    facts: Mapping[str, Value] = field(default_factory=dict)


def around(value: float, error: float, *references: str) -> Value:
    """A value with a symmetric error."""
    return Value(value, value - error, value + error, references)


def _hours(hours: int, minutes: int, seconds: float) -> float:
    return 15 * (hours + minutes / 60 + seconds / 3600)


def _south(degrees: int, minutes: int, seconds: float) -> float:
    return -(degrees + minutes / 60 + seconds / 3600)


# The facts, with the unit of each. The export estimates the last three: the
# counts as ranges.
FACTS = {
    "black_hole_mass": "solar masses, of the central black hole",
    "age": "Gyr, since the disc began to form",
    "scale_length": "pc, of the exponential disc",
    "thin_disc_scale_height": "pc",
    "thick_disc_scale_height": "pc",
    "half_light_radius": "pc",
    "disc_radius": "pc, to the farthest disc stars",
    "bar_half_length": "pc",
    "stellar_halo_mass": "solar masses",
    "circular_speed": "km/s, at the radius of the Sun's orbit",
    "supernova_rate": "core-collapse supernovae per century",
    "globular_clusters": "count",
    "satellite_galaxies": "count",
    "planets_per_star": "bound planets per star",
    "free_floating_planets_per_star": "planets per star",
    "star_count": "stars and stellar remnants",
    "planet_count": "bound planets",
    "orbital_period": "Myr, of a circular orbit at the Sun's radius",
}

REFERENCES: dict[str, Reference] = {
    "cassan_2012": Reference(
        "Cassan et al. 2012",
        "One or more bound planets per Milky Way star from microlensing"
        " observations (Nature 481, 167)",
        "https://doi.org/10.1038/nature10684",
    ),
    "cautun_2020": Reference(
        "Cautun et al. 2020",
        "The Milky Way total mass profile as inferred from Gaia DR2 (MNRAS 494, 4291)",
        "https://doi.org/10.1093/mnras/staa1017",
    ),
    "chabrier_2003": Reference(
        "Chabrier 2003",
        "Galactic stellar and substellar initial mass function (PASP 115, 763)",
        "https://doi.org/10.1086/376392",
    ),
    "de_vaucouleurs_pence_1978": Reference(
        "de Vaucouleurs & Pence 1978",
        "An outsider's view of the Galaxy: photometric parameters, scale"
        " lengths, and absolute magnitudes of the spheroidal and disk components"
        " of our Galaxy (AJ 83, 1163)",
        "https://doi.org/10.1086/112305",
    ),
    "deason_2019": Reference(
        "Deason, Belokurov & Sanders 2019",
        "The total stellar halo mass of the Milky Way (MNRAS 490, 3426)",
        "https://doi.org/10.1093/mnras/stz2793",
    ),
    "gravity_2021": Reference(
        "GRAVITY Collaboration 2021",
        "Improved GRAVITY astrometric accuracy from modeling optical aberrations"
        " (A&A 647, A59)",
        "https://doi.org/10.1051/0004-6361/202040208",
    ),
    "gravity_2022": Reference(
        "GRAVITY Collaboration 2022",
        "Mass distribution in the Galactic Center based on interferometric"
        " astrometry of multiple stellar orbits (A&A 657, L12)",
        "https://doi.org/10.1051/0004-6361/202142465",
    ),
    "harris_2010": Reference(
        "Harris 2010",
        "A new catalog of globular clusters in the Milky Way (arXiv:1012.3224)",
        # The 2010 edition has no DOI.
        "https://arxiv.org/abs/1012.3224",
    ),
    "juric_2008": Reference(
        "Jurić et al. 2008",
        "The Milky Way tomography with SDSS. I. Stellar number density"
        " distribution (ApJ 673, 864)",
        "https://doi.org/10.1086/523619",
    ),
    "lian_2024": Reference(
        "Lian et al. 2024",
        "The broken-exponential radial structure and larger size of the Milky"
        " Way galaxy (Nature Astronomy 8, 1302)",
        "https://doi.org/10.1038/s41550-024-02315-7",
    ),
    "licquia_newman_2015": Reference(
        "Licquia & Newman 2015",
        "Improved estimates of the Milky Way's stellar mass and star formation"
        " rate from hierarchical Bayesian meta-analysis (ApJ 806, 96)",
        "https://doi.org/10.1088/0004-637X/806/1/96",
    ),
    "licquia_newman_2016": Reference(
        "Licquia & Newman 2016",
        "Sizing up the Milky Way: a Bayesian mixture model meta-analysis of"
        " photometric scale length measurements (ApJ 831, 71)",
        "https://doi.org/10.3847/0004-637X/831/1/71",
    ),
    "lopez_corredoira_2018": Reference(
        "López-Corredoira et al. 2018",
        "Disk stars in the Milky Way detected beyond 25 kpc from its center"
        " (A&A 612, L8)",
        "https://doi.org/10.1051/0004-6361/201832880",
    ),
    "pace_2025": Reference(
        "Pace 2025",
        "The Local Volume Database: a library of the observed properties of"
        " nearby dwarf galaxies and star clusters (Open J. Astrophys. 8)",
        "https://doi.org/10.33232/001c.144859",
    ),
    "reid_2019": Reference(
        "Reid et al. 2019",
        "Trigonometric parallaxes of high-mass star-forming regions: our view of"
        " the Milky Way (ApJ 885, 131)",
        "https://doi.org/10.3847/1538-4357/ab4a11",
    ),
    "rozwadowska_2021": Reference(
        "Rozwadowska, Vissani & Cappellaro 2021",
        "On the rate of core collapse supernovae in the Milky Way"
        " (New Astronomy 83, 101498)",
        "https://doi.org/10.1016/j.newast.2020.101498",
    ),
    "sumi_2023": Reference(
        "Sumi et al. 2023",
        "Free-floating planet mass function from MOA-II 9 yr survey toward the"
        " Galactic bulge (AJ 166, 108)",
        "https://doi.org/10.3847/1538-3881/ace688",
    ),
    "wegg_2015": Reference(
        "Wegg, Gerhard & Portail 2015",
        "The structure of the Milky Way's bar outside the bulge (MNRAS 450, 4050)",
        "https://doi.org/10.1093/mnras/stv745",
    ),
    "xiang_rix_2022": Reference(
        "Xiang & Rix 2022",
        "A time-resolved picture of our Milky Way's early formation history"
        " (Nature 603, 599)",
        "https://doi.org/10.1038/s41586-022-04496-5",
    ),
    "xu_2022": Reference(
        "Xu et al. 2022",
        "A milliarcsecond-accurate position for Sagittarius A* (ApJ 940, 15)",
        "https://doi.org/10.3847/1538-4357/ac98b9",
    ),
}

# Chabrier 2003, Table 3, disc column: the stars up to 1 M☉, the stars above
# and the remnants near the Sun, each with its error. No brown dwarfs: a
# count of stars leaves them out.
_NUMBER_DENSITY = ((0.13, 0.02), (0.004, 0.0), (0.007, 0.001))  # pc⁻³
_MASS_DENSITY = ((0.035, 0.003), (0.006, 0.0), (0.006, 0.001))  # M☉ pc⁻³


def _mean_star_mass() -> Value:
    """The mass density over the number density. The bounds take every error
    at its end."""
    number, number_error = map(sum, zip(*_NUMBER_DENSITY))
    mass, mass_error = map(sum, zip(*_MASS_DENSITY))
    return Value(
        mass / number,
        (mass - mass_error) / (number + number_error),
        (mass + mass_error) / (number - number_error),
        ("chabrier_2003",),
    )


# GRAVITY 2022 prints the statistical error of R0, 9 pc (Sect. 4), and takes
# the systematic one from GRAVITY 2021: 33 pc (Eq. 38).
_R0_ERROR = round(math.hypot(9, 33))

MILKY_WAY = "milky-way"

GALAXIES: dict[str, Galaxy] = {
    MILKY_WAY: Galaxy(
        "Milky Way",
        "Q321",
        # Sgr A*, from VLBA phase referencing: the position at 2020.0
        # (abstract, Table 4) and the motion from 1995 to 2020 (Sect. 3.2),
        # which is the reflex of the Sun's orbit.
        Position(
            _hours(17, 45, 40.032863),
            _south(29, 0, 28.24260),
            2020.0,
            -3.152,
            -5.586,
            ("xu_2022",),
        ),
        # From the orbits of S2, S29, S38 and S55 about Sgr A* (Sect. 4,
        # Table B.1).
        Distance(
            R0,
            R0 - _R0_ERROR,
            R0 + _R0_ERROR,
            "dynamical",
            ("gravity_2022", "gravity_2021"),
        ),
        # The revised Hubble type, T = 4 ± 0.5 (abstract). The paper adds the
        # luminosity class II.
        morphological_type=Text("SAB(rs)bc", ("de_vaucouleurs_pence_1978",)),
        # Bulge, thin disc and thick disc of the mass model with a contracted
        # halo, fitted to the Gaia DR2 rotation curve (Table 2). No stellar
        # halo, no gas.
        stellar_mass=Value(5.04e10, 4.52e10, 5.47e10, ("cautun_2020",)),
        # M200 of the same model (Table 2).
        total_mass=Value(1.08e12, 0.94e12, 1.28e12, ("cautun_2020",)),
        # A combination of the earlier measurements, with a Kroupa IMF
        # (abstract).
        star_formation_rate=around(1.65, 0.19, "licquia_newman_2015"),
        mean_star_mass=_mean_star_mass(),
        holds_sun=True,
        # R0 of fit A5 to the masers (abstract, Table 3).
        sun_orbit_radius=around(8150, 150, "reid_2019"),
        facts={
            # Sgr A*, at R0 = 8277 pc, with the statistical error (Sect. 4,
            # Table B.1).
            "black_hole_mass": around(4.297e6, 0.012e6, "gravity_2022"),
            # When the old disc began to form, from the ages of subgiants.
            # The paper gives no error (abstract).
            "age": Value(13.0, None, None, ("xiang_rix_2022",)),
            # 29 photometric measurements combined (abstract).
            "scale_length": around(2640, 130, "licquia_newman_2016"),
            # Near the Sun, from SDSS M dwarfs, each good to 20% (abstract).
            "thin_disc_scale_height": around(300, 60, "juric_2008"),
            "thick_disc_scale_height": around(900, 180, "juric_2008"),
            # The radius that holds half of the disc's light, from APOGEE
            # (abstract).
            "half_light_radius": around(5750, 380, "lian_2024"),
            # Disc stars are found past this radius at 99.7% confidence
            # (abstract).
            "disc_radius": Value(None, 26000, None, ("lopez_corredoira_2018",)),
            # The long bar, from red clump giants (abstract).
            "bar_half_length": around(5000, 200, "wegg_2015"),
            # From Gaia DR2 red giants (abstract).
            "stellar_halo_mass": around(1.4e9, 0.4e9, "deason_2019"),
            # Θ0 of fit A5 to the masers, at its R0 (abstract, Table 3).
            "circular_speed": around(236, 7, "reid_2019"),
            # Core-collapse supernovae (Eq. 17).
            "supernova_rate": around(1.63, 0.46, "rozwadowska_2021"),
            # The 2010 edition of the catalogue (abstract).
            "globular_clusters": Value(157, None, None, ("harris_2010",)),
            # "At least 65" dwarf galaxies (p. 5).
            "satellite_galaxies": Value(None, 65, None, ("pace_2025",)),
            # Planets of 5 M⊕ to 10 MJ at 0.5 to 10 AU, from microlensing
            # (p. 4).
            "planets_per_star": Value(1.6, 0.71, 2.32, ("cassan_2012",)),
            # Free-floating or on very wide orbits, 0.33 to 6660 M⊕, from 6
            # short events (abstract).
            "free_floating_planets_per_star": Value(21, 8, 44, ("sumi_2023",)),
        },
    ),
}


def galaxy_qids() -> set[str]:
    """The Wikidata items of the galaxies of the list."""
    return {galaxy.qid for galaxy in GALAXIES.values() if galaxy.qid}
