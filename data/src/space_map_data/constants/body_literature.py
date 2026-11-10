"""Solar-system body sizes and GMs read from papers.

An entry is keyed by the NAIF id of the body, which stays the same between
ingests. Each value cites one work of REFERENCES by its key. The radius
chooser takes the sizes first, above the kernel and catalogue values that they
correct, and the density takes the volumes. The GMs are of bodies that no
kernel of the pool has: `target_bodies` writes them into kernels of its own,
which the probe fits and the mass chooser read, and the mass chooser credits
each to its paper, not to the kernel.
"""

import math
from typing import NamedTuple

from space_map_data.constants.measured_shapes import Reference


class Radii(NamedTuple):
    # Semi-axes, a >= b >= c, km.
    semi_axes_km: tuple[float, float, float]
    reference: str


class Gm(NamedTuple):
    # km^3/s^2, as the kernel writes it.
    gm: str
    reference: str
    # The id the probe fits ask for, where it is not the NAIF id of the body:
    # Lucy's kernels name their targets by SBDB spkid.
    spice_id: int | None = None


class Volume(NamedTuple):
    km3: float
    reference: str


def _sphere(diameter_km: float, reference: str) -> Radii:
    radius = diameter_km / 2
    return Radii((radius, radius, radius), reference)


def _equal_volume_sphere(radius_km: float, reference: str) -> Volume:
    """The volume of a shape model from the radius of the sphere of its
    volume, which is what the paper gives."""
    return Volume(4 / 3 * math.pi * radius_km**3, reference)


def _ellipsoid(a_km: float, b_km: float, c_km: float, reference: str) -> Radii:
    """An ellipsoid from its three full axes."""
    return Radii((a_km / 2, b_km / 2, c_km / 2), reference)


REFERENCES: dict[str, Reference] = {
    "barnouin_2024": Reference(
        "Barnouin et al. 2024 (Nat. Commun. 15, 6202)",
        "https://doi.org/10.1038/s41467-024-50146-x",
    ),
    "buratti_2019": Reference(
        "Buratti et al. 2019 (Science 364, eaat2349)",
        "https://doi.org/10.1126/science.aat2349",
    ),
    "daly_2024": Reference(
        "Daly et al. 2024 (PSJ 5, 24)",
        "https://doi.org/10.3847/PSJ/ad0b07",
    ),
    "fujiwara_2006": Reference(
        "Fujiwara et al. 2006 (Science 312, 1330)",
        "https://doi.org/10.1126/science.1125841",
    ),
    "grav_2015": Reference(
        "Grav et al. 2015 (ApJ 809, 3)",
        "https://doi.org/10.1088/0004-637X/809/1/3",
    ),
    "kiss_2019": Reference(
        "Kiss et al. 2019 (Icarus 334, 3)",
        "https://doi.org/10.1016/j.icarus.2019.03.013",
    ),
    "marchis_2006": Reference(
        "Marchis et al. 2006 (Nature 439, 565)",
        "https://doi.org/10.1038/nature04350",
    ),
    "park_2025": Reference(
        "Park et al. 2025 (Nat. Astron. 9, 824)",
        "https://doi.org/10.1038/s41550-025-02533-7",
    ),
    "patzold_2011": Reference(
        "Pätzold et al. 2011 (Science 334, 491)",
        "https://doi.org/10.1126/science.1209389",
    ),
    "patzold_2016": Reference(
        "Pätzold et al. 2016 (Nature 530, 63)",
        "https://doi.org/10.1038/nature16535",
    ),
    "scheeres_2019": Reference(
        "Scheeres et al. 2019 (Nat. Astron. 3, 352)",
        "https://doi.org/10.1038/s41550-019-0721-3",
    ),
    "shepard_2021": Reference(
        "Shepard et al. 2021 (PSJ 2, 125)",
        "https://doi.org/10.3847/PSJ/abfdba",
    ),
    "sicardy_2011": Reference(
        "Sicardy et al. 2011 (Nature 478, 493)",
        "https://doi.org/10.1038/nature10550",
    ),
    "weaver_2016": Reference(
        "Weaver et al. 2016 (Science 351, aae0030)",
        "https://doi.org/10.1126/science.aae0030",
    ),
    "willner_2014": Reference(
        "Willner et al. 2014 (PSS 102, 51)",
        "https://doi.org/10.1016/j.pss.2013.12.006",
    ),
    "yeomans_1997": Reference(
        "Yeomans et al. 1997 (Science 278, 2106)",
        "https://doi.org/10.1126/science.278.5346.2106",
    ),
}

