"""The metallicity that a star's panel shows, for the interior fit.

This is the rule of `frontend/src/components/detail/sections/star/metallicity.ts`
over Point source rows: the star's kind from its colour and absolute G, then
the first source in that kind's order with a value that holds. A compact star
(the export's `compact`, `families.compact`) has a kind of its own. No source
holds for it, because the surveys and Gaia's models are for normal stars. A change to
one file needs the same change in the other. Both test suites check the
stars of `data/tests/fixtures/star_metallicity.json`.

Each value comes with a width in dex: the published error, half the published
range, else DEFAULT_SIGMA. The fit reads [M/H] as [Fe/H], because the grid has
[α/Fe] = 0.
"""

from collections.abc import Callable

import numpy as np
import pyarrow as pa
import pyarrow.compute as pc

from space_map_data.utils.arrays import floats

OBA, FGK_DWARF, GIANT, M_DWARF = "oba", "fgkDwarf", "giant", "mDwarf"
COMPACT = "compact"
# No colour or no absolute G.
NO_KIND = ""
# BP − RP of an F0 and an M0 dwarf.
OBA_MAX_COLOUR = 0.4
M_DWARF_MIN_COLOUR = 1.84
# A giant is brighter than this absolute G: 2 mag over a straight main
# sequence, with no extinction.
GIANT_SLOPE = 2.8
GIANT_INTERCEPT = 0.3
# Where the XP [M/H] holds (Andrae, Rix & Chandra 2023, Sect. 3.5 and 4.3).
XP_MIN_COLOUR = 0.5
XP_MAX_COLOUR = 2.5
XP_MAX_G = 17.65
# The XP [M/H] has no error for each star; the paper gives 0.1 dex.
XP_SIGMA = 0.1
# A source that publishes no error.
DEFAULT_SIGMA = 0.1

PASTEL = "pastel-2020"
APOGEE = "apogee-dr17"
XHIP = "xhip"
GSPSPEC = "gaia-dr3-gspspec"
LAMOST = "lamost-dr10"
XP = "andrae-2023"
GSPPHOT = "gaia-dr3-gspphot"

# The Point source columns that `choose` reads, besides the colour and G.
COLUMNS = (
    "feh_pastel",
    "feh_pastel_min",
    "feh_pastel_max",
    "feh_apogee",
    "feh_apogee_error",
    "mh_apogee",
    "mh_apogee_error",
    "feh_xhip",
    "feh_xhip_error",
    "feh_xhip_quality",
    "mh_gspspec",
    "mh_gspspec_lower",
    "mh_gspspec_upper",
    "mh_gspspec_calibrated",
    "feh_gspspec_calibrated",
    "fem_gspspec",
    "fem_gspspec_lower",
    "fem_gspspec_upper",
    "flags_gspspec",
    "mh_lamost",
    "mh_lamost_error",
    "activity_lamost",
    "mh_xgboost",
    "in_vetted_rgb_sample",
    "in_oba_golden_sample",
    "mh_gspphot",
    "mh_gspphot_lower",
    "mh_gspphot_upper",
    "phot_g_mean_mag",
    "phot_bp_mean_mag",
    "phot_rp_mean_mag",
)

# A source's value and width for each row, NaN where it has none that holds.
type Values = tuple[np.ndarray, np.ndarray]
type Rule = Callable[[pa.Table], Values]
# The columns that `choose` adds: where the GSP-Spec and XP values hold.
GSPSPEC_HOLDS = "gspspec_holds"
XP_HOLDS = "xp_holds"
# The GSP-Spec flags that the quality cut reads.
GSPSPEC_FLAGS = 13


def star_kind(colour: np.ndarray, abs_g: np.ndarray) -> np.ndarray:
    """The kind of each star, NO_KIND without a colour or an absolute G."""
    kind = np.full(colour.size, NO_KIND, "<U10")
    known = np.isfinite(colour) & np.isfinite(abs_g)
    oba = known & (colour < OBA_MAX_COLOUR)
    giant = known & ~oba & (abs_g < GIANT_SLOPE * colour + GIANT_INTERCEPT)
    dwarf = known & ~oba & ~giant
    kind[oba] = OBA
    kind[giant] = GIANT
    kind[dwarf & (colour < M_DWARF_MIN_COLOUR)] = FGK_DWARF
    kind[dwarf & (colour >= M_DWARF_MIN_COLOUR)] = M_DWARF
    return kind


