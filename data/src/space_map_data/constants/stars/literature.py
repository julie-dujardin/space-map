"""Star values read from papers, for stars that no catalogue here places.

An entry is keyed by an id of the star that stays the same between ingests:
its Gaia DR3 id, else its HIP number, else its HD number. Our own IDs can
change, so they are not keys. Each value cites one work of REFERENCES by its
key. The ingest gives the values to their column group as the source
`literature`, first in the order of that group. The star's object entry cites
the work beside the value.
"""

from typing import NamedTuple

# (catalogue, release, catalogue id), as in the cross-ids of the registry.
type StarKey = tuple[str, str, str]


class Reference(NamedTuple):
    # Authors and year, as the star page names the work.
    short: str
    title: str
    url: str


class Distance(NamedTuple):
    # pc.
    value: float
    lower: float
    upper: float
    # A value of `distance_method`.
    method: str
    reference: str
    lower_percentile: float | None = None
    upper_percentile: float | None = None


REFERENCES: dict[str, Reference] = {
    "haucke_2018": Reference(
        "Haucke et al. 2018",
        "Wind properties of variable B supergiants. Evidence of pulsations"
        " connected with mass-loss episodes (A&A 614, A91)",
        "https://doi.org/10.1051/0004-6361/201731678",
    ),
    "kuhn_2021": Reference(
        "Kuhn et al. 2021",
        "A high pitch angle structure in the Sagittarius Arm (A&A 651, L10)",
        "https://doi.org/10.1051/0004-6361/202141198",
    ),
    "oplistilova_2025": Reference(
        "Oplištilová et al. 2025",
        "VLTI observations of Orion Belt stars. I. ε Orionis (A&A 704, A204)",
        "https://doi.org/10.1051/0004-6361/202556154",
    ),
    "smith_2006": Reference(
        "Smith 2006",
        "The Structure of the Homunculus. I. Shape and Latitude Dependence from"
        " H2 and [Fe II] Velocity Maps of η Carinae (ApJ 644, 1151)",
        "https://doi.org/10.1086/503766",
    ),
    "tuthill_2008": Reference(
        "Tuthill et al. 2008",
        "The Prototype Colliding-Wind Pinwheel WR 104 (ApJ 675, 698)",
        "https://doi.org/10.1086/527286",
    ),
}

DISTANCES: dict[StarKey, Distance] = {
    # η Car. The H2 shape of the Homunculus and its age of 160 yr give
    # 2350 ± 50 pc (Sect. 4.1).
    ("gaia", "dr3", "5350358584482202880"): Distance(
        2350, 2300, 2400, "expansion", "smith_2006"
    ),
    # Alnilam (ε Ori). Gaia saturates on it; the paper takes the median
    # distance of Orion OB1b from Gaia DR3, 384 ± 8 pc (Sect. 2.5, Table 5),
    # and also tries 350 and 420 pc.
    ("hip", "2007", "26311"): Distance(
        384, 376, 392, "association", "oplistilova_2025"
    ),
    # Polis (μ Sgr). Gaia DR3 gives it no parallax. It is a member of Sgr OB1
    # (Humphreys 1978, Table 8), whose core M8 is at 1.22 kpc from Gaia EDR3
    # (Table D.1, 95% interval).
    ("gaia", "dr3", "4093933487636355968"): Distance(
        1220,
        1200,
        1230,
        "association",
        "kuhn_2021",
        lower_percentile=2.5,
        upper_percentile=97.5,
    ),
    # Aludra (η CMa). No work measures its distance; the paper adopts the
    # Hipparcos parallax of 1.64 ± 0.40 mas, under 5σ, as 609 ± 148 pc
    # (Table 2).
    ("gaia", "dr3", "5605797194566011520"): Distance(
        609, 461, 757, "parallax", "haucke_2018"
    ),
    # WR 104. Gaia flags its parallax as spurious. The dust spiral expands at
    # 0.28 mas/day at the wind's terminal speed of 1220 km/s, which gives
    # 2.6 ± 0.7 kpc; the error is mostly that of the wind speed (Sect. 3).
    ("gaia", "dr3", "4069167258796371712"): Distance(
        2600, 1900, 3300, "expansion", "tuthill_2008"
    ),
}
