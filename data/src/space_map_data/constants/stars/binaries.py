"""Binary orbits and the stars of each pair, read from papers.

An entry is one pair that a point holds unresolved: the binary of a
circumbinary planet host. It is keyed by an id of that point that stays the
same between ingests, as in `literature.py`. Each value is read from the
adopted solution of the paper that REFERENCES names. Values printed only as
e cos ω and e sin ω stay in that form.

A value is a `Value`: errors are positive, and `lower` is None when the
error is symmetric. Times are full Julian dates in the paper's time scale.

The papers do not share their conventions, so each entry records them:
- `epoch_event`: what `epoch` marks.
- `osculating_epoch`: the time at which the elements hold, for a
  photometric-dynamical fit. `mean_longitude` (λ = M + ω) is at that time.
- `frame`: JACOBIAN for the elements of the secondary relative to the
  primary, else NOT_STATED.
- `arg_periastron_of`: whose ω the paper gives, else NOT_STATED.
- `node`: the binary's Ω on the sky. No light curve gives it, so the
  photometric-dynamical fits fix it at 0; that 0 is no value and is left out.

`spectral_type` is what a paper prints for that star, in the form that the
family rules read: "M dwarf" is dM, "main sequence G-type star" is GV. A star
with none has no type in its papers. No type comes from us out of a mass or a
temperature.
"""

import math
from typing import NamedTuple

from space_map_data.constants.stars.literature import Reference, StarKey

# `epoch_event` values.
PERIASTRON = "periastron"
PRIMARY_ECLIPSE = "primary eclipse"
# Conjunction with the barycentre; for a binary, near a primary eclipse.
CONJUNCTION = "conjunction"
NOT_STATED = "not stated"
# `frame` and `arg_periastron_of` values.
JACOBIAN = "jacobian"
PRIMARY = "primary"
SECONDARY = "secondary"
# `axis_unit` values.
AU = "au"
SOLAR_RADIUS = "solar radius"


class Value(NamedTuple):
    value: float
    upper: float | None = None
    lower: float | None = None


class Star(NamedTuple):
    # The component letter: "A" is the primary.
    label: str
    # Solar masses, nominal solar radii, K.
    mass: Value | None
    radius: Value | None
    teff: Value | None
    spectral_type: str | None = None


class Binary(NamedTuple):
    reference: str
    # Days.
    period: Value
    semi_major_axis: Value | None
    axis_unit: str
    eccentricity: Value | None
    # Degrees.
    inclination: Value | None
    arg_periastron: Value | None
    arg_periastron_of: str
    epoch: Value | None
    epoch_event: str
    time_scale: str
    frame: str
    stars: tuple[Star, Star]
    e_cos_omega: Value | None = None
    e_sin_omega: Value | None = None
    osculating_epoch: float | None = None
    mean_longitude: Value | None = None
    node: Value | None = None
    # The work of the stars' spectral types when `reference` prints none.
    type_reference: str | None = None


