"""What the fit reads from a star's Point source row, and the star's tier.

`choose` gives the Teff, L, V and A_V of each row. The fit and the star panel
(`surface`) both take them, so the two show the same values. A planet host
takes the exoplanet catalogue's Teff first, because the catalogue derives the
values of its planets from it. A planet host is a row with the host-star
group: the catalogues give it only to the star that their planets orbit.
Every other star takes a paper's Teff (`literature`), else GSP-Phot's. A
point of two or more stars takes the catalogue's Teff only. L is first
FLAME's on the GSP-Phot parameters, then on the GSP-Spec ones. The
metallicity is that of `metallicity.choose`. A width is half the published
16th to 84th percentile range, or the published 1σ error in dex. A Teff or L
with no width counts as none. A paper value with no error has no width. The
catalogue's Teff has no published width, so its width is 0.

Gaia saturates on the brightest stars, so other routes follow, best first:
- Teff: a spectroscopic or XP Teff that holds for the star's kind, then a
  Teff from B − V (`photometry`);
- L: from a measured radius and the Teff, from the radius that a paper's mass
  and log g give and the Teff, then from V, the distance and a bolometric
  correction.
`teff_source` and `luminosity_source` name the route of each star. The kind
takes the measured colour only (`render.photometric_bp_rp`), never one from a
Teff, as the Teff choice depends on the kind. The relations of the star kinds
and the Gaia models do not hold for a compact star (`families.compact`, which
`with_compact` adds as COMPACT). So it has a kind of its own
(`metallicity.COMPACT`) that no relation takes, and its Teff and L come from
a paper or the exoplanet catalogue only.

The tier says how far the result can be trusted:
- 1: a single FGK or M dwarf, its distance known to 10%, its metallicity
  from a spectrum. Single means a RUWE under MAX_RUWE and no Gaia
  non-single-star solution;
- 2: a star that is single or of unknown multiplicity (no RUWE, as for a
  Hipparcos star), its distance known to 25%, its metallicity from a
  spectrum or from Gaia XP;
- 3: every other star, with solar metallicity assumed where it has none from
  a spectrum or XP. GSP-Phot's [M/H] counts as none: its paper calls it
  biased.
A Teff from B − V or an L from a bolometric correction keeps a star out of
tier 1. GSP-Phot's Teff and FLAME's L correct for extinction, and these two
routes do not. So they ignore it for a star within NEAR_PC or brighter than
NAKED_EYE_V in the panel's V (`apparent_v`), where it is small, and else take
A_V from GSP-Phot. A star on one of these routes with no A_V is tier 3.
A star that renders at a suspect parallax (`placement` step 6) is tier 3,
because its Gaia solution can be spurious.
A point that holds two or more stars (its System row) has no row, curated or
fitted. Its light is that of two stars, and the scene gives it no radius. A
compact star and a young stellar object have no row too. These are the
EXCLUDED points. A star with no kind and a star whose distance is unknown or
worse than 50% have no tier. The distance error is that of the distance that
the star renders at (`placement`).
"""

from dataclasses import dataclass

import numpy as np
import pyarrow as pa
import pyarrow.compute as pc

from space_map_data.constants.planets.families import (
    SOLAR_RADIUS_KM,
    SUN_GM_KM3_S2,
)
from space_map_data.export.extrasolar import render
from space_map_data.extrasolar import families, placement
from space_map_data.extrasolar.interiors import metallicity, photometry
from space_map_data.extrasolar.measured_radius import MEASURED_COLUMNS, measured_radius
from space_map_data.extrasolar.sources.literature import LITERATURE
from space_map_data.utils.arrays import floats

NO_TIER = -1
GOOD_DISTANCE, FAIR_DISTANCE, MAX_DISTANCE = 0.1, 0.25, 0.5
MAX_RUWE = 1.4
YSO_TYPES = frozenset({"Y*O", "Y*?", "TT*", "TT?", "Ae*", "Ae?", "Or*", "pr*", "pr?"})
SPECTRA = frozenset(
    {
        metallicity.PASTEL,
        metallicity.APOGEE,
        metallicity.XHIP,
        metallicity.GSPSPEC,
        metallicity.LAMOST,
    }
)
# The `feh_source` of a star with no metallicity from a spectrum or XP. Its
# [Fe/H] is solar, with SOLAR_SIGMA as its width.
ASSUMED_SOLAR = "assumed-solar"
SOLAR_SIGMA = 0.25

