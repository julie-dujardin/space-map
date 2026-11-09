"""Star values read from papers, where no catalogue here gives them well.

An entry is keyed by an id of the star that stays the same between ingests:
its Gaia DR3 id, else its HIP number, else its HD number, else its SIMBAD
oid. Our own IDs can change, so they are not keys. Each value cites one work
of REFERENCES by its key. The ingest gives the values to their column group
as the source `literature`, first in the order of that group. The star's
object entry cites the work beside the value. The white dwarfs of O'Brien et
al. 2024 join TEFFS, LOGGS and MASSES from their download
(`extrasolar/sources/literature.measured_tables`).
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
    method: str | None
    reference: str
    lower_percentile: float | None = None
    upper_percentile: float | None = None


class Radius(NamedTuple):
    # Nominal solar radii.
    value: float
    reference: str


class Measured(NamedTuple):
    """A value with its 1σ error, None where the paper gives none."""

    value: float
    error: float | None
    reference: str


class Bounds(NamedTuple):
    """A value with the lower and upper bound that the paper prints."""

    value: float
    lower: float
    upper: float
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
    "bond_2015": Reference(
        "Bond et al. 2015",
        "Hubble Space Telescope astrometry of the Procyon system (ApJ 813, 106)",
        "https://doi.org/10.1088/0004-637X/813/2/106",
    ),
    # CC BY 4.0.
    "obrien_2024": Reference(
        "O'Brien et al. 2024",
        "The 40 pc sample of white dwarfs from Gaia (MNRAS 527, 8687)",
        "https://doi.org/10.1093/mnras/stad3773",
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
    "bond_2017": Reference(
        "Bond et al. 2017",
        "The Sirius System and its Astrophysical Puzzles: Hubble Space Telescope"
        " and Ground-Based Astrometry (ApJ 840, 70)",
        "https://doi.org/10.3847/1538-4357/aa6af8",
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
    "maiz_apellaniz_2022": Reference(
        "Maíz Apellániz et al. 2022",
        "The Villafranca catalog of Galactic OB groups. II. From Gaia DR2 to EDR3"
        " and ten new systems with O stars (A&A 657, A131)",
        "https://doi.org/10.1051/0004-6361/202142364",
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
    "allende_prieto_lambert_1999": Reference(
        "Allende Prieto & Lambert 1999",
        "Fundamental parameters of nearby stars from the comparison with"
        " evolutionary calculations: masses, radii and effective temperatures"
        " (A&A 352, 555)",
        # The work has no DOI.
        "https://ui.adsabs.harvard.edu/abs/1999A%26A...352..555A",
    ),
    "baines_2018": Reference(
        "Baines et al. 2018",
        "Fundamental parameters of 87 stars from the Navy Precision Optical"
        " Interferometer (AJ 155, 30)",
        "https://doi.org/10.3847/1538-3881/aa9d8b",
    ),
    "bouchaud_2020": Reference(
        "Bouchaud et al. 2020",
        "A realistic two-dimensional model of Altair (A&A 633, A78)",
        "https://doi.org/10.1051/0004-6361/201936830",
    ),
    "cotton_2022": Reference(
        "Cotton et al. 2022",
        "Polarimetric detection of non-radial oscillation modes in the β Cephei"
        " star β Crucis (Nature Astronomy 6, 154)",
        "https://doi.org/10.1038/s41550-021-01531-9",
    ),
    "david_hillenbrand_2015": Reference(
        "David & Hillenbrand 2015",
        "The ages of early-type stars: Strömgren photometric methods calibrated,"
        " validated, tested, and applied to hosts and prospective hosts of"
        " directly imaged exoplanets (ApJ 804, 146)",
        "https://doi.org/10.1088/0004-637X/804/2/146",
    ),
    "domiciano_de_souza_2021": Reference(
        "Domiciano de Souza et al. 2021",
        "Refined fundamental parameters of Canopus from combined near-IR"
        " interferometry and spectral energy distribution (A&A 654, A19)",
        "https://doi.org/10.1051/0004-6361/202140478",
    ),
    "gardner_2021": Reference(
        "Gardner et al. 2021",
        "Establishing α Oph as a prototype rotator: precision orbit with new"
        " Keck, CHARA, and RV observations (ApJ 921, 41)",
        "https://doi.org/10.3847/1538-4357/ac1172",
    ),
    "howarth_van_leeuwen_2019": Reference(
        "Howarth & van Leeuwen 2019",
        "The distance, rotation, and physical parameters of ζ Pup (MNRAS 484, 5350)",
        "https://doi.org/10.1093/mnras/stz291",
    ),
    "joyce_2020": Reference(
        "Joyce et al. 2020",
        "Standing on the shoulders of giants: new mass and distance estimates for"
        " Betelgeuse through combined evolutionary, asteroseismic, and"
        " hydrodynamic simulations with MESA (ApJ 902, 63)",
        "https://doi.org/10.3847/1538-4357/abb8db",
    ),
    "kervella_2022": Reference(
        "Kervella et al. 2022",
        "The binary system of the spinning-top Be star Achernar (A&A 667, A111)",
        "https://doi.org/10.1051/0004-6361/202244009",
    ),
    "kervella_arenou_thevenin_2022": Reference(
        "Kervella, Arenou & Thévenin 2022",
        "Stellar and substellar companions from Gaia EDR3. Proper-motion anomaly"
        " and resolved common proper-motion pairs (A&A 657, A7)",
        "https://doi.org/10.1051/0004-6361/202142146",
    ),
    "luck_2015": Reference(
        "Luck 2015",
        "Abundances in the local region. I. G and K giants (AJ 150, 88)",
        "https://doi.org/10.1088/0004-6256/150/3/88",
    ),
    "mazumdar_2006": Reference(
        "Mazumdar et al. 2006",
        "An asteroseismic study of the β Cephei star β Canis Majoris (A&A 459, 589)",
        "https://doi.org/10.1051/0004-6361:20064980",
    ),
    "monnier_2012": Reference(
        "Monnier et al. 2012",
        "Resolving Vega and the inclination controversy with CHARA/MIRC (ApJL 761, L3)",
        "https://doi.org/10.1088/2041-8205/761/1/L3",
    ),
    "morel_2001": Reference(
        "Morel et al. 2001",
        "The ζ Herculis binary system revisited. Calibration and seismology"
        " (A&A 379, 245)",
        "https://doi.org/10.1051/0004-6361:20011336",
    ),
    "north_2007": Reference(
        "North et al. 2007",
        "γ2 Velorum: orbital solution and fundamental parameter determination"
        " with SUSI (MNRAS 377, 415)",
        "https://doi.org/10.1111/j.1365-2966.2007.11608.x",
    ),
    "ohnaka_2013": Reference(
        "Ohnaka et al. 2013",
        "High spectral resolution imaging of the dynamical atmosphere of the red"
        " supergiant Antares in the CO first overtone lines with VLTI/AMBER"
        " (A&A 555, A24)",
        "https://doi.org/10.1051/0004-6361/201321063",
    ),
    "ramirez_allende_prieto_2011": Reference(
        "Ramírez & Allende Prieto 2011",
        "Fundamental parameters and chemical composition of Arcturus (ApJ 743, 135)",
        "https://doi.org/10.1088/0004-637X/743/2/135",
    ),
    "schiller_przybilla_2008": Reference(
        "Schiller & Przybilla 2008",
        "Quantitative spectroscopy of Deneb (A&A 479, 849)",
        "https://doi.org/10.1051/0004-6361:20078590",
    ),
    "soubiran_2024": Reference(
        "Soubiran et al. 2024",
        "Gaia FGK benchmark stars: fundamental Teff and log g of the third"
        " version (A&A 682, A145)",
        "https://doi.org/10.1051/0004-6361/202347136",
    ),
    "southworth_2007": Reference(
        "Southworth, Bruntt & Buzasi 2007",
        "Eclipsing binaries observed with the WIRE satellite. II. β Aurigae and"
        " non-linear limb darkening in light curves (A&A 467, 1215)",
        "https://doi.org/10.1051/0004-6361:20077184",
    ),
    "stock_2018": Reference(
        "Stock et al. 2018",
        "Precise radial velocities of giant stars. X. Bayesian stellar parameters"
        " and evolutionary stages for 372 giant stars from the Lick planet-search"
        " program (A&A 616, A33)",
        "https://doi.org/10.1051/0004-6361/201833111",
    ),
    "tango_2006": Reference(
        "Tango et al. 2006",
        "Orbital elements, masses and distance of λ Scorpii A and B determined"
        " with the Sydney University Stellar Interferometer and high-resolution"
        " spectroscopy (MNRAS 370, 884)",
        "https://doi.org/10.1111/j.1365-2966.2006.10526.x",
    ),
    "tetzlaff_2011": Reference(
        "Tetzlaff, Neuhäuser & Hohle 2011",
        "A catalogue of young runaway Hipparcos stars within 3 kpc from the Sun"
        " (MNRAS 410, 190)",
        "https://doi.org/10.1111/j.1365-2966.2010.17434.x",
    ),
    "tkachenko_2016": Reference(
        "Tkachenko et al. 2016",
        "Stellar modelling of Spica, a high-mass spectroscopic binary with a"
        " β Cep variable primary component (MNRAS 458, 1964)",
        "https://doi.org/10.1093/mnras/stw255",
    ),
    "tomkin_popper_1986": Reference(
        "Tomkin & Popper 1986",
        "Rediscussion of eclipsing binaries. XV. Alpha Coronae Borealis, a"
        " main-sequence system with components of types A and G (AJ 91, 1428)",
        "https://doi.org/10.1086/114121",
    ),
}

SIRIUS_B: StarKey = ("gaia", "dr3", "2947050466531873024")
# No Gaia, HIP or HD id holds Procyon B alone.
PROCYON_B: StarKey = ("simbad", "oid", "988144")

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
    # Sirius A, and B through their shared distance. Gaia cannot measure A;
    # B's parallax, 374.49 ± 0.23 mas at a RUWE of 2.4, would outweigh A's
    # though it sits 3σ under the 378.9 ± 1.4 mas that the paper's masses
    # take, the weighted mean of the ground-based and Hipparcos parallaxes
    # (Table 5).
    ("hip", "2007", "32349"): Distance(2.6392, 2.6295, 2.6490, "parallax", "bond_2017"),
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
    # 15 Mon A. Its Hipparcos parallax, 3.55 ± 0.50 mas, is 2.5 times that of
    # the north core of NGC 2264, which holds it: 701 pc from Gaia EDR3
    # (Table A.2, Villafranca O-016 N; Fig. 6 shows 15 Mon Aa,Ab and B as
    # members).
    ("gaia", "dr3", "3326740865570982400"): Distance(
        701, 696, 707, "association", "maiz_apellaniz_2022"
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
    # Sirius B, from its absolute flux (Sect. 8).
    SIRIUS_B: Radius(0.008098, "bond_2017"),
    # Procyon B. Provencal et al. 2002's radius at the paper's parallax (Sect. 8).
    PROCYON_B: Radius(0.01232, "bond_2015"),
}

# Teff (K), log g (cgs) and mass (M☉) of white dwarfs, which Gaia does not
# fit. A paper on the one star comes before the 40 pc sample.
TEFFS: dict[StarKey, Measured] = {
    # The fit to the HST STIS spectra (Sect. 8).
    SIRIUS_B: Measured(25369, 46, "bond_2017"),
    # The fit of Provencal et al. 2002, which the paper takes (Sect. 8).
    PROCYON_B: Measured(7740, 50, "bond_2015"),
}
LOGGS: dict[StarKey, Measured] = {
    # The fit to the spectra that gives its Teff (Sect. 8).
    SIRIUS_B: Measured(8.591, 0.016, "bond_2017"),
    # From the dynamical mass and the radius: the star has no Balmer lines
    # (Sect. 8).
    PROCYON_B: Measured(8.028, 0.023, "bond_2015"),
}
# Masses (M☉) of the white dwarfs above, and of bright stars that Gaia FLAME
# saturates on and that no other catalogue here gives a mass. Each value keeps
# the spread that the paper or its online table prints. A symmetric 1σ error
# is a Measured. Printed bounds, an asymmetric error and a range are a Bounds.
# A range goes in as its middle. A point that holds an unresolved pair takes the mass
# of its primary.
MASSES: dict[StarKey, Measured | Bounds] = {
    # Dynamical masses.
    SIRIUS_B: Measured(1.018, 0.011, "bond_2017"),
    PROCYON_B: Measured(0.592, 0.006, "bond_2015"),
    # Hassaleh.
    ("gaia", "dr3", "160886283751041408"): Bounds(5.23, 4.13, 5.44, "stock_2018"),
    # Schedar.
    ("gaia", "dr3", "418551920284673408"): Bounds(4.1, 3.65, 4.23, "stock_2018"),
    ("gaia", "dr3", "423018377034969216"): Measured(2.02, 0.03, "baines_2018"),  # Caph
    # Ruchbah.
    ("gaia", "dr3", "510204838759030144"): Bounds(
        2.06, 1.8, 2.2, "david_hillenbrand_2015"
    ),
    # Phecda.
    ("gaia", "dr3", "792588939773693568"): Bounds(
        2.27, 2.1, 2.4, "david_hillenbrand_2015"
    ),
    # Merak.
    ("gaia", "dr3", "856096765753549056"): Bounds(
        2.38, 2.2, 2.5, "david_hillenbrand_2015"
    ),
    # Alphecca.
    ("gaia", "dr3", "1222646935698492160"): Measured(2.58, 0.045, "tomkin_popper_1986"),
    # Muphrid.
    ("gaia", "dr3", "1244946371540479616"): Measured(1.559, 0.072, "soubiran_2024"),
    # Kornephoros.
    ("gaia", "dr3", "1297565458994346240"): Measured(2.91, 0.11, "baines_2018"),
    ("gaia", "dr3", "1312665361415345920"): Measured(1.45, 0.01, "morel_2001"),  # ζ Her
    # Rastaban.
    ("gaia", "dr3", "1415230383034813824"): Measured(6.3, 0.6, "tetzlaff_2011"),
    # Alkaid.
    ("gaia", "dr3", "1510374147844219904"): Bounds(
        5.65, 5.2, 6.0, "david_hillenbrand_2015"
    ),
    # Alioth.
    ("gaia", "dr3", "1576683529448755328"): Bounds(
        2.21, 2.1, 2.3, "david_hillenbrand_2015"
    ),
    ("gaia", "dr3", "2067518817314952576"): Measured(12, 0.1, "tetzlaff_2011"),  # Sadr
    # Alderamin.
    ("gaia", "dr3", "2193192137376175488"): Bounds(
        1.78, 1.6, 1.9, "david_hillenbrand_2015"
    ),
    # Markab.
    ("gaia", "dr3", "2816504901198512768"): Bounds(
        2.48, 2.3, 2.6, "david_hillenbrand_2015"
    ),
    # Phact.
    ("gaia", "dr3", "2900546759663847168"): Bounds(
        3.32, 3.2, 3.4, "david_hillenbrand_2015"
    ),
    # Nihal.
    ("gaia", "dr3", "2968097043228517120"): Measured(
        3.34, 0.17, "kervella_arenou_thevenin_2022"
    ),
    # Arneb.
    ("gaia", "dr3", "2971266110612490624"): Measured(12.2, 0.1, "tetzlaff_2011"),
    # Saiph.
    ("gaia", "dr3", "3011968416163350272"): Measured(15.5, 0.8, "tetzlaff_2011"),
    # Cursa.
    ("gaia", "dr3", "3211922645854328832"): Bounds(
        1.8, 1.7, 1.9, "david_hillenbrand_2015"
    ),
    ("gaia", "dr3", "3501215734352781440"): Measured(2.73, None, "luck_2015"),  # Kraz
    # Zosma.
    ("gaia", "dr3", "3990320597065899776"): Bounds(
        1.96, 1.8, 2.0, "david_hillenbrand_2015"
    ),
    # Kaus Media.
    ("gaia", "dr3", "4049506483413484672"): Measured(3.21, None, "luck_2015"),
    # Kaus Borealis.
    ("gaia", "dr3", "4076915349846977664"): Bounds(0.93, 0.85, 1.01, "stock_2018"),
    # UY Sct, the middle of the 7–10 that its place in the HR diagram gives.
    ("gaia", "dr3", "4152993273702130432"): Bounds(8.5, 7, 10, "arroyo_torres_2013"),
    # Tarazed.
    ("gaia", "dr3", "4302054339959905920"): Measured(3.51, 0.23, "baines_2018"),
    # ζ Oph.
    ("gaia", "dr3", "4337352305320149760"): Measured(19.8, 0.1, "tetzlaff_2011"),
    # Yed Prior.
    ("gaia", "dr3", "4357027756659697664"): Measured(
        1.59, 0.08, "kervella_arenou_thevenin_2022"
    ),
    # Unukalhai.
    ("gaia", "dr3", "4429785739602747392"): Measured(1.61, 0.12, "baines_2018"),
    # Cebalrai. Soubiran et al. 2024 give this giant two masses that differ twofold.
    ("gaia", "dr3", "4473334474604992384"): Measured(1.44, 0.16, "baines_2018"),
    # Rasalhague.
    ("gaia", "dr3", "4493746564376875520"): Measured(2.20, 0.06, "gardner_2021"),
    # β Hyi.
    ("gaia", "dr3", "4683897617110115200"): Measured(1.086, 0.036, "soubiran_2024"),
    # Ankaa.
    ("gaia", "dr3", "4993479684438433792"): Measured(
        2.79, 0.14, "kervella_arenou_thevenin_2022"
    ),
    # θ Car.
    ("gaia", "dr3", "5239828735016184448"): Measured(14.9, 0.4, "tetzlaff_2011"),
    # Aspidiske.
    ("gaia", "dr3", "5300300156538723328"): Measured(7.9, 0.2, "tetzlaff_2011"),
    # Markeb.
    ("gaia", "dr3", "5310393535853560576"): Measured(12.5, 0.4, "tetzlaff_2011"),
    # μ Vel.
    ("gaia", "dr3", "5361403934691772160"): Measured(
        1.51, 0.30, "kervella_arenou_thevenin_2022"
    ),
    # Naos.
    ("gaia", "dr3", "5534788672055388032"): Measured(
        25.3, 5.3, "howarth_van_leeuwen_2019"
    ),
    # π Pup.
    ("gaia", "dr3", "5589311357728452608"): Measured(11.7, 0.2, "tetzlaff_2011"),
    # Aludra.
    ("gaia", "dr3", "5605797194566011520"): Measured(19.2, 0.1, "tetzlaff_2011"),
    # Uridim.
    ("gaia", "dr3", "5905821894507108864"): Measured(10.1, 1.0, "tetzlaff_2011"),
    # κ Sco.
    ("gaia", "dr3", "5961206940987571200"): Measured(10.1, 0.1, "tetzlaff_2011"),
    # Larawag.
    ("gaia", "dr3", "6026152137856166912"): Measured(1.31, None, "luck_2015"),
    # Imai.
    ("gaia", "dr3", "6071060144089351808"): Measured(8.9, 0.1, "tetzlaff_2011"),
    # γ Cen.
    ("gaia", "dr3", "6127791439360208640"): Bounds(
        2.14, 2.0, 2.2, "david_hillenbrand_2015"
    ),
    # Kulou.
    ("gaia", "dr3", "6165699748417797504"): Bounds(
        2.14, 2.0, 2.2, "david_hillenbrand_2015"
    ),
    # Zubeneschamali.
    ("gaia", "dr3", "6319542659461082752"): Bounds(
        3.29, 3.1, 3.4, "david_hillenbrand_2015"
    ),
    # Alnair.
    ("gaia", "dr3", "6560604777055249536"): Bounds(
        3.8, 3.6, 4.0, "david_hillenbrand_2015"
    ),
    # Ascella.
    ("gaia", "dr3", "6760703042771435136"): Bounds(
        2.18, 2.0, 2.3, "david_hillenbrand_2015"
    ),
    # Alpheratz.
    ("hip", "2007", "677"): Bounds(3.62, 3.4, 3.8, "david_hillenbrand_2015"),
    ("hip", "2007", "3419"): Bounds(2.86, 2.73, 3.07, "stock_2018"),  # Diphda
    ("hip", "2007", "7588"): Measured(6.0, 0.6, "kervella_2022"),  # Achernar
    # Sheratan.
    ("hip", "2007", "8903"): Bounds(1.84, 1.7, 1.9, "david_hillenbrand_2015"),
    ("hip", "2007", "14135"): Measured(1.465, 0.109, "soubiran_2024"),  # Menkar
    ("hip", "2007", "15863"): Measured(7.5, 0.4, "tetzlaff_2011"),  # Mirfak
    ("hip", "2007", "25336"): Measured(8.6, 0.3, "tetzlaff_2011"),  # Bellatrix
    # Elnath.
    ("hip", "2007", "25428"): Bounds(3.48, 3.3, 3.6, "david_hillenbrand_2015"),
    ("hip", "2007", "26311"): Measured(28.4, 2.0, "oplistilova_2025"),  # Alnilam
    # Betelgeuse, the middle of its present-day 16.5–19.
    ("hip", "2007", "27989"): Bounds(17.8, 16.5, 19, "joyce_2020"),
    ("hip", "2007", "28360"): Measured(2.376, 0.027, "southworth_2007"),  # Menkalinan
    # Mahasim.
    ("hip", "2007", "28380"): Bounds(2.79, 2.6, 3.0, "david_hillenbrand_2015"),
    ("hip", "2007", "30324"): Measured(13.5, 0.5, "mazumdar_2006"),  # Mirzam
    # Canopus.
    ("hip", "2007", "30438"): Measured(9.64, 1.42, "domiciano_de_souza_2021"),
    # Alhena.
    ("hip", "2007", "31681"): Bounds(2.21, 2.0, 2.4, "david_hillenbrand_2015"),
    ("hip", "2007", "33579"): Measured(10.1, 1.0, "tetzlaff_2011"),  # Adhara
    ("hip", "2007", "34444"): Measured(12, 0.2, "tetzlaff_2011"),  # Wezen
    ("hip", "2007", "37279"): Measured(1.478, 0.012, "bond_2015"),  # Procyon
    # γ2 Vel. The point holds both stars, and the value is the O star's.
    ("hip", "2007", "39953"): Measured(28.5, 1.1, "north_2007"),
    ("hip", "2007", "41037"): Measured(9, 0.9, "tetzlaff_2011"),  # Avior
    ("hip", "2007", "44816"): Measured(8.5, 0.3, "tetzlaff_2011"),  # Suhail
    # Miaplacidus. The table rounds its error to 0.00.
    ("hip", "2007", "45238"): Measured(2.96, None, "allende_prieto_lambert_1999"),
    ("hip", "2007", "46390"): Bounds(2.4, 2.29, 2.63, "stock_2018"),  # Alphard
    ("hip", "2007", "50583"): Measured(1.63, None, "luck_2015"),  # Algieba
    # Denebola.
    ("hip", "2007", "57632"): Bounds(2.02, 1.9, 2.1, "david_hillenbrand_2015"),
    # Gienah.
    ("hip", "2007", "59803"): Bounds(2.91, 2.8, 3.0, "david_hillenbrand_2015"),
    ("hip", "2007", "62434"): Measured(14.5, 0.5, "cotton_2022"),  # Mimosa
    ("hip", "2007", "65474"): Measured(11.43, 1.15, "tkachenko_2016"),  # Spica
    ("hip", "2007", "66657"): Measured(11.7, 0.3, "tetzlaff_2011"),  # ε Cen
    ("hip", "2007", "68002"): Measured(7.8, 0.1, "tetzlaff_2011"),  # Leepwal
    # Menkent.
    ("hip", "2007", "68933"): Measured(1.48, 0.60, "allende_prieto_lambert_1999"),
    # Arcturus.
    ("hip", "2007", "69673"): Measured(1.08, 0.06, "ramirez_allende_prieto_2011"),
    ("hip", "2007", "71352"): Measured(12, 0.3, "tetzlaff_2011"),  # η Cen
    ("hip", "2007", "78401"): Measured(19.7, 0.1, "tetzlaff_2011"),  # Dschubba
    # Antares, the middle of its current 11–14.3.
    ("hip", "2007", "80763"): Bounds(12.7, 11, 14.3, "ohnaka_2013"),
    ("hip", "2007", "82273"): Measured(2.33, None, "luck_2015"),  # Atria
    # Sabik.
    ("hip", "2007", "84012"): Bounds(1.97, 1.9, 2.1, "david_hillenbrand_2015"),
    ("hip", "2007", "85696"): Measured(11.4, 0.5, "tetzlaff_2011"),  # Lesath
    ("hip", "2007", "85927"): Measured(10.4, 1.3, "tango_2006"),  # Shaula
    # Sargas.
    ("hip", "2007", "86228"): Measured(4.63, 0.01, "allende_prieto_lambert_1999"),
    ("hip", "2007", "87833"): Measured(1.791, 0.098, "soubiran_2024"),  # Eltanin
    # Kaus Australis.
    ("hip", "2007", "90185"): Measured(3.47, 0.06, "allende_prieto_lambert_1999"),
    # Vega, 2.15 +0.10 −0.15.
    ("hip", "2007", "91262"): Bounds(2.15, 2.00, 2.25, "monnier_2012"),
    # Nunki.
    ("hip", "2007", "92855"): Bounds(6.37, 6.0, 6.6, "david_hillenbrand_2015"),
    ("hip", "2007", "97649"): Measured(1.86, 0.03, "bouchaud_2020"),  # Altair
    # Peacock.
    ("hip", "2007", "100751"): Bounds(5.42, 5.1, 5.6, "david_hillenbrand_2015"),
    ("hip", "2007", "102098"): Measured(19, 4, "schiller_przybilla_2008"),  # Deneb
    ("hip", "2007", "107315"): Bounds(7.2, 7.00, 7.72, "stock_2018"),  # Enif
}