REFERENCES: dict[str, Reference] = {
    "almeida_2012": Reference(
        "Almeida et al. 2012",
        "A photometric and spectroscopic study of NSVS 14256825: the second"
        " sdOB+dM eclipsing binary (MNRAS 423, 478)",
        "https://doi.org/10.1111/j.1365-2966.2012.20891.x",
    ),
    "baycroft_2025": Reference(
        "Baycroft et al. 2025",
        "BEBOP VII. SOPHIE discovery of BEBOP-3b, a circumbinary giant planet"
        " on an eccentric orbit (MNRAS 541, 2801)",
        "https://doi.org/10.1093/mnras/staf1184",
    ),
    "doyle_2011": Reference(
        "Doyle et al. 2011",
        "Kepler-16: A Transiting Circumbinary Planet (Science 333, 1602)",
        "https://doi.org/10.1126/science.1210923",
    ),
    "esmer_2022": Reference(
        "Esmer et al. 2022",
        "Detection of two additional circumbinary planets around Kepler-451"
        " (MNRAS 511, 5207)",
        "https://doi.org/10.1093/mnras/stac357",
    ),
    "goldberg_2023": Reference(
        "Goldberg et al. 2023",
        "A 5 MJup non-transiting coplanar circumbinary planet around"
        " Kepler-1660AB (MNRAS 525, 4628)",
        "https://doi.org/10.1093/mnras/stad2568",
    ),
    "kostov_2014": Reference(
        "Kostov et al. 2014",
        "Kepler-413b: a slightly misaligned, Neptune-size transiting"
        " circumbinary planet (ApJ 784, 14)",
        "https://doi.org/10.1088/0004-637X/784/1/14",
    ),
    "kostov_2016": Reference(
        "Kostov et al. 2016",
        "Kepler-1647b: the largest and longest-period Kepler transiting"
        " circumbinary planet (ApJ 827, 86)",
        "https://doi.org/10.3847/0004-637X/827/1/86",
    ),
    "kostov_2020": Reference(
        "Kostov et al. 2020",
        "TOI-1338: TESS' First Transiting Circumbinary Planet (AJ 159, 253)",
        "https://doi.org/10.3847/1538-3881/ab8a48",
    ),
    "kostov_2021": Reference(
        "Kostov et al. 2021",
        "TIC 172900988: A Transiting Circumbinary Planet Detected in One"
        " Sector of TESS Data (AJ 162, 234)",
        "https://doi.org/10.3847/1538-3881/ac223a",
    ),
    "lee_2009": Reference(
        "Lee et al. 2009",
        "The sdB+M eclipsing system HW Virginis and its circumbinary planets"
        " (AJ 137, 3181)",
        "https://doi.org/10.1088/0004-6256/137/2/3181",
    ),
    "lehmann_2016": Reference(
        "Lehmann et al. 2016",
        "KIC 7177553: a quadruple system of two close binaries (ApJ 819, 33)",
        "https://doi.org/10.3847/0004-637X/819/1/33",
    ),
    "maxted_2007": Reference(
        "Maxted et al. 2007",
        "The mass and radius of the M-dwarf in the short-period eclipsing"
        " binary RR Caeli (MNRAS 376, 919)",
        "https://doi.org/10.1111/j.1365-2966.2007.11564.x",
    ),
    "orosz_2012": Reference(
        "Orosz et al. 2012",
        "The Neptune-sized circumbinary planet Kepler-38b (ApJ 758, 87)",
        "https://doi.org/10.1088/0004-637X/758/2/87",
    ),
    "orosz_2019": Reference(
        "Orosz et al. 2019",
        "Discovery of a Third Transiting Planet in the Kepler-47 Circumbinary"
        " System (AJ 157, 174)",
        "https://doi.org/10.3847/1538-3881/ab0ca0",
    ),
    "parsons_2010": Reference(
        "Parsons et al. 2010",
        "Precise mass and radius values for the white dwarf and low mass M"
        " dwarf in the pre-cataclysmic binary NN Serpentis (MNRAS 402, 2591)",
        "https://doi.org/10.1111/j.1365-2966.2009.16072.x",
    ),
    "popper_1986": Reference(
        "Popper 1986",
        "Properties of main-sequence eclipsing binaries: into the G stars with"
        " HS Aurigae, FL Lyrae, and EW Orionis (AJ 91, 383)",
        "https://doi.org/10.1086/114018",
    ),
    "schwamb_2013": Reference(
        "Schwamb et al. 2013",
        "Planet Hunters: a transiting circumbinary planet in a quadruple star"
        " system (ApJ 768, 127)",
        "https://doi.org/10.1088/0004-637X/768/2/127",
    ),
    "socia_2020": Reference(
        "Socia et al. 2020",
        "Kepler-1661 b: A Neptune-sized Kepler Transiting Circumbinary Planet"
        " around a Grazing Eclipsing Binary (AJ 159, 94)",
        "https://doi.org/10.3847/1538-3881/ab665b",
    ),
    "triaud_2022": Reference(
        "Triaud et al. 2022",
        "BEBOP III. Observations and an independent mass measurement of Kepler-16"
        " (AB) b, the first circumbinary planet detected with radial velocities"
        " (MNRAS 511, 3561)",
        "https://doi.org/10.1093/mnras/stab3712",
    ),
    "triaud_2025": Reference(
        "Triaud et al. 2025",
        "BEBOP VIII. SOPHIE radial velocities reveal an eccentric, circumbinary"
        " brown dwarf (MNRAS 544, 2180)",
        "https://doi.org/10.1093/mnras/staf1884",
    ),
    "van_den_besselaar_2007": Reference(
        "van den Besselaar et al. 2007",
        "DE Canum Venaticorum: a bright, eclipsing red dwarf-white dwarf"
        " binary (A&A 466, 1031)",
        "https://doi.org/10.1051/0004-6361:20066246",
    ),
    "welsh_2012": Reference(
        "Welsh et al. 2012",
        "Transiting circumbinary planets Kepler-34 b and Kepler-35 b (Nature 481, 475)",
        "https://doi.org/10.1038/nature10768",
    ),
    "welsh_2015": Reference(
        "Welsh et al. 2015",
        "Kepler 453 b: the 10th Kepler transiting circumbinary planet (ApJ 809, 26)",
        "https://doi.org/10.1088/0004-637X/809/1/26",
    ),
}