# The values of `teff_source` and `luminosity_source`.
PAPER = LITERATURE.name
GSPPHOT = metallicity.GSPPHOT
HOST = "host-star"
APOGEE = metallicity.APOGEE
LAMOST = metallicity.LAMOST
ESPHS = "gaia-dr3-esphs"
XP = metallicity.XP
FLAME = "gaia-dr3-flame"
FLAME_SPEC = "gaia-dr3-flame-spec"
RADIUS = "radius"
MASS_GRAVITY = "mass-gravity"
BOLOMETRIC = "bolometric-correction"
FROM_COLOUR = frozenset({photometry.CASAGRANDE_2010, photometry.FLOWER_1996})

# Fouesneau et al. 2023 find ESP-HS's Teff off the literature by about 300 K
# for A stars and 500 to 2000 K for B stars. This width in dex is about 7%.
ESPHS_SIGMA = 0.03
# The precision of the XP Teff (Andrae et al. 2023), K.
XP_TEFF_SIGMA = 50.0
# Flower 1996 gives no scatter. These are the rms of the relation within
# NEAR_PC (dex): against APOGEE DR17 for 163 giants, and against ESP-HS for
# 96 hot stars.
FLOWER_SIGMA = 0.012
FLOWER_HOT_SIGMA = 0.043
# The column that `with_binary_points` adds, and the System columns it reads.
BINARY_POINT = "binary_point"
SYSTEM_COLUMNS = ("id", "point")
# The column that `with_compact` adds.
COMPACT = "compact"
# The Metadata columns of the classes that the family masks read.
CLASS_COLUMNS = ("id", "class")
# The measured Johnson V columns, best first, and the column of each one's
# source. The panel and the BC luminosity take one order.
MEASURED_V = (
    ("v_mag", "hipparcos_photometry_source"),
    ("simbad_v_mag", "simbad_photometry_source"),
)
# Extinction is small within this distance (pc) or above this V.
NEAR_PC = 100.0
NAKED_EYE_V = 6.0
# The sources of A_V besides GSP-Phot. NEGLIGIBLE is small, UNKNOWN is taken as 0.
NEGLIGIBLE = "negligible"
UNKNOWN = "unknown"
# GSP-Phot's A0, at 541.4 nm, stands for A_V. E(B − V) = A_V / R_V.
R_V = 3.1
# A star with wider inputs (dex) has no row. Fitted again at these widths, a
# quarter of the naked-eye stars with narrow inputs move by over 0.1 dex in
# mass, and their median mass range doubles.
MAX_SIGMA_LOG_TEFF = 0.1
MAX_SIGMA_LOG_L = 0.4
# The `out` of a point that has no Interior row of any kind.
BINARY = "binary point"
COMPACT_STAR = "compact star"
YOUNG = "young stellar object"
EXCLUDED = (BINARY, COMPACT_STAR, YOUNG)

COLUMNS = tuple(
    dict.fromkeys(
        (
            "id",
            *placement.COLUMNS,
            *placement.ERROR_COLUMNS,
            *render.MAG_COLUMNS,
            *metallicity.COLUMNS,
            *families.COLUMNS,
            *MEASURED_COLUMNS,
            "v_i",
            "b_v_error",
            "teff_literature",
            "teff_literature_error",
            "logg_literature",
            "logg_literature_error",
            "mass_literature",
            "mass_literature_lower",
            "mass_literature_upper",
            "teff_gspphot",
            "teff_gspphot_lower",
            "teff_gspphot_upper",
            "azero_gspphot",
            "host_teff",
            "teff_apogee",
            "teff_apogee_error",
            "teff_lamost",
            "teff_lamost_error",
            "teff_esphs",
            "teff_xgboost",
            "host_v_mag",
            "hipparcos_photometry_source",
            "simbad_photometry_source",
            "host_star_source",
            *(
                f"lum_flame{run}{bound}"
                for run in ("", "_spec")
                for bound in ("", "_lower", "_upper")
            ),
            "ruwe",
            "non_single_star",
            "simbad_otype",
            "spicy_id",
        )
    )
)


