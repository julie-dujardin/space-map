"""The surface values of a star's panel, which the export computes for each
Point source row.

Teff, L, V and A_V are those of the interior fit (`interiors.inputs.choose`),
so the panel and the fit agree. `teff` is the one Teff of the export: the
render colour, the system files, the habitable zone and the star lineup take
it. A value has bounds where its source publishes
them: the 16th and 84th percentiles of GSP-Phot and FLAME, or the value ± the
1σ error of a paper, APOGEE and LAMOST. A value that a relation gives has
none. The fit leaves out compact stars and young stellar objects, and the
panel does not. A point that holds two or more stars has V, and the Teff that
the exoplanet catalogue gives the host star of its planets. Its light is that
of two stars, so the other one-star values do not hold for it, nor does
GSP-Phot's A_V (`inputs.extinction`). Its panel shows V and absolute V only.

log g is that of the source of Teff where that source has one, else
GSP-Phot's, else the exoplanet catalogue's. A compact star takes no GSP-Phot
log g. Absolute V is at the distance that the star renders at, less A_V.
`extinction_source` tells a negligible A_V of V from an unknown one.
`compact` is the export's compact-star test (`families.compact`), so that a
client leaves out Gaia's fits of the same stars. The interior step writes these columns for
each region (`interiors.table`), and the tiles take them from there.
"""

from collections import Counter

import numpy as np
import pyarrow as pa

from space_map_data.extrasolar.interiors import inputs
from space_map_data.utils.arrays import floats

# Magnitudes are known to a few mmag at best.
MAG_DECIMALS = 3
# The directory of the surface values in the export's scratch.
SCRATCH = "surface"
# The Point source columns that `columns` reads besides `inputs.COLUMNS`.
COLUMNS = tuple(
    dict.fromkeys(
        (
            *inputs.COLUMNS,
            "logg_gspphot",
            "logg_gspphot_lower",
            "logg_gspphot_upper",
            "host_logg",
            "logg_apogee",
            "logg_apogee_error",
            "logg_lamost",
            "logg_lamost_error",
            "logg_esphs",
            "logg_xgboost",
        )
    )
)


def _bounded(*names: str) -> tuple[pa.Field, ...]:
    return tuple(
        pa.field(f"{name}{bound}", pa.float32())
        for name in names
        for bound in ("", "_lower", "_upper")
    )


# Teff in K, L in nominal solar luminosities, log g in log(cm/s²), V in mag.
FIELDS = (
    *_bounded("teff"),
    pa.field("teff_source", pa.string()),
    *_bounded("luminosity"),
    pa.field("luminosity_source", pa.string()),
    *_bounded("logg"),
    pa.field("logg_source", pa.string()),
    pa.field("apparent_v", pa.float32()),
    pa.field("apparent_v_source", pa.string()),
    pa.field("absolute_v", pa.float32()),
    pa.field("extinction_source", pa.string()),
    pa.field("compact", pa.bool_()),
)

# A value with its lower and upper bound.
type Bounded = tuple[np.ndarray, np.ndarray, np.ndarray]


def _percentiles(table: pa.Table, name: str) -> Bounded:
    value, low, high = (floats(table, f"{name}{b}") for b in ("", "_lower", "_upper"))
    return value, low, high


def _error(table: pa.Table, name: str, error: str) -> Bounded:
    value, sigma = floats(table, name), floats(table, error)
    return value, value - sigma, value + sigma


def _alone(table: pa.Table, name: str) -> Bounded:
    value = floats(table, name)
    return value, np.full(value.size, np.nan), np.full(value.size, np.nan)


def _teff_bounds(table: pa.Table) -> dict[str, tuple[np.ndarray, np.ndarray]]:
    """The published bounds of each Teff source that has them."""
    found = {
        inputs.PAPER: _error(table, "teff_literature", "teff_literature_error"),
        inputs.GSPPHOT: _percentiles(table, "teff_gspphot"),
        inputs.APOGEE: _error(table, "teff_apogee", "teff_apogee_error"),
        inputs.LAMOST: _error(table, "teff_lamost", "teff_lamost_error"),
    }
    return {name: (low, high) for name, (_, low, high) in found.items()}


def _loggs(table: pa.Table) -> dict[str, Bounded]:
    """The log g of each Teff source that has one."""
    return {
        inputs.PAPER: _error(table, "logg_literature", "logg_literature_error"),
        inputs.GSPPHOT: _percentiles(table, "logg_gspphot"),
        inputs.HOST: _alone(table, "host_logg"),
        inputs.APOGEE: _error(table, "logg_apogee", "logg_apogee_error"),
        inputs.LAMOST: _error(table, "logg_lamost", "logg_lamost_error"),
        inputs.ESPHS: _alone(table, "logg_esphs"),
        inputs.XP: _alone(table, "logg_xgboost"),
    }