def _flag(table: pa.Table, name: str, value: bool) -> np.ndarray:
    """True where the column holds `value`; a null holds neither."""
    column = table[name]
    return (column.fill_null(not value).to_numpy(zero_copy_only=False) == value) & (
        column.is_valid().to_numpy(zero_copy_only=False)
    )


def _width(table: pa.Table, low: str, high: str) -> np.ndarray:
    return (floats(table, high) - floats(table, low)) / 2


def _with_error(table: pa.Table, name: str) -> Values:
    return floats(table, name), floats(table, f"{name}_error")


def first(*found: Values) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """The first finite value of each row, its width, and the index of its
    source in `found`, -1 where no source has one."""
    value = np.full(found[0][0].size, np.nan)
    width = np.full(value.size, np.nan)
    index = np.full(value.size, -1)
    for k, (its_value, its_width) in enumerate(found):
        take = (index < 0) & np.isfinite(its_value)
        value[take], width[take], index[take] = its_value[take], its_width[take], k
    return value, width, index


def _either(*rules: Rule) -> Rule:
    def rule(table: pa.Table) -> Values:
        return first(*(each(table) for each in rules))[:2]

    return rule


def _pastel(table: pa.Table) -> Values:
    return floats(table, "feh_pastel"), _width(
        table, "feh_pastel_min", "feh_pastel_max"
    )


def _xhip(table: pa.Table) -> Values:
    """Quality C is uncalibrated."""
    quality = table["feh_xhip_quality"].to_numpy(zero_copy_only=False)
    value, sigma = _with_error(table, "feh_xhip")
    return np.where(np.isin(quality, ["A", "B"]), value, np.nan), sigma


def gspspec_holds(table: pa.Table) -> np.ndarray:
    """The medium-quality cut of Recio-Blanco et al. 2023 (Sect. 9.1.1) on the
    first 13 flags: each at most 1, but fluxNoise (7th) at most 3 and
    KMgiantPar (13th) 0. A row with no flags fails."""
    flags = pc.utf8_slice_codeunits(
        table["flags_gspspec"].fill_null(""), 0, GSPSPEC_FLAGS
    )
    flags = pc.utf8_rpad(flags, GSPSPEC_FLAGS, "9").combine_chunks()
    if not len(flags):
        return np.zeros(0, bool)
    # Each value now has GSPSPEC_FLAGS ASCII digits, so the data is a block.
    start = int(np.frombuffer(flags.buffers()[1], np.int32)[flags.offset])
    data = np.frombuffer(flags.buffers()[2], np.uint8)
    digits = data[start : start + GSPSPEC_FLAGS * len(flags)].reshape(-1, GSPSPEC_FLAGS)
    limit = np.ones(GSPSPEC_FLAGS, np.int16) + ord("0")
    limit[6], limit[12] = ord("3"), ord("0")
    return np.all((digits >= ord("0")) & (digits <= limit), axis=1)


def _holds(table: pa.Table, name: str) -> np.ndarray:
    return table[name].to_numpy(zero_copy_only=False)


def _gspspec_mh(table: pa.Table) -> Values:
    holds = _holds(table, GSPSPEC_HOLDS) & np.isfinite(floats(table, "mh_gspspec"))
    value = np.where(holds, floats(table, "mh_gspspec_calibrated"), np.nan)
    return value, _width(table, "mh_gspspec_lower", "mh_gspspec_upper")


def _gspspec_feh(table: pa.Table) -> Values:
    """[Fe/H] where its calibration holds, with the range of [Fe/M]."""
    holds = _holds(table, GSPSPEC_HOLDS) & np.isfinite(floats(table, "fem_gspspec"))
    value = np.where(holds, floats(table, "feh_gspspec_calibrated"), np.nan)
    return value, _width(table, "fem_gspspec_lower", "fem_gspspec_upper")