# A source's name, its values (K or L☉) and their widths (dex).
type Found = tuple[str, np.ndarray, np.ndarray]


def _log_width(table: pa.Table, low: str, high: str) -> np.ndarray:
    with np.errstate(invalid="ignore", divide="ignore"):
        return (np.log10(floats(table, high)) - np.log10(floats(table, low))) / 2


def _dex(value: np.ndarray, error: np.ndarray | float) -> np.ndarray:
    with np.errstate(invalid="ignore", divide="ignore"):
        return error / (value * np.log(10))


def _first(*sources: Found) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """The first positive value with a width of each row, with its width and
    source."""
    names = np.array([*(name for name, _, _ in sources), None], object)
    with np.errstate(invalid="ignore"):
        value, width, index = metallicity.first(
            *(
                (
                    np.where((found > 0) & np.isfinite(its_width), found, np.nan),
                    its_width,
                )
                for _, found, its_width in sources
            )
        )
    return value, width, names[index]


def with_binary_points(table: pa.Table, systems: pa.Table | None) -> pa.Table:
    """`table` with BINARY_POINT: True for a point that holds two or more
    stars. `systems` holds the SYSTEM_COLUMNS of System rows."""
    points = (
        np.zeros(0, np.int64)
        if systems is None
        else systems.filter(pc.fill_null(systems["point"], False))["id"].to_numpy()
    )
    return table.append_column(
        BINARY_POINT, pa.array(np.isin(table["id"].to_numpy(), points))
    )


def with_compact(table: pa.Table, masks: np.ndarray) -> pa.Table:
    """`table` with COMPACT, the `families.compact` test of each row.
    `masks` holds the published and estimated families of each row."""
    return table.append_column(COMPACT, pa.array(families.compact(masks)))


def absolute_g(table: pa.Table, distance_pc: np.ndarray) -> np.ndarray:
    """Absolute G at the render distance, with no extinction, as `absoluteG`
    in `record.ts` rounds it."""
    mag = render.magnitudes(table)[0]
    with np.errstate(invalid="ignore", divide="ignore"):
        absolute = mag - 5 * np.log10(distance_pc) + 5
    return np.round(absolute / render.MAG_STEP) * render.MAG_STEP


def v_mag(table: pa.Table) -> np.ndarray:
    """The first measured Johnson V of each row (MEASURED_V)."""
    v = np.full(table.num_rows, np.nan)
    for column, _ in MEASURED_V:
        v = np.where(np.isnan(v), floats(table, column), v)
    return v


def apparent_v(table: pa.Table) -> tuple[np.ndarray, np.ndarray]:
    """Johnson V of each row and its source, None where there is none: the
    first of MEASURED_V and the exoplanet catalogue's V, credited to the
    source of the row's group, else V from Gaia G and BP − RP."""
    bp_rp = floats(table, "phot_bp_mean_mag") - floats(table, "phot_rp_mean_mag")
    v = np.full(table.num_rows, np.nan)
    source = np.full(table.num_rows, None, object)
    for column, source_column in (*MEASURED_V, ("host_v_mag", "host_star_source")):
        values = floats(table, column)
        at = np.isnan(v) & np.isfinite(values)
        v[at] = values[at]
        source[at] = table[source_column].to_numpy(zero_copy_only=False)[at]
    gaia = photometry.v_from_gaia(floats(table, "phot_g_mean_mag"), bp_rp)
    at = np.isnan(v) & np.isfinite(gaia)
    v[at] = gaia[at]
    source[at] = photometry.RIELLO_2021
    return v, source


def extinction(
    table: pa.Table, distance_pc: np.ndarray, v: np.ndarray, binary: np.ndarray
) -> tuple[np.ndarray, np.ndarray]:
    """A_V (mag) of each row of V `v`, and its source. GSP-Phot's A0 is a
    one-star fit, so it does not hold for a point of two or more stars
    (`binary`)."""
    small = (distance_pc <= NEAR_PC) | (v <= NAKED_EYE_V)
    a0 = np.where(binary, np.nan, floats(table, "azero_gspphot"))
    known = small | np.isfinite(a0)
    source = np.select([small, known], [NEGLIGIBLE, GSPPHOT], UNKNOWN)
    return np.where(small | ~known, 0.0, a0), source


