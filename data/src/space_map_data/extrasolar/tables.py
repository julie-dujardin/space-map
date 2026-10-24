"""The record tables and the merge of several sources into one row.

A table is a set of properties that nearly every one of its rows has. Every
row is keyed by an ID. Its columns come in groups. Each group has a fixed
source order: the group takes the values of the first source in that order
that has a value in the group, and its source column names that source. The
values of the other sources are dropped. Their catalogue ids stay in the
registry, and Metadata lists them as cross-ids.

Metadata has a row for every live ID. It has no table number, because it
never mints. A data table has a number from 1 to 30, the `table` field of the
IDs it mints. To add a table, define it here and add it to TABLES.
"""

from dataclasses import dataclass

import numpy as np
import pyarrow as pa
import pyarrow.compute as pc

from space_map_data.extrasolar.ids import CELL_MASK, FIRST_TABLE, LAST_TABLE

ID_FIELD = pa.field("id", pa.int64(), nullable=False)
SOURCE_COLUMN = "source"


@dataclass(frozen=True)
class ColumnGroup:
    name: str
    columns: tuple[pa.Field, ...]
    # The source names, first wins.
    sources: tuple[str, ...]

    @property
    def source_column(self) -> str:
        return f"{self.name}_source"

    @property
    def names(self) -> list[str]:
        return [field.name for field in self.columns]


@dataclass(frozen=True)
class TableDef:
    number: int | None
    slug: str
    groups: tuple[ColumnGroup, ...]
    # Columns that the engine fills, not a source.
    computed: tuple[pa.Field, ...] = ()

    def __post_init__(self) -> None:
        if self.number is not None and not FIRST_TABLE <= self.number <= LAST_TABLE:
            raise ValueError(f"{self.slug}: table number {self.number}")
        names = [ID_FIELD.name] + [field.name for field in self.computed]
        for group in self.groups:
            names += [*group.names, group.source_column]
        if len(names) != len(set(names)):
            raise ValueError(f"{self.slug}: a column name is used twice")

    @property
    def schema(self) -> pa.Schema:
        fields = [ID_FIELD]
        for group in self.groups:
            fields += [*group.columns, pa.field(group.source_column, pa.string())]
        return pa.schema(fields + list(self.computed))

    @property
    def group_fields(self) -> list[pa.Field]:
        return [field for group in self.groups for field in group.columns]

    def groups_of(self, source: str) -> list[ColumnGroup]:
        return [group for group in self.groups if source in group.sources]


CROSS_ID = pa.struct(
    [
        pa.field("catalogue", pa.string()),
        pa.field("release", pa.string()),
        pa.field("catalogue_id", pa.string()),
    ]
)


def _fields(kind: pa.DataType, *names: str) -> tuple[pa.Field, ...]:
    return tuple(pa.field(name, kind) for name in names)


# The name is the IAU proper name, else a Bayer or Flamsteed designation, HD,
# HIP or Gaia DR3 number, in that order. Each source gives its best one.
METADATA = TableDef(
    number=None,
    slug="metadata",
    groups=(
        ColumnGroup(
            "name",
            (pa.field("name", pa.string()),),
            ("iau-wgsn", "hipparcos-2007", "gaia-dr3"),
        ),
        ColumnGroup(
            "class", (pa.field("class", pa.string()),), ("gaia-dr3", "hipparcos-2007")
        ),
    ),
    computed=(
        pa.field("cross_ids", pa.list_(CROSS_ID)),
        # Bit n is set when data table n has a row for the ID.
        pa.field("mask", pa.uint32()),
        pa.field("object_file", pa.string()),
        pa.field("alias_target", pa.int64()),
    ),
)