def _pick(
    source: np.ndarray, bounds: dict[str, tuple[np.ndarray, np.ndarray]]
) -> tuple[np.ndarray, np.ndarray]:
    """The bounds of each row's source, NaN for a source without them."""
    low = np.full(source.size, np.nan)
    high = np.full(source.size, np.nan)
    for name, (its_low, its_high) in bounds.items():
        at = source == name
        low[at], high[at] = its_low[at], its_high[at]
    return low, high


def logg(table: pa.Table, chosen: inputs.Chosen) -> tuple[Bounded, np.ndarray]:
    """log g with its bounds, and its source, None where none has one."""
    loggs = _loggs(table)
    n = table.num_rows
    out: Bounded = (np.full(n, np.nan), np.full(n, np.nan), np.full(n, np.nan))
    source = np.full(n, None, object)
    steps = [(name, chosen.teff_source == name) for name in loggs]
    steps += [
        (inputs.GSPPHOT, chosen.excluded != inputs.COMPACT_STAR),
        (inputs.HOST, np.ones(n, bool)),
    ]
    for name, rows in steps:
        values = loggs[name]
        at = rows & np.isnan(out[0]) & np.isfinite(values[0])
        for column, value in zip(out, values, strict=True):
            column[at] = value[at]
        source[at] = name
    return out, source


def _strings(values: np.ndarray, keep: np.ndarray) -> pa.Array:
    return pa.array(values, pa.string(), mask=~keep)


def columns(table: pa.Table, chosen: inputs.Chosen) -> list[pa.Array]:
    """The FIELDS of each row of `table`, which holds COLUMNS, the orbit
    parallax, `inputs.BINARY_POINT` and `inputs.COMPACT`, from its
    `inputs.choose`."""
    single = ~table[inputs.BINARY_POINT].to_numpy(zero_copy_only=False)
    teff_low, teff_high = _pick(chosen.teff_source, _teff_bounds(table))
    l_low, l_high = _pick(
        chosen.luminosity_source,
        {
            name: _percentiles(table, f"lum_flame{run}")[1:]
            for name, run in ((inputs.FLAME, ""), (inputs.FLAME_SPEC, "_spec"))
        },
    )
    (g, g_low, g_high), g_source = logg(table, chosen)
    v = np.round(chosen.apparent_v, MAG_DECIMALS)
    with np.errstate(invalid="ignore", divide="ignore"):
        absolute = v - 5 * np.log10(chosen.distance_pc) + 5 - chosen.a_v
    absolute = np.round(absolute, MAG_DECIMALS)

    def one_star(values: np.ndarray) -> pa.Array:
        return pa.array(
            np.where(single, values, np.nan), pa.float32(), from_pandas=True
        )

    def any_point(values: np.ndarray) -> pa.Array:
        return pa.array(values, pa.float32(), from_pandas=True)

    return [
        any_point(chosen.teff),
        one_star(teff_low),
        one_star(teff_high),
        pa.array(chosen.teff_source, pa.string()),
        one_star(chosen.luminosity),
        one_star(l_low),
        one_star(l_high),
        _strings(chosen.luminosity_source, single),
        one_star(g),
        one_star(g_low),
        one_star(g_high),
        _strings(g_source, single),
        any_point(v),
        pa.array(chosen.apparent_v_source, pa.string()),
        any_point(absolute),
        _strings(chosen.extinction_source, np.isfinite(v)),
        pa.array(chosen.excluded == inputs.COMPACT_STAR, pa.bool_(), mask=~single),
    ]


# The source columns whose works the export credits.
SOURCES = ("teff_source", "luminosity_source", "apparent_v_source")


def count_key(name: str, source: str) -> str:
    """The key of `counts` for the rows of `source` in column `name`."""
    return f"surface {name}: {source}"


def counts(found: pa.Table) -> Counter:
    """The number of rows of `found`, a `rows` table, for each source in SOURCES."""
    out: Counter = Counter()
    for name in SOURCES:
        for entry in found[name].value_counts().to_pylist():
            if entry["values"] is not None:
                out[count_key(name, entry["values"])] = entry["counts"]
    return out


def rows(table: pa.Table, chosen: inputs.Chosen) -> pa.Table:
    """The ID and the FIELDS of each row of `table`, as `columns` takes it."""
    return pa.table(
        [table["id"], *columns(table, chosen)],
        schema=pa.schema([table.schema.field("id"), *FIELDS]),
    )