def _measured_teff(table: pa.Table, kind: np.ndarray) -> list[Found]:
    """The spectroscopic and XP Teffs, each where it holds for the star's
    kind. APOGEE and XP are not for hot stars, LAMOST holds M dwarfs only and
    ESP-HS hot stars only."""
    cool = np.isin(
        kind, [metallicity.FGK_DWARF, metallicity.GIANT, metallicity.M_DWARF]
    )
    m_dwarf = kind == metallicity.M_DWARF
    hot = kind == metallicity.OBA
    apogee, lamost = floats(table, "teff_apogee"), floats(table, "teff_lamost")
    esphs = floats(table, "teff_esphs")
    xp = np.where(metallicity.xp_holds(table), floats(table, "teff_xgboost"), np.nan)
    return [
        (
            APOGEE,
            np.where(cool, apogee, np.nan),
            _dex(apogee, floats(table, "teff_apogee_error")),
        ),
        (
            LAMOST,
            np.where(m_dwarf, lamost, np.nan),
            _dex(lamost, floats(table, "teff_lamost_error")),
        ),
        (ESPHS, np.where(hot, esphs, np.nan), np.full(esphs.size, ESPHS_SIGMA)),
        (XP, np.where(cool, xp, np.nan), _dex(xp, XP_TEFF_SIGMA)),
    ]


def b_v(table: pa.Table) -> tuple[np.ndarray, np.ndarray]:
    """B − V from Hipparcos, else from SIMBAD, and its error (0 for none)."""
    hipparcos = floats(table, "b_v")
    simbad = floats(table, "simbad_b_mag") - floats(table, "simbad_v_mag")
    error = np.where(np.isfinite(hipparcos), floats(table, "b_v_error"), 0.0)
    return np.where(np.isfinite(hipparcos), hipparcos, simbad), np.nan_to_num(error)


def _colour_teff(
    table: pa.Table, kind: np.ndarray, feh: np.ndarray, a_v: np.ndarray
) -> list[Found]:
    """Teff from the dereddened B − V: Casagrande for an FGK dwarf, Flower
    for an FGK dwarf outside Casagrande's range, a giant or a hot star. An M
    dwarf has none: B − V barely changes over the M types."""
    colour_, error = b_v(table)
    colour_ = colour_ - a_v / R_V
    fgk = kind == metallicity.FGK_DWARF
    flower = fgk | np.isin(kind, [metallicity.GIANT, metallicity.OBA])
    casagrande = np.where(fgk, photometry.casagrande_log_teff(colour_, feh), np.nan)
    casagrande_width = np.hypot(
        _dex(10**casagrande, photometry.CASAGRANDE_SIGMA),
        photometry.slope(photometry.casagrande_log_teff, colour_, feh) * error,
    )
    by_flower = np.where(flower, photometry.flower_log_teff(colour_), np.nan)
    flower_width = np.hypot(
        np.where(kind == metallicity.OBA, FLOWER_HOT_SIGMA, FLOWER_SIGMA),
        photometry.slope(photometry.flower_log_teff, colour_) * error,
    )
    return [
        (photometry.CASAGRANDE_2010, 10**casagrande, casagrande_width),
        (photometry.FLOWER_1996, 10**by_flower, flower_width),
    ]


def _radius_luminosity(
    table: pa.Table, log_teff: np.ndarray, sigma_log_teff: np.ndarray
) -> Found:
    """L from a measured radius and the Teff: not from a star's `radius`,
    whose other sources are model radii."""
    radius, _ = measured_radius(table)
    log_l = photometry.log_l_from_radius(radius, log_teff)
    return RADIUS, 10**log_l, 4 * sigma_log_teff