BINARIES: dict[StarKey, Binary] = {
    # Kepler-16. Table 1 of the published version: medians, with the 15.85%
    # and 84.15% levels as errors. Osculating Jacobian elements at
    # BJD 2,455,212.12316. The paper gives no Teff of B and no types; Triaud et
    # al. 2022 says "a K dwarf" and "a mid M dwarf".
    ("gaia", "dr3", "2133476355197071616"): Binary(
        reference="doyle_2011",
        type_reference="triaud_2022",
        period=Value(41.079220, 0.000078, 0.000077),
        semi_major_axis=Value(0.22431, 0.00035, 0.00034),
        axis_unit=AU,
        eccentricity=Value(0.15944, 0.00061, 0.00062),
        inclination=Value(90.3401, 0.0016, 0.0019),
        arg_periastron=Value(263.464, 0.026, 0.027),
        arg_periastron_of=NOT_STATED,
        epoch=None,
        epoch_event=NOT_STATED,
        time_scale="BJD",
        frame=JACOBIAN,
        stars=(
            Star(
                "A",
                Value(0.6897, 0.0035, 0.0034),
                Value(0.6489, 0.0013),
                Value(4450, 150),
                spectral_type="dK",
            ),
            Star(
                "B",
                Value(0.20255, 0.00066, 0.00065),
                Value(0.22623, 0.00059, 0.00053),
                None,
                spectral_type="dM",
            ),
        ),
        osculating_epoch=2455212.12316,
        mean_longitude=Value(92.3520, 0.0011),
    ),
    # Kepler-34. SI Tables 1 and 2: osculating Jacobian elements, "r1 is the
    # position of Star B relative to Star A". The epoch is the reference
    # time of the primary eclipse.
    ("gaia", "dr3", "2079692678777827712"): Binary(
        reference="welsh_2012",
        period=Value(27.7958103, 0.0000016, 0.0000015),
        semi_major_axis=Value(0.22882, 0.00019, 0.00018),
        axis_unit=AU,
        eccentricity=Value(0.52087, 0.00052, 0.00055),
        inclination=Value(89.8584, 0.0075, 0.0083),
        arg_periastron=None,
        arg_periastron_of=NOT_STATED,
        epoch=Value(2454979.72308, 0.000036),
        epoch_event=PRIMARY_ECLIPSE,
        time_scale="BJD",
        frame=JACOBIAN,
        stars=(
            Star(
                "A",
                Value(1.0479, 0.0033, 0.0030),
                Value(1.1618, 0.0027, 0.0031),
                Value(5913, 130),
            ),
            Star(
                "B",
                Value(1.0208, 0.0022),
                Value(1.0927, 0.0032, 0.0027),
                Value(5867, 130),
            ),
        ),
        e_cos_omega=Value(0.165828, 0.000065, 0.000061),
        e_sin_omega=Value(0.49377, 0.00057, 0.00060),
        osculating_epoch=2454969.20000,
        mean_longitude=Value(300.1970, 0.0099, 0.0105),
    ),
    # Kepler-35. As Kepler-34. The SI text table and the main table differ
    # in some last digits; these are the SI text values.
    ("gaia", "dr3", "2128155371757730816"): Binary(
        reference="welsh_2012",
        period=Value(20.733666, 0.000012),
        semi_major_axis=Value(0.17617, 0.00029, 0.00030),
        axis_unit=AU,
        eccentricity=Value(0.1421, 0.0014, 0.0015),
        inclination=Value(90.4238, 0.0076, 0.0073),
        arg_periastron=None,
        arg_periastron_of=NOT_STATED,
        epoch=Value(2454965.84580, 0.000034),
        epoch_event=PRIMARY_ECLIPSE,
        time_scale="BJD",
        frame=JACOBIAN,
        stars=(
            Star(
                "A",
                Value(0.8877, 0.0051, 0.0053),
                Value(1.0284, 0.0020, 0.0019),
                Value(5606, 150),
            ),
            Star(
                "B",
                Value(0.8094, 0.0042, 0.0045),
                Value(0.7861, 0.0020, 0.0022),
                Value(5202, 100),
            ),
        ),
        e_cos_omega=Value(0.0086413, 0.0000031),
        e_sin_omega=Value(0.1418, 0.0014, 0.0015),
        osculating_epoch=2454965.85000,
        mean_longitude=Value(89.1784, 0.0011, 0.0012),
    ),
    # Kepler-38. Tables 4 to 6, best fit, with the 15.8% and 84.2% levels
    # about the median as errors. Osculating at t0 = BJD 2,454,970. The paper
    # gives Teff of B only as a ratio to A's (Table 7, 0.5896). A's Teff "is
    # roughly what one expects for a spectral type of G4V".
    ("gaia", "dr3", "2105448841733970432"): Binary(
        reference="orosz_2012",
        period=Value(18.79537, 0.000062, 0.000051),
        semi_major_axis=Value(0.1469, 0.0026, 0.0029),
        axis_unit=AU,
        eccentricity=Value(0.1032, 0.0012, 0.0012),
        inclination=Value(89.265, 0.026, 0.025),
        arg_periastron=Value(268.680, 0.037, 0.039),
        arg_periastron_of=NOT_STATED,
        epoch=Value(2454952.872566, 0.000072, 0.000078),
        epoch_event=PRIMARY_ECLIPSE,
        time_scale="BJD",
        frame=NOT_STATED,
        stars=(
            Star(
                "A",
                Value(0.949, 0.055, 0.059),
                Value(1.757, 0.031, 0.034),
                Value(5623, 50),
                spectral_type="G4V",
            ),
            Star(
                "B",
                Value(0.249, 0.009, 0.010),
                Value(0.2724, 0.0049, 0.0053),
                None,
            ),
        ),
        osculating_epoch=2454970.0,
    ),
    # Kepler-47. Tables 5 and 6. Jacobian elements at Tref = BJD 2,454,965.
    # Teff of A is fixed at the value of Orosz et al. 2012; B has only a
    # ratio to it (0.613). B is larger than models, "as is seen in many other M
    # dwarfs".
    ("gaia", "dr3", "2080506523540902912"): Binary(
        reference="orosz_2019",
        period=Value(7.4483648, 0.0000038, 0.0000270),
        semi_major_axis=Value(0.08145, 0.00036, 0.00037),
        axis_unit=AU,
        eccentricity=Value(0.0288, 0.0015, 0.0013),
        inclination=Value(89.613, 0.045, 0.040),
        arg_periastron=Value(226.3, 2.8, 2.6),
        arg_periastron_of=NOT_STATED,
        epoch=Value(2454970.694752, 0.000031, 0.000030),
        epoch_event=CONJUNCTION,
        time_scale="BJD",
        frame=JACOBIAN,
        stars=(
            Star("A", Value(0.957, 0.013, 0.015), Value(0.936, 0.005), Value(5636)),
            Star(
                "B", Value(0.342, 0.003), Value(0.338, 0.002), None, spectral_type="dM"
            ),
        ),
        e_cos_omega=Value(-0.019895, 0.000025, 0.000024),
        e_sin_omega=Value(-0.0208, 0.0019, 0.0020),
        osculating_epoch=2454965.0,
    ),
    # Kepler-64 (PH1), the eclipsing pair Aa+Ab of a quadruple. Tables 7 and
    # 8, the EB-only and EB-fixed columns that the paper prefers. Osculating
    # Jacobian elements at t0 = BJD 2,454,970. Radii and Teff from Sect. 6.
    # Types: "an F dwarf" and "M dwarf".
    ("gaia", "dr3", "2073478823183937536"): Binary(
        reference="schwamb_2013",
        period=Value(20.0002468, 0.0000044),
        semi_major_axis=Value(0.1797, 0.0035),
        axis_unit=AU,
        eccentricity=Value(0.2188, 0.0094),
        inclination=Value(87.592, 0.053),
        arg_periastron=Value(220.1, 2.9, 3.2),
        arg_periastron_of=NOT_STATED,
        epoch=Value(2454967.81797, 0.00016),
        epoch_event=PRIMARY_ECLIPSE,
        time_scale="BJD",
        frame=JACOBIAN,
        stars=(
            Star(
                "Aa",
                Value(1.528, 0.087),
                Value(1.734, 0.044),
                Value(6407, 150),
                spectral_type="dF",
            ),
            Star(
                "Ab",
                Value(0.408, 0.024),
                Value(0.378, 0.023),
                Value(3561, 150),
                spectral_type="dM",
            ),
        ),
        e_cos_omega=Value(-0.16747, 0.00037),
        e_sin_omega=Value(-0.141, 0.015),
        osculating_epoch=2454970.0,
    ),
    # Kepler-413. Tables 3 and 4, best fit, with the 15.8% and 84.2% levels
    # about the median as errors. Jacobian elements at BJD 2,455,014.46543.
    # Teff from Sect. 6; neither has an error. Types: "two K+M stars".
    ("gaia", "dr3", "2133352385261516928"): Binary(
        reference="kostov_2014",
        period=Value(10.1161114, 0.0000099, 0.0000101),
        semi_major_axis=Value(0.10148, 0.00057, 0.00052),
        axis_unit=AU,
        eccentricity=Value(0.0365, 0.0023, 0.0021),
        inclination=Value(87.332, 0.050, 0.060),
        arg_periastron=Value(279.74, 0.62, 0.58),
        arg_periastron_of=NOT_STATED,
        epoch=Value(2455008.34898, 0.00024),
        epoch_event=CONJUNCTION,
        time_scale="BJD",
        frame=JACOBIAN,
        stars=(
            Star(
                "A",
                Value(0.820, 0.015, 0.014),
                Value(0.7761, 0.0088, 0.0096),
                Value(4700),
                spectral_type="K",
            ),
            Star(
                "B",
                Value(0.5423, 0.0081, 0.0073),
                Value(0.484, 0.027, 0.021),
                Value(3460),
                spectral_type="M",
            ),
        ),
        e_cos_omega=Value(0.006169, 0.000038, 0.000037),
        e_sin_omega=Value(-0.0359, 0.0022, 0.0023),
        osculating_epoch=2455014.46543,
    ),
    # Kepler-453. Table 3, best fit, published version. Osculating at
    # Tref = BJD 2,454,964.
    ("gaia", "dr3", "2107434834610481920"): Binary(
        reference="welsh_2015",
        period=Value(27.322037, 0.000017),
        semi_major_axis=Value(0.18539, 0.00066),
        axis_unit=AU,
        eccentricity=Value(0.0524, 0.0037),
        inclination=Value(90.266, 0.052),
        arg_periastron=Value(263.05, 0.48),
        arg_periastron_of=NOT_STATED,
        epoch=Value(2454965.425988, 0.000060),
        epoch_event=CONJUNCTION,
        time_scale="BJD",
        frame=NOT_STATED,
        stars=(
            Star("A", Value(0.944, 0.010), Value(0.833, 0.011), Value(5527, 100)),
            Star("B", Value(0.1951, 0.0020), Value(0.2150, 0.0014), Value(3226, 100)),
        ),
        e_cos_omega=Value(-0.006339, 0.000016),
        e_sin_omega=Value(-0.0520, 0.0037),
        osculating_epoch=2454964.0,
    ),
    # Kepler-1647. Table 4, best fit, Jacobian elements at BJD 2,455,000.
    # Footnote 11: "ω for the primary star is ωbin − π". Teff from Table 2.
    # Types: "of spectral type approximately F8", "secondary (G-type)".
    ("gaia", "dr3", "2073793420945053824"): Binary(
        reference="kostov_2016",
        period=Value(11.2588179, 0.0000013),
        semi_major_axis=Value(0.1276, 0.0002),
        axis_unit=AU,
        eccentricity=Value(0.1602, 0.0004),
        inclination=Value(87.9164, 0.0145),
        arg_periastron=Value(300.5442, 0.0883),
        arg_periastron_of=SECONDARY,
        epoch=Value(2454956.48005, 0.00002),
        epoch_event=CONJUNCTION,
        time_scale="BJD",
        frame=JACOBIAN,
        stars=(
            Star(
                "A",
                Value(1.2207, 0.0112),
                Value(1.7903, 0.0055),
                Value(6210, 100),
                spectral_type="F8",
            ),
            Star(
                "B",
                Value(0.9678, 0.0039),
                Value(0.9663, 0.0057),
                Value(5770, 125),
                spectral_type="G",
            ),
        ),
        osculating_epoch=2455000.0,
    ),
    # Kepler-1661. Table 3, best fit. Osculating at BJD 2,454,960. Types: "a K
    # and M star".
    ("gaia", "dr3", "2104078025612319360"): Binary(
        reference="socia_2020",
        period=Value(28.162539, 0.00005),
        semi_major_axis=Value(0.187, 0.002),
        axis_unit=AU,
        eccentricity=Value(0.112, 0.002),
        inclination=Value(88.76, 0.02),
        arg_periastron=Value(36.4, 1.1),
        arg_periastron_of=NOT_STATED,
        epoch=Value(2454976.71820, 0.00007),
        epoch_event=CONJUNCTION,
        time_scale="BJD",
        frame=NOT_STATED,
        stars=(
            Star(
                "A",
                Value(0.841, 0.022),
                Value(0.762, 0.010),
                Value(5100, 100),
                spectral_type="K",
            ),
            Star(
                "B",
                Value(0.262, 0.005),
                Value(0.276, 0.006),
                Value(3585, 167),
                spectral_type="M",
            ),
        ),
        osculating_epoch=2454960.0,
    ),
    # NN Ser, a white dwarf (A) and an M dwarf. Table 8. P is that of
    # Brinkworth et al. 2006 and Teff of A that of Haefner et al. 2004, as
    # the table cites them. R of B is the volume-averaged radius. The paper
    # gives no epoch, no eccentricity and no Teff of B. Types: DAO1 and M4 ± 0.5
    # in Table 8, "cool M dwarf".
    ("gaia", "dr3", "1191504471436192512"): Binary(
        reference="parsons_2010",
        period=Value(0.13008017141, 0.00000000017),
        semi_major_axis=Value(0.934, 0.009),
        axis_unit=SOLAR_RADIUS,
        eccentricity=None,
        inclination=Value(89.6, 0.2),
        arg_periastron=None,
        arg_periastron_of=NOT_STATED,
        epoch=None,
        epoch_event=NOT_STATED,
        time_scale=NOT_STATED,
        frame=NOT_STATED,
        stars=(
            Star(
                "A",
                Value(0.535, 0.012),
                Value(0.0211, 0.0002),
                Value(57000, 3000),
                spectral_type="DAO1",
            ),
            Star(
                "B", Value(0.111, 0.004), Value(0.149, 0.002), None, spectral_type="dM4"
            ),
        ),
    ),
    # HW Vir, an sdB (A) and an M dwarf. P and T0 from the ephemeris of
    # Table 7 (HJD); i from Table 3, the same in both models; M and R from
    # Table 5. Teff from Table 3, model 1; Teff of A is fixed there. The
    # two models of Table 3 give different a, so a is left out. The
    # eccentricity is "negligible". B is "an M6-7 main sequence star".
    ("gaia", "dr3", "3675067076961979264"): Binary(
        reference="lee_2009",
        period=Value(0.11671959933, 0.00000000055),
        semi_major_axis=None,
        axis_unit=SOLAR_RADIUS,
        eccentricity=None,
        inclination=Value(80.98, 0.10),
        arg_periastron=None,
        arg_periastron_of=NOT_STATED,
        epoch=Value(2445730.557123, 0.000025),
        epoch_event=NOT_STATED,
        time_scale="HJD",
        frame=NOT_STATED,
        stars=(
            Star(
                "A",
                Value(0.485, 0.013),
                Value(0.183, 0.026),
                Value(28488, 208),
                spectral_type="sdB",
            ),
            Star(
                "B",
                Value(0.142, 0.004),
                Value(0.175, 0.026),
                Value(3084, 272),
                spectral_type="M6-7V",
            ),
        ),
    ),
    # RR Cae, a white dwarf (A) and an M dwarf. The linear ephemeris of
    # primary minima (Sect. 3.1) and Table 3. The orbit is fitted as
    # circular. The paper gives the radii and the mass of B as ranges over
    # the inclination, and no single i; these are left out. B is "an M4 dwarf".
    ("gaia", "dr3", "4788741548375134336"): Binary(
        reference="maxted_2007",
        period=Value(0.3037036366, 0.0000000047),
        semi_major_axis=None,
        axis_unit=SOLAR_RADIUS,
        eccentricity=Value(0.0),
        inclination=None,
        arg_periastron=None,
        arg_periastron_of=NOT_STATED,
        epoch=Value(2451523.048567, 0.000019),
        epoch_event=PRIMARY_ECLIPSE,
        time_scale="BJD_TDB",
        frame=NOT_STATED,
        stars=(
            Star("A", Value(0.440, 0.023), None, Value(7540, 175), spectral_type="WD"),
            Star("B", None, None, Value(3100, 100), spectral_type="dM4"),
        ),
    ),
    # NSVS 14256825, an sdOB (A) and an M dwarf. The ephemeris of primary
    # minima (Eq. 1, TDB) and Table 6, model 2, which the paper prefers.
    # The orbit is circular. Types: "an sdOB star", and sdOB+dM in the title.
    ("gaia", "dr3", "4245906369913936000"): Binary(
        reference="almeida_2012",
        period=Value(0.110374230, 0.000000002),
        semi_major_axis=Value(0.80, 0.04),
        axis_unit=SOLAR_RADIUS,
        eccentricity=Value(0.0),
        inclination=Value(82.5, 0.3),
        arg_periastron=None,
        arg_periastron_of=NOT_STATED,
        epoch=Value(2454274.2087, 0.0001),
        epoch_event=PRIMARY_ECLIPSE,
        time_scale="BJD_TDB",
        frame=NOT_STATED,
        stars=(
            Star(
                "A",
                Value(0.419, 0.070),
                Value(0.188, 0.010),
                Value(42000, 400),
                spectral_type="sdOB",
            ),
            Star(
                "B",
                Value(0.109, 0.023),
                Value(0.162, 0.008),
                Value(2550, 500),
                spectral_type="dM",
            ),
        ),
    ),
    # DE CVn, a white dwarf (A) and an M dwarf. The ephemeris of primary
    # eclipses (Eq. 1) and Sect. 4.1: most likely values with 68% ranges.
    # The orbit is taken as circular. The paper gives no Teff of B in K. Types:
    # "DA-type" and "a spectral type of M3V".
    ("gaia", "dr3", "1550299304833675392"): Binary(
        reference="van_den_besselaar_2007",
        period=Value(0.3641394, 0.0000002),
        semi_major_axis=Value(2.07, 0.09, 0.04),
        axis_unit=SOLAR_RADIUS,
        eccentricity=Value(0.0),
        inclination=Value(86, 3, 2),
        arg_periastron=None,
        arg_periastron_of=NOT_STATED,
        epoch=Value(2452784.5533, 0.0001),
        epoch_event=PRIMARY_ECLIPSE,
        time_scale="HJD",
        frame=NOT_STATED,
        stars=(
            Star(
                "A",
                Value(0.51, 0.06, 0.02),
                Value(0.0136, 0.0008, 0.0002),
                Value(8000, 1000),
                spectral_type="DA",
            ),
            Star(
                "B",
                Value(0.41, 0.06),
                Value(0.37, 0.06, 0.007),
                None,
                spectral_type="M3V",
            ),
        ),
    ),
    # KIC 7177553, the eclipsing pair S1,2 of a quadruple. Table 3. The
    # epoch is the time of periastron. The point has no Gaia, HIP or HD id
    # in the registry, so the key is its exoplanet.eu host. Types: "all
    # components of the two systems are main sequence G-type stars".
    ("exoplanet-eu", "catalog", "KIC 7177553 (AB)"): Binary(
        reference="lehmann_2016",
        period=Value(17.996467, 0.000017),
        semi_major_axis=Value(36.76, 0.15),
        axis_unit=SOLAR_RADIUS,
        eccentricity=Value(0.3915, 0.0010),
        inclination=Value(87.679, 0.055),
        arg_periastron=Value(3.298, 0.061),
        arg_periastron_of=NOT_STATED,
        epoch=Value(2455690.213, 0.012),
        epoch_event=PERIASTRON,
        time_scale="BJD",
        frame=NOT_STATED,
        stars=(
            Star(
                "A",
                Value(1.043, 0.014),
                Value(0.940, 0.005),
                Value(5800, 130),
                spectral_type="GV",
            ),
            Star(
                "B",
                Value(0.986, 0.015),
                Value(0.941, 0.005),
                Value(5740, 140),
                spectral_type="GV",
            ),
        ),
    ),
    # FL Lyr. Tables VII, IX (solution 4) and XVII. The orbit is taken as
    # circular. The paper gives a sin i, not a, and log Teff, not Teff.
    # Kozyreva et al. 2015 is not used: its Kepler elements are only a
    # template for eclipse timing, with no errors, masses, a or Teff. Types:
    # F8 + G8 (Table XVII), of "main-sequence eclipsing binaries".
    ("gaia", "dr3", "2130371574879626112"): Binary(
        reference="popper_1986",
        period=Value(2.1781542, 0.0000003),
        semi_major_axis=None,
        axis_unit=SOLAR_RADIUS,
        eccentricity=Value(0.0),
        inclination=Value(86.3, 0.4),
        arg_periastron=None,
        arg_periastron_of=NOT_STATED,
        epoch=Value(2445143.7256, 0.0003),
        epoch_event=PRIMARY_ECLIPSE,
        time_scale="JD",
        frame=NOT_STATED,
        stars=(
            Star(
                "A", Value(1.218, 0.016), Value(1.283, 0.030), None, spectral_type="F8V"
            ),
            Star(
                "B", Value(0.958, 0.011), Value(0.963, 0.030), None, spectral_type="G8V"
            ),
        ),
    ),
    # TOI-1338 (BEBOP-1). Tables 3 and 4, the posterior medians that the
    # paper adopts. Jacobian elements at BJD 2,455,186. The paper gives Teff
    # of B only as a ratio to A's (0.5516). B is "the M dwarf secondary".
    ("gaia", "dr3", "5494443978353833088"): Binary(
        reference="kostov_2020",
        period=Value(14.608559, 0.000013, 0.000012),
        semi_major_axis=Value(0.1321, 0.0024, 0.0025),
        axis_unit=AU,
        eccentricity=Value(0.15603, 0.00015),
        inclination=Value(89.696, 0.178, 0.114),
        arg_periastron=Value(117.554, 0.072, 0.074),
        arg_periastron_of=NOT_STATED,
        epoch=Value(2458336.8242, 0.0025, 0.0023),
        epoch_event=CONJUNCTION,
        time_scale="BJD",
        frame=JACOBIAN,
        stars=(
            Star(
                "A",
                Value(1.127, 0.068, 0.069),
                Value(1.331, 0.024, 0.026),
                Value(6040.8, 98.1, 91.5),
            ),
            Star(
                "B",
                Value(0.3128, 0.0113, 0.0118),
                Value(0.3089, 0.0056, 0.0060),
                None,
                spectral_type="dM",
            ),
        ),
        osculating_epoch=2455186.0,
    ),
    # TIC 172900988 (BEBOP-2). Tables 3, 5 and 6, family 5. The paper keeps
    # six families of solutions and adopts none; family 5 is "formally the
    # best". Jacobian elements at BJD 2,453,250. Types: "a late-F and early-G
    # main sequence star", "approximately F9 and G0".
    ("gaia", "dr3", "709709093301608448"): Binary(
        reference="kostov_2021",
        period=Value(19.658173, 0.000025),
        semi_major_axis=Value(0.191915, 0.000034),
        axis_unit=AU,
        eccentricity=Value(0.44790, 0.00017),
        inclination=Value(90.5762, 0.0047),
        arg_periastron=Value(69.605, 0.011),
        arg_periastron_of=NOT_STATED,
        epoch=Value(2458878.3835, 0.0072),
        epoch_event=CONJUNCTION,
        time_scale="BJD",
        frame=JACOBIAN,
        stars=(
            Star(
                "A",
                Value(1.2384, 0.0007),
                Value(1.3842, 0.0016),
                Value(6050, 100),
                spectral_type="F9V",
            ),
            Star(
                "B",
                Value(1.2019, 0.0007),
                Value(1.3124, 0.0012),
                Value(5983, 100),
                spectral_type="G0V",
            ),
        ),
        osculating_epoch=2453250.0,
    ),
    # BEBOP-3. Tables 1 and 2. ω is the primary's about the barycentre, in
    # rad in the paper. The paper gives a about the barycentre only (0.0234853
    # and 0.09728 AU). Masses from the HRCCS column, which the paper adopts;
    # radii from the RV + photometry column. No Teff of B. A "has a F9 spectral
    # classification".
    ("gaia", "dr3", "1141769093744241536"): Binary(
        reference="baycroft_2025",
        period=Value(13.2176657, 0.0000027),
        semi_major_axis=None,
        axis_unit=AU,
        eccentricity=Value(0.063255, 0.000054),
        inclination=Value(88.7488, 0.0092),
        arg_periastron=Value(
            math.degrees(4.90226), math.degrees(0.00097), math.degrees(0.00090)
        ),
        arg_periastron_of=PRIMARY,
        epoch=Value(2459756.1098, 0.0021, 0.0019),
        epoch_event=PERIASTRON,
        time_scale="BJD",
        frame=NOT_STATED,
        stars=(
            Star(
                "A",
                Value(1.083, 0.026),
                Value(1.414, 0.017),
                Value(6033, 100),
                spectral_type="F9",
            ),
            Star("B", Value(0.2615, 0.0039), Value(0.2811, 0.0033), None),
        ),
    ),
    # BEBOP-4. Table 1, mean elements. ω is the primary's about the
    # barycentre, in rad in the paper. The paper assumes i, gives a about the
    # barycentre only (0.099063 and 0.325 AU), and gives no radii and no Teff.
    # Its type G3 is that of the system, so neither star takes it.
    ("gaia", "dr3", "3961485079994112896"): Binary(
        reference="triaud_2025",
        period=Value(71.96857, 0.00015),
        semi_major_axis=None,
        axis_unit=AU,
        eccentricity=Value(0.26887, 0.00011),
        inclination=None,
        arg_periastron=Value(
            math.degrees(4.81629), math.degrees(0.00049), math.degrees(0.00051)
        ),
        arg_periastron_of=PRIMARY,
        epoch=Value(2459724.6183, 0.0049, 0.0056),
        epoch_event=PERIASTRON,
        time_scale="BJD",
        frame=NOT_STATED,
        stars=(
            Star("A", Value(1.507, 0.152), None, None),
            Star("B", Value(0.459, 0.028), None, None),
        ),
    ),
    # Kepler-1660. Table 2, median column; the paper does not say which
    # column it adopts. Elements of the secondary relative to the primary,
    # osculating at BJD 2,454,900. Radii from Table 1 and Teff from Sect. 2.4,
    # both from an isochrone fit. The arXiv copy is the version before
    # acceptance.
    ("gaia", "dr3", "2101127864119148160"): Binary(
        reference="goldberg_2023",
        period=Value(18.610869, 0.000031),
        semi_major_axis=None,
        axis_unit=AU,
        eccentricity=Value(0.4973, 0.0172),
        inclination=Value(84.399, 0.766),
        arg_periastron=Value(109.09, 1.79),
        arg_periastron_of=NOT_STATED,
        epoch=Value(2454966.861694, 0.000302),
        epoch_event=CONJUNCTION,
        time_scale="BJD",
        frame=JACOBIAN,
        stars=(
            Star("A", Value(1.1450, 0.0728), Value(1.491, 0.072), Value(6050, 40)),
            Star("B", Value(1.0980, 0.0644), Value(1.299, 0.061), Value(6040, 30)),
        ),
        osculating_epoch=2454900.0,
    ),
    # Kepler-451, an sdB (A) and an M dwarf. The ephemeris of Table 3 (from
    # primary minima) and Table 2, the PHOEBE Legacy column, which has the
    # errors. The masses, a and Teff of A are fixed from Østensen et al. 2010.
    # Baran et al. 2015 is not used: it fits only P and T0, and takes i from
    # Østensen et al. 2010. The orbit is circular. Types: "an sdB + dM eclipsing
    # binary".
    ("gaia", "dr3", "2080063931448749824"): Binary(
        reference="esmer_2022",
        period=Value(0.125765285, 0.000000001),
        semi_major_axis=Value(0.891),
        axis_unit=SOLAR_RADIUS,
        eccentricity=Value(0.0),
        inclination=Value(69.92, 0.03),
        arg_periastron=None,
        arg_periastron_of=NOT_STATED,
        epoch=Value(2454953.643182, 0.000004),
        epoch_event=PRIMARY_ECLIPSE,
        time_scale="BJD_TDB",
        frame=NOT_STATED,
        stars=(
            Star(
                "A", Value(0.48), Value(0.203, 0.001), Value(29564), spectral_type="sdB"
            ),
            Star(
                "B",
                Value(0.12),
                Value(0.168, 0.001),
                Value(2829, 1),
                spectral_type="dM",
            ),
        ),
    ),
}
