"""Solar-system body sizes and GMs read from papers.

An entry is keyed by the NAIF id of the body, which stays the same between
ingests. Each value cites one work of REFERENCES by its key. The radius
chooser takes the sizes first, above the kernel and catalogue values that they
correct. The GMs are of bodies that no kernel of the pool has: `target_bodies`
writes them into kernels of its own for the probe fits, and the mass chooser
credits each to its paper, not to the kernel.
"""

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


def _sphere(diameter_km: float, reference: str) -> Radii:
    radius = diameter_km / 2
    return Radii((radius, radius, radius), reference)


def _ellipsoid(a_km: float, b_km: float, c_km: float, reference: str) -> Radii:
    """An ellipsoid from its three full axes."""
    return Radii((a_km / 2, b_km / 2, c_km / 2), reference)


REFERENCES: dict[str, Reference] = {
    "abe_2006": Reference(
        "Abe et al. 2006 (Science 312, 1344)",
        "https://doi.org/10.1126/science.1126272",
    ),
    "grav_2015": Reference(
        "Grav et al. 2015 (ApJ 809, 3)",
        "https://doi.org/10.1088/0004-637X/809/1/3",
    ),
    "marchis_2006": Reference(
        "Marchis et al. 2006 (Nature 439, 565)",
        "https://doi.org/10.1038/nature04350",
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
    "sicardy_2011": Reference(
        "Sicardy et al. 2011 (Nature 478, 493)",
        "https://doi.org/10.1038/nature10550",
    ),
    "weaver_2016": Reference(
        "Weaver et al. 2016 (Science 351, aae0030)",
        "https://doi.org/10.1126/science.aae0030",
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
    2025143: Gm("2.389E-9", "abe_2006"),  # Itokawa, 3.58e10 kg
    1000012: Gm("6.662E-7", "patzold_2016"),  # 67P, 666.2 m^3/s^2
}

# The GM of a primary and its satellite together, from the satellite orbit.
SYSTEM_GMS: dict[int, Gm] = {
    2000617: Gm("9.08E-2", "marchis_2006", 20000617),  # Patroclus, 1.36e18 kg
}