def _gravity_luminosity(
    table: pa.Table, log_teff: np.ndarray, sigma_log_teff: np.ndarray
) -> Found:
    """L from the radius R = √(GM / g) of a paper's mass and log g, and the
    Teff."""
    mass, logg = floats(table, "mass_literature"), floats(table, "logg_literature")
    gm_cgs = SUN_GM_KM3_S2 * 1e15
    with np.errstate(invalid="ignore", divide="ignore"):
        log_radius = 0.5 * (np.log10(gm_cgs * mass) - logg) - np.log10(
            SOLAR_RADIUS_KM * 1e5
        )
    sigma_log_radius = 0.5 * np.hypot(
        floats(table, "logg_literature_error"),
        _log_width(table, "mass_literature_lower", "mass_literature_upper"),
    )
    log_l = photometry.log_l_from_radius(10**log_radius, log_teff)
    return MASS_GRAVITY, 10**log_l, np.hypot(4 * sigma_log_teff, 2 * sigma_log_radius)


def _bolometric_luminosity(
    table: pa.Table,
    kind: np.ndarray,
    distance_pc: np.ndarray,
    distance_error: np.ndarray,
    a_v: np.ndarray,
    log_teff: np.ndarray,
    sigma_log_teff: np.ndarray,
) -> Found:
    """L from V, the distance and Flower's BC, for an FGK dwarf, a giant or
    a hot star. Torres 2010 finds the BC wrong for M dwarfs."""
    log_l = photometry.log_l_from_v(v_mag(table), distance_pc, a_v, log_teff)
    bc = np.isin(kind, [metallicity.FGK_DWARF, metallicity.GIANT, metallicity.OBA])
    log_l = np.where(bc, log_l, np.nan)
    bc_spread = np.abs(
        photometry.flower_bc(log_teff + sigma_log_teff)
        - photometry.flower_bc(log_teff - sigma_log_teff)
    )
    sigma = np.hypot(2 * distance_error / np.log(10), 0.4 * bc_spread / 2)
    return BOLOMETRIC, 10**log_l, sigma


def _excluded(table: pa.Table) -> np.ndarray:
    """The EXCLUDED reason of each row, "" for a row with none."""
    otype = table["simbad_otype"].fill_null("").to_numpy(zero_copy_only=False)
    otype = otype.astype(str)
    young = table["spicy_id"].is_valid().to_numpy(zero_copy_only=False) | np.isin(
        otype, list(YSO_TYPES)
    )
    binary = table[BINARY_POINT].to_numpy(zero_copy_only=False)
    compact = table[COMPACT].to_numpy(zero_copy_only=False)
    return np.select([binary, compact, young], list(EXCLUDED), "")


@dataclass(frozen=True)
class Chosen:
    """What the fit and the star panel take from each row. Widths are in dex."""

    where: placement.Placement
    # The distance (pc) that the star renders at, and its relative error.
    distance_pc: np.ndarray
    distance_error: np.ndarray
    kind: np.ndarray
    feh: np.ndarray
    sigma_feh: np.ndarray
    feh_source: np.ndarray
    # Johnson V and its source, None where there is none.
    apparent_v: np.ndarray
    apparent_v_source: np.ndarray
    # A_V (mag), and its source.
    a_v: np.ndarray
    extinction_source: np.ndarray
    teff: np.ndarray
    sigma_log_teff: np.ndarray
    teff_source: np.ndarray
    luminosity: np.ndarray
    sigma_log_l: np.ndarray
    luminosity_source: np.ndarray
    # The EXCLUDED reason of each row, "" for a row with none.
    excluded: np.ndarray


@dataclass(frozen=True)
class Inputs:
    """The chosen values of each row, log Teff and log L, and the tier."""

    chosen: Chosen
    log_teff: np.ndarray
    log_l: np.ndarray
    tier: np.ndarray
    # Why a row has no tier, "" for a row with one.
    out: np.ndarray


