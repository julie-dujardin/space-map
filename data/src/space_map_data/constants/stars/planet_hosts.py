"""Planet rows of the exoplanet catalogues that a paper corrects.

A row is (catalogue, key), with the key of `Planet`: the objectid in the
archive, else the first name. An objectid stays when the archive changes a
letter. Each entry cites one work of REFERENCES by its key.

HOSTS gives a row the star that a paper says it orbits. The row stays out of
the planet join, takes no letter and loses its star columns. Its host row
claims the key of the star, so that the star keeps its one point.

JOINS makes one planet of two rows that no score can join. The named row
comes from an earlier catalogue. A row with no star names the row that gives
it one, which can come later.

STARS gives a star row of a catalogue, keyed by (catalogue, star key), the key
and position of its star. The row then claims that key.

An entry that names no row stops the ingest before it writes anything. A key
that its row does not reach stops the ingest before its commit.
"""

from typing import NamedTuple

from space_map_data.constants.stars.literature import Reference, StarKey

ARCHIVE = "nasa-exoplanet-archive"
EU = "exoplanet-eu"
OEC = "open-exoplanet-catalogue"


class HostStar(NamedTuple):
    # An id of the star that stays the same between ingests.
    key: StarKey
    # Its name in the host rows.
    name: str
    # J2016.0, deg. The engine looks for a claim only near the claiming row.
    ra: float
    dec: float


class Host(NamedTuple):
    star: HostStar
    reference: str


class Join(NamedTuple):
    # The row of the same planet.
    row: tuple[str, str]
    reference: str


REFERENCES: dict[str, Reference] = {
    "benedict_2022": Reference(
        "Benedict et al. 2022",
        "The μ Arae Planetary System: Radial Velocities and Astrometry (AJ 163, 295)",
        "https://doi.org/10.3847/1538-3881/ac6ac8",
    ),
    "best_2017": Reference(
        "Best et al. 2017",
        "The Young L Dwarf 2MASS J11193254−1137466 Is a Planetary-mass Binary"
        " (ApJL 843, L4)",
        "https://doi.org/10.3847/2041-8213/aa76df",
    ),
    "bowler_2015": Reference(
        "Bowler & Hillenbrand 2015",
        "Near-infrared Spectroscopy of 2M0441+2301 AabBab: A Quadruple System"
        " Spanning the Stellar to Planetary Mass Regimes (ApJ 811, L30)",
        "https://doi.org/10.1088/2041-8205/811/2/L30",
    ),
    "burgasser_2011": Reference(
        "Burgasser et al. 2011",
        "The Hyperactive L Dwarf 2MASS J13153094−2649513: Continued Emission and a"
        " Brown Dwarf Companion (ApJ 739, 49)",
        "https://doi.org/10.1088/0004-637X/739/1/49",
    ),
    "chung_2019": Reference(
        "Chung et al. 2019",
        "Spitzer Microlensing of MOA-2016-BLG-231L: A Counter-rotating Brown"
        " Dwarf Binary in the Galactic Disk (ApJ 871, 179)",
        "https://doi.org/10.3847/1538-4357/aaf861",
    ),
    "deacon_2014": Reference(
        "Deacon et al. 2014",
        "Wide Cool and Ultracool Companions to Nearby Stars from Pan-STARRS 1"
        " (ApJ 792, 119)",
        "https://doi.org/10.1088/0004-637X/792/2/119",
    ),
    "dupuy_2014": Reference(
        "Dupuy et al. 2014",
        "New Evidence for a Substellar Luminosity Problem: Dynamical Mass for"
        " the Brown Dwarf Binary Gl 417BC (ApJ 790, 133)",
        "https://doi.org/10.1088/0004-637X/790/2/133",
    ),
    "guerrero_2021": Reference(
        "Guerrero et al. 2021",
        "The TESS Objects of Interest Catalog from the TESS Prime Mission"
        " (ApJS 254, 39)",
        "https://doi.org/10.3847/1538-4365/abefe1",
    ),
    "hoy_2026": Reference(
        "Hoy et al. 2026",
        "Planetary-mass exosatellite detected around the substellar companion"
        " of a star (Nature 655, 865)",
        "https://doi.org/10.1038/s41586-026-10751-w",
    ),
    "thompson_2025": Reference(
        "Thompson et al. 2025",
        "On the Orbit of the Binary Brown Dwarf Companion GL229 Ba and Bb"
        " (AJ 169, 193)",
        "https://doi.org/10.3847/1538-3881/adb4f2",
    ),
    "xuan_2024": Reference(
        "Xuan et al. 2024",
        "The cool brown dwarf Gliese 229 B is a close binary (Nature 634, 1070)",
        "https://doi.org/10.1038/s41586-024-08064-x",
    ),
}

