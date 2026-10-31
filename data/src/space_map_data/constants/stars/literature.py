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
    "argyle_2015": Reference(
        "Argyle, Alzner & van Leeuwen 2015",
        "Micrometric measures and orbits of southern visual double stars (AN 336, 378)",
        "https://doi.org/10.1002/asna.201412166",
    ),
    "bartkevicius_2002": Reference(
        "Bartkevičius & Gudas 2002",
        "Kinematics of Hipparcos visual binaries. II. Stars with ground-based"
        " orbital solutions (Baltic Astron. 11, 153)",
        # Crossref and SIMBAD know no DOI for this volume.
        "https://ui.adsabs.harvard.edu/abs/2002BaltA..11..153B",
    ),
    # CC BY-NC 3.0 IGO.
    "gaia_dr2_2018": Reference(
        "Gaia Collaboration 2018",
        "Gaia DR2 (CDS I/345, 2018yCat.1345....0G)",
        "https://doi.org/10.26093/cds/vizier.1345",
    ),
    "haucke_2018": Reference(
        "Haucke et al. 2018",
        "Wind properties of variable B supergiants. Evidence of pulsations"
        " connected with mass-loss episodes (A&A 614, A91)",
        "https://doi.org/10.1051/0004-6361/201731678",
    ),
    "hernandez_2005": Reference(
        "Hernández et al. 2005",
        "Herbig Ae/Be stars in nearby OB associations (AJ 129, 856)",
        "https://doi.org/10.1086/426918",
    ),
    "kaltcheva_makarov_2007": Reference(
        "Kaltcheva & Makarov 2007",
        "The structure and the distance of Collinder 121 from Hipparcos and"
        " photometry: resolving the discrepancy (ApJ 667, L155)",
        "https://doi.org/10.1086/522495",
    ),
    "kuhn_2021": Reference(
        "Kuhn et al. 2021",
        "A high pitch angle structure in the Sagittarius Arm (A&A 651, L10)",
        "https://doi.org/10.1051/0004-6361/202141198",
    ),
    "menshchikov_2002": Reference(
        "Men'shchikov et al. 2002",
        "Properties of the close binary and circumbinary torus of the Red"
        " Rectangle (A&A 393, 867)",
        "https://doi.org/10.1051/0004-6361:20020859",
    ),
    "oplistilova_2025": Reference(
        "Oplištilová et al. 2025",
        "VLTI observations of Orion Belt stars. I. ε Orionis (A&A 704, A204)",
        "https://doi.org/10.1051/0004-6361/202556154",
    ),
    "ortiz_leon_2018": Reference(
        "Ortiz-León et al. 2018",
        "Gaia-DR2 confirms VLBA parallaxes in Ophiuchus, Serpens, and Aquila"
        " (ApJ 869, L33)",
        "https://doi.org/10.3847/2041-8213/aaf6ad",
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
    # β Phe. Gaia and Hipparcos 2007 give the pair no good parallax; a Hipparcos
    # re-reduction with the orbital motion gives 17.93 ± 0.53 mas (Table 3).
    ("hip", "2007", "5165"): Distance(55.77, 54.17, 57.47, "parallax", "argyle_2015"),
    # τ2 Cap. The only parallax over 5σ is the dynamical one, 3.72 ± 0.62 mas
    # (CDS J/BaltA/11/153, table 2, code DYN).
    ("hip", "2007", "101923"): Distance(
        268.8, 230.4, 322.6, "dynamical", "bartkevicius_2002"
    ),
    # HD 51925. The photometric uvbyβ distance of Kaltcheva 2000 (MNRAS 318,
    # 1023), repeated in Table 1 with a maximum error of 20%.
    ("hip", "2007", "33532"): Distance(
        539, 431, 647, "photometric", "kaltcheva_makarov_2007"
    ),
    # HD 33546. A candidate member of Ori OB1a, at 335 ± 13 pc from Hipparcos
    # (Table 1).
    ("hip", "2007", "24127"): Distance(335, 322, 348, "association", "hernandez_2005"),
    # Flying Saucer. A region value: L1688, where the disk lies, is at
    # 138.4 ± 2.6 pc.
    ("gaia", "dr3", "6049103961995537664"): Distance(
        138.4, 135.8, 141.0, "association", "ortiz_leon_2018"
    ),
    # Red Rectangle. The model of the SED and the reddening gives D ≈ 710 pc,
    # ±10% (Table 1).
    ("hip", "2007", "30089"): Distance(710, 640, 780, "model", "menshchikov_2002"),
    # HD 184268. Gaia DR2 source 6768305615921978240 gives 2.4971 ± 0.072 mas.
    ("hip", "2007", "96274"): Distance(
        400.5, 389.2, 412.4, "parallax", "gaia_dr2_2018"
    ),
}