def choose(table: pa.Table) -> Chosen:
    """The values of each row of `table`, which holds COLUMNS, the orbit
    parallax, BINARY_POINT and COMPACT."""
    n = table.num_rows
    where = placement.placement(table)
    distance_pc = placement.star_distance(table, where)[0]
    error = placement.distance_error(table, where)
    bp_rp = render.photometric_bp_rp(table)
    abs_g = absolute_g(table, distance_pc)
    excluded = _excluded(table)
    compact = excluded == COMPACT_STAR
    kind = np.where(compact, metallicity.COMPACT, metallicity.star_kind(bp_rp, abs_g))
    feh, sigma_feh, source = metallicity.choose(table, kind)
    assumed = ~np.isin(source, [*SPECTRA, metallicity.XP])
    feh = np.where(assumed, 0.0, feh)
    sigma_feh = np.where(assumed, SOLAR_SIGMA, sigma_feh)
    feh_source = np.where(assumed, ASSUMED_SOLAR, source)
    binary = table[BINARY_POINT].to_numpy(zero_copy_only=False)
    v, v_source = apparent_v(table)
    a_v, extinction_source = extinction(table, distance_pc, v, binary)

    def gaia(column: str) -> np.ndarray:
        return np.where(compact, np.nan, floats(table, column))

    paper_teff = floats(table, "teff_literature")
    teff, sigma_teff, teff_source = _first(
        (HOST, floats(table, "host_teff"), np.zeros(n)),
        *(
            (name, np.where(binary, np.nan, value), width)
            for name, value, width in (
                (
                    PAPER,
                    paper_teff,
                    _dex(paper_teff, floats(table, "teff_literature_error")),
                ),
                (
                    GSPPHOT,
                    gaia("teff_gspphot"),
                    _log_width(table, "teff_gspphot_lower", "teff_gspphot_upper"),
                ),
                *_measured_teff(table, kind),
                *_colour_teff(table, kind, feh, a_v),
            )
        ),
    )
    with np.errstate(invalid="ignore", divide="ignore"):
        log_teff = np.log10(teff)
    lum, sigma_lum, luminosity_source = _first(
        *(
            (
                name,
                gaia(f"lum_flame{run}"),
                _log_width(table, f"lum_flame{run}_lower", f"lum_flame{run}_upper"),
            )
            for name, run in ((FLAME, ""), (FLAME_SPEC, "_spec"))
        ),
        _radius_luminosity(table, log_teff, sigma_teff),
        _gravity_luminosity(table, log_teff, sigma_teff),
        _bolometric_luminosity(
            table, kind, distance_pc, error, a_v, log_teff, sigma_teff
        ),
    )
    return Chosen(
        where,
        distance_pc,
        error,
        kind,
        feh,
        sigma_feh,
        feh_source,
        v,
        v_source,
        a_v,
        extinction_source,
        teff,
        sigma_teff,
        teff_source,
        lum,
        sigma_lum,
        luminosity_source,
        excluded,
    )


def read(table: pa.Table) -> Inputs:
    """The inputs and the tier of each row of `table`, which holds COLUMNS,
    the orbit parallax, BINARY_POINT and COMPACT."""
    chosen = choose(table)
    error, kind = chosen.distance_error, chosen.kind
    spectrum = np.isin(chosen.feh_source, list(SPECTRA))
    assumed = chosen.feh_source == ASSUMED_SOLAR

    ruwe = floats(table, "ruwe")
    nss = table["non_single_star"]
    nss_known = nss.is_valid().to_numpy(zero_copy_only=False)
    nss = nss.fill_null(0).to_numpy(zero_copy_only=False)
    multiple = (ruwe >= MAX_RUWE) | (nss > 0)
    single = ~multiple & (ruwe < MAX_RUWE) & nss_known
    derived = np.isin(chosen.teff_source, list(FROM_COLOUR)) | (
        chosen.luminosity_source == BOLOMETRIC
    )

    tier = np.full(table.num_rows, 3, np.int8)
    tier[~multiple & (error <= FAIR_DISTANCE) & ~assumed] = 2
    dwarf = np.isin(kind, [metallicity.FGK_DWARF, metallicity.M_DWARF])
    tier[single & (error <= GOOD_DISTANCE) & spectrum & dwarf & ~derived] = 1
    unknown = chosen.extinction_source == UNKNOWN
    tier[(derived & unknown) | chosen.where.by_suspect] = 3
    out = np.select(
        [
            chosen.excluded != "",
            kind == metallicity.NO_KIND,
            ~np.isfinite(error) | (error > MAX_DISTANCE),
        ],
        [chosen.excluded, "no kind", "distance"],
        "",
    )
    tier[out != ""] = NO_TIER
    with np.errstate(invalid="ignore", divide="ignore"):
        return Inputs(
            chosen, np.log10(chosen.teff), np.log10(chosen.luminosity), tier, out
        )