# Aa, the M4.5 star of the pair Aab. SIMBAD and the WDS swap A and B here.
_2M0441_A = HostStar(
    ("gaia", "dr3", "146487560507840768"),
    "2MASS J04414565+2301580",
    70.44025,
    23.03269,
)
_GJ_229_B = HostStar(("simbad", "oid", "864867"), "GJ 229 B", 92.64434, -21.86984)
_HD_97334_B = HostStar(
    ("gaia", "dr3", "761918578311083264"), "HD 97334 B", 168.10552, 35.80287
)
_NLTT_31450 = HostStar(
    ("gaia", "dr3", "1514394443389500288"), "NLTT 31450", 189.95550, 32.14722
)

HOSTS: dict[tuple[str, str], Host] = {
    # The brown dwarf at 33 AU from Aa (Sect. 1).
    (EU, "2MASS J0441+2301 Ab"): Host(_2M0441_A, "bowler_2015"),
    # The 19 MJ primary of the pair Bab, 1800 AU from A (Sect. 1). The row
    # gives that separation, so it stays a companion of A.
    (EU, "2MASS J0441+2301 B"): Host(_2M0441_A, "bowler_2015"),
    # 12.3″, 487 AU from NLTT 31450. The row has the star and the position of
    # NLTT 730, on the other side of the sky.
    (EU, "NLTT 31450 b"): Host(_NLTT_31450, "deacon_2014"),
    # Xuan et al. resolved B into two brown dwarfs, and Thompson et al. give
    # their orbit, 12.1346 d. The rows name the system's primary, GJ 229 A.
    (EU, "GJ 229 Ba"): Host(_GJ_229_B, "thompson_2025"),
    (EU, "GJ 229 Bb"): Host(_GJ_229_B, "xuan_2024"),
    # Gl 417 C orbits B at 2.85 AU in 15.65 yr (Tables 2, 3), the a and P of
    # the row, which names the primary.
    (EU, "HD 97334 C"): Host(_HD_97334_B, "dupuy_2014"),
}

# The archive's "HD 160691 c" and "CD-35 2722 B b".
_MU_ARA_E = (ARCHIVE, "3.11139")
_CD_35_2722_B_B = (ARCHIVE, "3.21067")

JOINS: dict[tuple[str, str], Join] = {
    # The outermost planet. Table 4 calls it e, as these rows do, and refines
    # its period to 3947 ± 23 d. The archive takes that period and calls it c.
    (EU, "mu Ara e"): Join(_MU_ARA_E, "benedict_2022"),
    (OEC, "mu Arae e"): Join(_MU_ARA_E, "benedict_2022"),
    # The row has the preprint's two-satellite fit (169.45 d, 0.743 MJ). The
    # archive has the published one-satellite fit (171.11 d, 0.92 MJ).
    (EU, "CD-35 2722 b I"): Join(_CD_35_2722_B_B, "hoy_2026"),
    # OEC imported these two rows from exoplanet.eu. The rows give the paper's
    # 3.6 AU, 90 yr and 3.7 MJ, and 0.88 AU and 9 MJ, and name no star.
    (EU, "2MASS J1119-1137 b"): Join((OEC, "2MASS J1119-1137 b"), "best_2017"),
    (EU, "MOA-2016-BLG-231 b"): Join((OEC, "MOA-2016-BLG-231 b"), "chung_2019"),
}

STARS: dict[tuple[str, str], Host] = {
    # SIMBAD's TWA 42 is the 2MASS J11193254−1137466 of the title. The short
    # name of the row resolves to no object.
    (OEC, "2MASS J1119-1137"): Host(
        HostStar(
            ("simbad", "oid", "9910123"), "2MASS J1119-1137", 169.88492, -11.63007
        ),
        "best_2017",
    ),
    # The row has the declination with the wrong sign.
    (EU, "2MASS J1315-2649"): Host(
        HostStar(
            ("gaia", "dr3", "6186534394250282752"),
            "2MASS J1315-2649",
            198.87515,
            -26.83235,
        ),
        "burgasser_2011",
    ),
    # The row is 115° from TIC 304339227, the star of the TOI table.
    (EU, "TOI-4629"): Host(
        HostStar(
            ("gaia", "dr3", "6432805482548304384"), "TOI-4629", 275.94309, -68.34495
        ),
        "guerrero_2021",
    ),
}