# Every Gaia DR3 field of the positionable stars with its error or range, and
# the Hipparcos astrometry and photometry. A group that one catalogue fills
# keeps that catalogue's names. The Gaia rows also carry the astrometric
# fidelity of Rybizki et al. 2022.
POINT_SOURCE = TableDef(
    number=1,
    slug="point-source",
    groups=(
        # ICRS at `epoch` (Julian year): deg, errors in mas (ra_error is on
        # ra·cos dec), parallax in mas, proper motions in mas/yr (pmra is
        # on ra·cos dec).
        ColumnGroup(
            "astrometry",
            (
                *_fields(pa.float64(), "ra", "dec"),
                *_fields(
                    pa.float32(),
                    "ra_error",
                    "dec_error",
                    "parallax",
                    "parallax_error",
                    "pmra",
                    "pmra_error",
                    "pmdec",
                    "pmdec_error",
                    "epoch",
                ),
            ),
            ("gaia-dr3", "hipparcos-2007"),
        ),
        ColumnGroup(
            "gaia_photometry",
            (
                *_fields(
                    pa.float32(),
                    "phot_g_mean_mag",
                    "phot_bp_mean_mag",
                    "phot_rp_mean_mag",
                    "phot_g_mean_flux_over_error",
                    "phot_bp_mean_flux_over_error",
                    "phot_rp_mean_flux_over_error",
                    "phot_bp_rp_excess_factor",
                ),
                pa.field("phot_variable_flag", pa.string()),
            ),
            ("gaia-dr3",),
        ),
        # From the Hipparcos catalogue of 1997 (I/239): magnitudes in mag,
        # sp_type as published.
        ColumnGroup(
            "hipparcos_photometry",
            (
                *_fields(
                    pa.float32(),
                    "hp_mag",
                    "hp_mag_error",
                    "v_mag",
                    "b_v",
                    "b_v_error",
                    "v_i",
                    "v_i_error",
                ),
                pa.field("sp_type", pa.string()),
            ),
            ("hipparcos-2007",),
        ),
        ColumnGroup(
            "rvs",
            (
                *_fields(pa.float32(), "radial_velocity", "radial_velocity_error"),
                pa.field("rv_nb_transits", pa.int16()),
                *_fields(
                    pa.float32(),
                    "rv_expected_sig_to_noise",
                    "vbroad",
                    "vbroad_error",
                    "grvs_mag",
                    "grvs_mag_error",
                ),
            ),
            ("gaia-dr3",),
        ),
        # Lower and upper are the 16th and 84th percentiles.
        ColumnGroup(
            "gspphot",
            (
                *_fields(
                    pa.float32(),
                    *(
                        f"{name}_gspphot{bound}"
                        for name in (
                            "teff",
                            "radius",
                            "logg",
                            "mh",
                            "distance",
                            "azero",
                            "ag",
                            "ebpminrp",
                        )
                        for bound in ("", "_lower", "_upper")
                    ),
                ),
                pa.field("libname_gspphot", pa.string()),
            ),
            ("gaia-dr3",),
        ),
        ColumnGroup(
            "astrometric_quality",
            (
                pa.field("ruwe", pa.float32()),
                pa.field("astrometric_params_solved", pa.int8()),
                *_fields(
                    pa.float32(),
                    "astrometric_excess_noise",
                    "astrometric_excess_noise_sig",
                ),
                pa.field("visibility_periods_used", pa.int16()),
                pa.field("ipd_frac_multi_peak", pa.int8()),
                pa.field("ipd_gof_harmonic_amplitude", pa.float32()),
                pa.field("duplicated_source", pa.bool_()),
                *_fields(pa.float32(), "nu_eff_used_in_astrometry", "pseudocolour"),
            ),
            ("gaia-dr3",),
        ),
        ColumnGroup(
            "gaia_classification",
            (
                pa.field("non_single_star", pa.int16()),
                *_fields(pa.bool_(), "in_qso_candidates", "in_galaxy_candidates"),
                *_fields(
                    pa.float32(),
                    "classprob_dsc_combmod_quasar",
                    "classprob_dsc_combmod_galaxy",
                    "classprob_dsc_combmod_star",
                ),
            ),
            ("gaia-dr3",),
        ),
        ColumnGroup(
            "gaia_products",
            _fields(
                pa.bool_(),
                "has_xp_continuous",
                "has_xp_sampled",
                "has_rvs",
                "has_epoch_photometry",
                "has_epoch_rv",
            ),
            ("gaia-dr3",),
        ),
        # Under 0.5 marks a likely spurious astrometric solution.
        ColumnGroup(
            "fidelity",
            _fields(pa.float32(), "fidelity_v2", "norm_dg"),
            ("gaia-dr3",),
        ),
    ),
)

TABLES: tuple[TableDef, ...] = (POINT_SOURCE,)


def merge_by_source_order(table: TableDef, rows: pa.Table) -> pa.Table:
    """One row per ID from the rows of several sources.

    `rows` has the columns `id`, `source` and every group column of `table`
    (null where a source has no value). An ID with no value in any group gets
    no row. The result is sorted by cell, then ID, and has the group columns
    and source columns of `table.schema`; computed columns are left out.
    """
    if not rows.num_rows:
        return pa.schema(
            [f for f in table.schema if f.name not in {c.name for c in table.computed}]
        ).empty_table()
    ids = rows["id"].to_numpy()
    order = np.lexsort((ids, ids & CELL_MASK))
    rows = rows.take(order)
    ids = ids[order]
    starts = np.flatnonzero(np.r_[True, ids[1:] != ids[:-1]])
    group_of_row = np.repeat(np.arange(starts.size), np.diff(np.r_[starts, ids.size]))
    sources = rows[SOURCE_COLUMN].combine_chunks()

    columns: dict[str, pa.Array] = {}
    any_value = np.zeros(starts.size, bool)
    for group in table.groups:
        rank = np.full(rows.num_rows, len(group.sources), np.int64)
        for position, name in enumerate(group.sources):
            rank[pc.equal(sources, name).to_numpy(zero_copy_only=False)] = position
        has = np.zeros(rows.num_rows, bool)
        for name in group.names:
            has |= rows[name].is_valid().to_numpy(zero_copy_only=False)
        has &= rank < len(group.sources)
        # In each ID, the row of the first eligible source comes first.
        best = np.lexsort((np.where(has, rank, len(group.sources)), group_of_row))
        pick = best[starts]
        chosen = has[pick]
        any_value |= chosen
        mask = pa.array(~chosen)
        for field in group.columns:
            values = rows[field.name].take(pick).combine_chunks().cast(field.type)
            columns[field.name] = pc.if_else(
                mask, pa.nulls(starts.size, field.type), values
            )
        columns[group.source_column] = pc.if_else(
            mask, pa.nulls(starts.size, pa.string()), sources.take(pick)
        )

    keep = np.flatnonzero(any_value)
    out = {"id": pa.array(ids[starts][keep], pa.int64())}
    out.update({name: array.take(keep) for name, array in columns.items()})
    return pa.table(out)
