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


class Radius(NamedTuple):
    # Nominal solar radii.
    value: float
    reference: str


REFERENCES: dict[str, Reference] = {
    "argyle_2015": Reference(
        "Argyle, Alzner & van Leeuwen 2015",
        "Micrometric measures and orbits of southern visual double stars (AN 336, 378)",
        "https://doi.org/10.1002/asna.201412166",
    ),
    "aerts_2010": Reference(
        "Aerts et al. 2010",
        "Periodic mass-loss episodes due to an oscillation mode with variable"
        " amplitude in the hot supergiant HD 50064 (A&A 517)",
        "https://doi.org/10.1051/0004-6361/201014124",
    ),
    "arroyo_torres_2013": Reference(
        "Arroyo-Torres et al. 2013",
        "The atmospheric structure and fundamental parameters of the red"
        " supergiants AH Sco, UY Sct, and KW Sgr (A&A 554, A76)",
        "https://doi.org/10.1051/0004-6361/201220920",
    ),
    "baron_2012": Reference(
        "Baron et al. 2012",
        "Imaging the Algol triple system in the H band with the CHARA"
        " interferometer (ApJ 752, 20)",
        "https://doi.org/10.1088/0004-637X/752/1/20",
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
    "chesneau_2014": Reference(
        "Chesneau et al. 2014",
        "The yellow hypergiant HR 5171 A: resolving a massive interacting binary"
        " in the common envelope phase (A&A 563, A71)",
        "https://doi.org/10.1051/0004-6361/201322421",
    ),
    "clark_2012": Reference(
        "Clark et al. 2012",
        "On the nature of the galactic early-B hypergiants (A&A 541, A145)",
        "https://doi.org/10.1051/0004-6361/201117472",
    ),
    "groh_2009": Reference(
        "Groh et al. 2009",
        "Bona-fide, strong-variable Galactic luminous blue variable stars are"
        " fast rotators: detection of a high rotational velocity in HR Carinae"
        " (ApJ 705, L25)",
        "https://doi.org/10.1088/0004-637X/705/1/L25",
    ),
    "kasikov_2026": Reference(
        "Kasikov et al. 2026",
        "Painting a family portrait of the yellow super- and hypergiants in the"
        " Milky Way. I. Constraining the distances and luminosities (A&A 708)",
        "https://doi.org/10.1051/0004-6361/202558527",
    ),
    "levesque_2005": Reference(
        "Levesque et al. 2005",
        "The effective temperature scale of Galactic red supergiants: cool, but"
        " not as cool as we thought (ApJ 628, 973)",
        "https://doi.org/10.1086/430901",
    ),
    "mehner_2017": Reference(
        "Mehner et al. 2017",
        "Spectroscopic and photometric oscillatory envelope variability during"
        " the S Doradus outburst of the Luminous Blue Variable R71 (A&A 608, A124)",
        "https://doi.org/10.1051/0004-6361/201731829",
    ),
    "ritchie_2009": Reference(
        "Ritchie et al. 2009",
        "Spectroscopic monitoring of the Luminous Blue Variable Westerlund1-243"
        " from 2002 to 2009 (A&A 507, 1597)",
        "https://doi.org/10.1051/0004-6361/200912986",
    ),
    "wittkowski_2012": Reference(
        "Wittkowski et al. 2012",
        "Fundamental properties and atmospheric structure of the red supergiant"
        " VY Canis Majoris based on VLTI/AMBER spectro-interferometry (A&A 540, L12)",
        "https://doi.org/10.1051/0004-6361/201219126",
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

# For the listed stars that JMDC cannot size: a dust shell at 8 µm for VY CMa,
# the three stars at once for Algol, and for the others no distance to take a
# diameter to: neither Hipparcos nor Gaia has a 5σ parallax of these supergiants.
RADII: dict[StarKey, Radius] = {
    # Algol A.
    ("hd", "1949", "19356"): Radius(2.73, "baron_2012"),
    ("hd", "1949", "62058"): Radius(245, "kasikov_2026"),  # R Pup
    # HR Car, at minimum, at the photosphere at 5 kpc.
    ("hd", "1949", "90177"): Radius(75, "groh_2009"),
    ("hd", "1949", "96918"): Radius(616, "kasikov_2026"),  # V382 Car
    ("hd", "1949", "100261"): Radius(403, "kasikov_2026"),  # o1 Cen
    ("hd", "1949", "101947"): Radius(222, "kasikov_2026"),  # V810 Cen
    # HR 5171 A, the whole of its contact binary's larger star.
    ("hd", "1949", "119796"): Radius(1315, "chesneau_2014"),
    ("hd", "1949", "152236"): Radius(103, "clark_2012"),  # ζ1 Sco, at 1.64 kpc.
    ("hd", "1949", "179821"): Radius(264, "kasikov_2026"),  # V1427 Aql
    ("hd", "1949", "212466"): Radius(902, "kasikov_2026"),  # RW Cep
    ("hd", "1949", "217476"): Radius(449, "kasikov_2026"),  # V509 Cas
    ("hd", "1949", "58061"): Radius(1420, "wittkowski_2012"),
    # From its luminosity and Teff at the distance of Cep OB2.
    ("hd", "1949", "206936"): Radius(1420, "levesque_2005"),
    # Anugu et al. 2024's diameter of 2.09 mas at the paper's own distance.
    ("hd", "1949", "224014"): Radius(628, "kasikov_2026"),
    # R71, quiescent, at the photosphere.
    ("hd", "1949", "269006"): Radius(107, "mehner_2017"),
    ("hd", "1949", "316496"): Radius(1009, "arroyo_torres_2013"),  # KW Sgr
    ("gaia", "dr3", "2067782734461462912"): Radius(246, "clark_2012"),  # Cyg OB2 #12
    # HD 50064, not in Hipparcos. Rough, from its Hα profile.
    ("gaia", "dr3", "3113547759973829120"): Radius(200, "aerts_2010"),
    ("gaia", "dr3", "2200195820289135104"): Radius(1520, "levesque_2005"),  # V354 Cep
    ("gaia", "dr3", "4152993273702130432"): Radius(
        1708, "arroyo_torres_2013"
    ),  # UY Sct
    # Westerlund 1-243, at the photosphere at 4.5 kpc.
    ("gaia", "dr3", "5940105830990286208"): Radius(450, "ritchie_2009"),
    ("gaia", "dr3", "6054569565614460800"): Radius(70, "clark_2012"),  # BP Cru
}