RADII: dict[int, Radii] = {
    # NEOWISE thermal fits, Table 3. The PCK holds the IAU mean radii of the
    # 1990s, or a placeholder sphere.
    506: _sphere(139.6, "grav_2015"),  # Himalia
    507: _sphere(79.9, "grav_2015"),  # Elara
    508: _sphere(57.8, "grav_2015"),  # Pasiphae
    509: _sphere(35.0, "grav_2015"),  # Sinope
    510: _sphere(42.2, "grav_2015"),  # Lysithea
    511: _sphere(46.7, "grav_2015"),  # Carme
    512: _sphere(29.1, "grav_2015"),  # Ananke
    513: _sphere(21.5, "grav_2015"),  # Leda
    517: _sphere(9.6, "grav_2015"),  # Callirrhoe
    523: _sphere(6.9, "grav_2015"),  # Kalyke
    527: _sphere(7.0, "grav_2015"),  # Praxidike
    626: _sphere(28.6, "grav_2015"),  # Albiorix
    629: _sphere(39.3, "grav_2015"),  # Siarnaq
    # The 2010 occultation, a sphere of 1163 ± 6 km radius. SsODNet has 2400 km.
    2136199: _sphere(2326.0, "sicardy_2011"),  # Eris
    # New Horizons ellipsoid fits, Table 2, ±3 km. The PCK holds a synthetic
    # 100 km sphere.
    904: _ellipsoid(19, 10, 9, "weaver_2016"),  # Kerberos
    905: _ellipsoid(16, 9, 8, "weaver_2016"),  # Styx
}

# The GM of the body alone, from a spacecraft that flew by or orbited it.
GMS: dict[int, Gm] = {
    2000021: Gm("1.134E-1", "patzold_2011"),  # Lutetia, 1.700e18 kg
    2000253: Gm("6.89E-3", "yeomans_1997"),  # Mathilde, 1.033e17 kg
    2101955: Gm("4.892E-9", "scheeres_2019"),  # Bennu, 4.892 m^3/s^2
    # The weighted mean of the four Hayabusa fits, ±3%.
    2025143: Gm("2.343E-9", "fujiwara_2006"),  # Itokawa, 3.51e10 kg
    1000012: Gm("6.662E-7", "patzold_2016"),  # 67P, 666.2 m^3/s^2
}

# The GM of a primary and its satellite together, from the satellite orbit.
SYSTEM_GMS: dict[int, Gm] = {
    2000617: Gm("9.08E-2", "marchis_2006", 20000617),  # Patroclus, 1.36e18 kg
    # The mean of the prograde and retrograde orbits of Xiangliu, ±0.07e21 kg.
    2225088: Gm("1.168E+2", "kiss_2019"),  # Gonggong, 1.75e21 kg
}

# The volume of a body's shape model. The density takes it over that of the
# ellipsoid of the body's size, which an irregular body is far from.
VOLUMES: dict[int, Volume] = {
    401: Volume(5742, "willner_2014"),  # Phobos, ±35 km^3
    615: _equal_volume_sphere(14.9, "buratti_2019"),  # Atlas, ±0.2 km
    618: _equal_volume_sphere(13.7, "buratti_2019"),  # Pan, ±0.3 km
    # Dawn's whole-mission shape model, ±0.01e7 km^3.
    2000004: Volume(7.49e7, "park_2025"),  # Vesta
    2000016: Volume(5.75e6, "shepard_2021"),  # Psyche, ±0.19e6 km^3
    2025143: Volume(0.0184, "fujiwara_2006"),  # Itokawa, ±5%
    # DART's model, ±3.4%, which its authors think a little small (the unlit
    # limb).
    2065803: Volume(0.203, "barnouin_2024"),  # Didymos
    120065803: Volume(0.00176, "daly_2024"),  # Dimorphos, ±5%
}