def _lamost(table: pa.Table) -> Values:
    """Zhang et al. 2025 advise caution for stars with Hα emission."""
    value, sigma = _with_error(table, "mh_lamost")
    return np.where(_flag(table, "activity_lamost", False), value, np.nan), sigma


def xp_holds(table: pa.Table) -> np.ndarray:
    """Their vetted red giants always; else inside the colour range and G
    limit, and not an OBA star of the golden sample."""
    colour = floats(table, "phot_bp_mean_mag") - floats(table, "phot_rp_mean_mag")
    inside = (
        _flag(table, "in_oba_golden_sample", False)
        & (floats(table, "phot_g_mean_mag") <= XP_MAX_G)
        & (colour > XP_MIN_COLOUR)
        & (colour < XP_MAX_COLOUR)
    )
    return _flag(table, "in_vetted_rgb_sample", True) | inside


def _xp(table: pa.Table) -> Values:
    value = np.where(_holds(table, XP_HOLDS), floats(table, "mh_xgboost"), np.nan)
    return value, np.full(table.num_rows, XP_SIGMA)


def _gspphot(table: pa.Table) -> Values:
    return floats(table, "mh_gspphot"), _width(
        table, "mh_gspphot_lower", "mh_gspphot_upper"
    )


_gspspec = _either(_gspspec_feh, _gspspec_mh)
# APOGEE gives [Fe/H] first, but [M/H] first for an M dwarf.
_apogee_feh = _either(
    lambda t: _with_error(t, "feh_apogee"), lambda t: _with_error(t, "mh_apogee")
)
_apogee_mh = _either(
    lambda t: _with_error(t, "mh_apogee"), lambda t: _with_error(t, "feh_apogee")
)

FGK_DWARF_ORDER: tuple[tuple[str, Rule], ...] = (
    (PASTEL, _pastel),
    (APOGEE, _apogee_feh),
    (XHIP, _xhip),
    (GSPSPEC, _gspspec),
    (XP, _xp),
    (GSPPHOT, _gspphot),
)
# Only spectra of hot stars hold for O, B and A stars. GSP-Phot is off by
# +0.5 dex there, so the panel hides it. A star with no kind takes the FGK
# order. A compact star takes none.
ORDER: dict[str, tuple[tuple[str, Rule], ...]] = {
    OBA: ((PASTEL, _pastel), (XHIP, _xhip)),
    FGK_DWARF: FGK_DWARF_ORDER,
    GIANT: (
        (PASTEL, _pastel),
        (APOGEE, _apogee_feh),
        (GSPSPEC, _gspspec),
        (XHIP, _xhip),
        (XP, _xp),
        (GSPPHOT, _gspphot),
    ),
    M_DWARF: (
        (APOGEE, _apogee_mh),
        (LAMOST, _lamost),
        (GSPSPEC, _gspspec_mh),
        (XP, _xp),
        (GSPPHOT, _gspphot),
    ),
    NO_KIND: FGK_DWARF_ORDER,
    COMPACT: (),
}


def choose(
    table: pa.Table, kind: np.ndarray
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """The value (dex), width (dex) and source of each row's metallicity; NaN
    and None where no source holds."""
    value = np.full(table.num_rows, np.nan)
    sigma = np.full(table.num_rows, np.nan)
    source = np.full(table.num_rows, None, object)
    table = table.select(list(COLUMNS))
    table = table.append_column(GSPSPEC_HOLDS, pa.array(gspspec_holds(table)))
    table = table.append_column(XP_HOLDS, pa.array(xp_holds(table)))
    for name, order in ORDER.items():
        rows = np.flatnonzero(kind == name)
        if not rows.size or not order:
            continue
        part = table.take(pa.array(rows))
        labels = np.array([*(label for label, _ in order), None], object)
        value[rows], sigma[rows], index = first(*(rule(part) for _, rule in order))
        source[rows] = labels[index]
    sigma = np.where(np.isfinite(sigma) & (sigma > 0), sigma, DEFAULT_SIGMA)
    return value, np.where(np.isfinite(value), sigma, np.nan), source
