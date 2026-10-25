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

    def group(self, name: str) -> ColumnGroup:
        (group,) = (group for group in self.groups if group.name == name)
        return group


CROSS_ID = pa.struct(
    [
        pa.field("catalogue", pa.string()),
        pa.field("release", pa.string()),
        pa.field("catalogue_id", pa.string()),
    ]
)


def _fields(kind: pa.DataType, *names: str) -> tuple[pa.Field, ...]:
    return tuple(pa.field(name, kind) for name in names)


def _flame(run: str) -> tuple[pa.Field, ...]:
    """The columns of one FLAME run, whose names end in `run`, with the 16th
    and 84th percentiles: radius in nominal solar radii, luminosity in nominal
    solar luminosities, mass in solar masses, age in Gyr, gravitational
    redshift in km/s, the bolometric correction in mag. The stage and the
    flags are as published."""
    return (
        *_fields(
            pa.float32(),
            *(
                f"{name}_flame{run}{bound}"
                for name in ("radius", "lum", "mass", "age", "gravredshift")
                for bound in ("", "_lower", "_upper")
            ),
            f"bc_flame{run}",
        ),
        pa.field(f"evolstage_flame{run}", pa.int16()),
        pa.field(f"flags_flame{run}", pa.string()),
    )


# The exoplanet catalogues, in their source order.
EXOPLANET_SOURCES = (
    "nasa-exoplanet-archive",
    "exoplanet-eu",
    "open-exoplanet-catalogue",
)

# The name is the IAU proper name. A planet host then takes the name of its
# exoplanet catalogues, since its planets' designations come from it. Other
# stars take the Wikidata label, else a Bayer or Flamsteed designation, a WR
# number, a GCVS name, an HD or HIP number, a SIMBAD NAME, SIMBAD's main
# identifier or the Gaia DR3 number, in that order. Each source gives its best
# one. SIMBAD comes before Hipparcos: it knows more designations.
METADATA = TableDef(
    number=None,
    slug="metadata",
    groups=(
        ColumnGroup(
            "name",
            (pa.field("name", pa.string()),),
            (
                "iau-wgsn",
                *EXOPLANET_SOURCES,
                "wikidata",
                "simbad",
                "hipparcos-2007",
                "hipparcos-1997",
                "gaia-dr3",
                "gaia-dr3-named",
            ),
        ),
        ColumnGroup(
            "class",
            (pa.field("class", pa.string()),),
            (
                "gaia-dr3",
                "hipparcos-2007",
                "hipparcos-1997",
                "gaia-dr3-named",
                *EXOPLANET_SOURCES,
                "simbad",
            ),
        ),
    ),
    computed=(
        pa.field("cross_ids", pa.list_(CROSS_ID)),
        # Bit n is set when data table n has a row for the ID.
        pa.field("mask", pa.uint32()),
        # True when the site's object files hold an entry for the ID.
        pa.field("object", pa.bool_()),
        pa.field("alias_target", pa.int64()),
    ),
)

# An ID with an id of one of these catalogues has an entry in the site's
# object files, which is built from that catalogue.
OBJECT_CATALOGUES = frozenset({"wikidata", "literature"})

# Every Gaia DR3 field of the positionable stars with its error or range, and
# the Hipparcos astrometry and photometry. A group that one catalogue fills
# keeps that catalogue's names. The Gaia rows also carry the astrometric
# fidelity of Rybizki et al. 2022 and the XP metallicities of Andrae et al.
# 2023. The metallicity groups after them come from spectra, one catalogue
# each. PASTEL, APOGEE and LAMOST join the Gaia rows by source_id at each
# ingest (PASTEL also the Hipparcos rows by HIP number), so they hold no
# catalogue id in the registry. gaia-dr3-named are the Gaia rows of SIMBAD
# stars and planet hosts without a 5σ parallax, so their astrometry ranks
# below Hipparcos.
POINT_SOURCE = TableDef(
    number=1,
    slug="point-source",
    groups=(
        # ICRS at `epoch` (Julian year): deg, errors in mas (ra_error is on
        # ra·cos dec), parallax in mas, proper motions in mas/yr (pmra is
        # on ra·cos dec). A row of hipparcos-1997 has only a rough ra and dec.
        # SIMBAD's errors are the major axis of its error ellipses.
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
            (
                "gaia-dr3",
                "hipparcos-2007",
                "gaia-dr3-named",
                *EXOPLANET_SOURCES,
                "simbad",
                "hipparcos-1997",
            ),
        ),
        # A distance in pc from a paper, a SIMBAD parallax or a distance
        # catalogue, with its 16th and 84th percentiles or the value ∓ its
        # error. `distance_method`: `parallax`, `photometric`, `cluster` (of
        # the host cluster), `galaxy` (of the host galaxy), `geometric`
        # (parallax with a Galaxy prior) or `expansion` (expansion parallax of
        # a nebula). A value from a paper comes first: it is chosen for that
        # star.
        ColumnGroup(
            "distance",
            (
                *_fields(pa.float32(), "distance", "distance_lower", "distance_upper"),
                pa.field("distance_method", pa.string()),
            ),
            (
                "literature",
                "simbad-parallax",
                "reyle-2021",
                "ultracoolsheet",
                "hunt-reffert-2024",
                "magellanic-clouds",
                "bailer-jones-2021",
            ),
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
            ("gaia-dr3", "gaia-dr3-named"),
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
            ("hipparcos-2007", "hipparcos-1997"),
        ),
        # Compiled by SIMBAD from the literature: B, V and Gaia G in mag, the
        # spectral type as SIMBAD gives it, and SIMBAD's object type. Every
        # SIMBAD row has an object type, so the source column marks the stars
        # that SIMBAD lists.
        ColumnGroup(
            "simbad_photometry",
            (
                *_fields(pa.float32(), "simbad_b_mag", "simbad_v_mag", "simbad_g_mag"),
                pa.field("simbad_sp_type", pa.string()),
                pa.field("simbad_otype", pa.string()),
            ),
            ("simbad",),
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
            ("gaia-dr3", "gaia-dr3-named"),
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
            ("gaia-dr3", "gaia-dr3-named"),
        ),
        # FLAME, from the GSP-Phot temperature and the G luminosity.
        ColumnGroup("flame", _flame(""), ("gaia-dr3", "gaia-dr3-named")),
        # Table 1 of Andrae et al. 2023, with no quality cut: [M/H] in dex,
        # Teff in K, log g in log(cm/s²), CatWISE W1 and W2 in Vega mag.
        # The flags mark their vetted Table 2 and the Gaia golden sample of
        # OBA stars, the inputs of their validity cuts.
        ColumnGroup(
            "xgboost",
            (
                *_fields(
                    pa.float32(),
                    "mh_xgboost",
                    "teff_xgboost",
                    "logg_xgboost",
                    "catwise_w1",
                    "catwise_w2",
                ),
                *_fields(
                    pa.bool_(),
                    "in_training_sample",
                    "in_vetted_rgb_sample",
                    "in_oba_golden_sample",
                ),
            ),
            ("gaia-dr3", "gaia-dr3-named"),
        ),
        # GSP-Spec from the RVS spectra, with the calibrations of
        # Recio-Blanco et al. 2023: [M/H] and [Fe/M] in dex, log g in
        # log(cm/s²), and the 41-character flag chain as published.
        ColumnGroup(
            "gspspec",
            (
                *_fields(
                    pa.float32(),
                    *(
                        f"{name}_gspspec{bound}"
                        for name in ("mh", "fem", "logg")
                        for bound in ("", "_lower", "_upper")
                    ),
                    "mh_gspspec_calibrated",
                    "feh_gspspec_calibrated",
                ),
                pa.field("flags_gspspec", pa.string()),
            ),
            ("gaia-dr3", "gaia-dr3-named"),
        ),
        # XHIP [Fe/H] (Anderson & Francis 2012). Quality A and B are
        # calibrated, C is not.
        ColumnGroup(
            "xhip_metallicity",
            (
                *_fields(pa.float32(), "feh_xhip", "feh_xhip_error"),
                pa.field("feh_xhip_quality", pa.string()),
            ),
            ("hipparcos-2007", "hipparcos-1997"),
        ),
        # PASTEL: the designation, the median [Fe/H] of the star's
        # determinations, their range and number, and the bibcode of each,
        # space-separated.
        ColumnGroup(
            "pastel",
            (
                pa.field("pastel_designation", pa.string()),
                *_fields(
                    pa.float32(), "feh_pastel", "feh_pastel_min", "feh_pastel_max"
                ),
                pa.field("feh_pastel_count", pa.int16()),
                pa.field("pastel_bibcodes", pa.string()),
            ),
            ("gaia-dr3", "gaia-dr3-named", "hipparcos-2007", "hipparcos-1997"),
        ),
        # APOGEE DR17: the APOGEE id and the named ASPCAP values, [M/H] and
        # [Fe/H] in dex, Teff in K, log g in log(cm/s²), with their errors,
        # and the S/N per pixel.
        ColumnGroup(
            "apogee",
            (
                pa.field("apogee_id", pa.string()),
                *_fields(
                    pa.float32(),
                    *(
                        f"{name}_apogee{suffix}"
                        for name in ("mh", "feh", "teff", "logg")
                        for suffix in ("", "_error")
                    ),
                    "snr_apogee",
                ),
            ),
            ("gaia-dr3", "gaia-dr3-named"),
        ),
        # The LAMOST DR10 M dwarfs of Zhang et al. 2025, from the spectrum
        # with the best S/N in i: its LAMOST designation, [M/H] in dex, Teff
        # in K, log g in log(cm/s²), with their errors, the Hα activity flag
        # and the variability or binarity flag (0 none, 1 variable, 2 binary).
        ColumnGroup(
            "lamost",
            (
                pa.field("lamost_id", pa.string()),
                *_fields(
                    pa.float32(),
                    *(
                        f"{name}_lamost{suffix}"
                        for name in ("mh", "teff", "logg")
                        for suffix in ("", "_error")
                    ),
                    "snr_i_lamost",
                ),
                pa.field("activity_lamost", pa.bool_()),
                pa.field("vbflag_lamost", pa.int8()),
            ),
            ("gaia-dr3", "gaia-dr3-named"),
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
            ("gaia-dr3", "gaia-dr3-named"),
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
            ("gaia-dr3", "gaia-dr3-named"),
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
            ("gaia-dr3", "gaia-dr3-named"),
        ),
        # Under 0.5 marks a likely spurious astrometric solution.
        ColumnGroup(
            "fidelity",
            _fields(pa.float32(), "fidelity_v2", "norm_dg"),
            ("gaia-dr3", "gaia-dr3-named"),
        ),
        # The star as an exoplanet catalogue gives it: its name there, the
        # distance (pc) with its larger error, Teff (K), radius and mass
        # (solar), metallicity (dex), log g (cgs), age (Gyr) and V, G and K
        # magnitudes. The distance places a star that neither a 5σ parallax
        # nor the distance group places.
        ColumnGroup(
            "host_star",
            (
                pa.field("host_name", pa.string()),
                *_fields(
                    pa.float32(),
                    "host_distance",
                    "host_distance_error",
                    "host_teff",
                    "host_radius",
                    "host_mass",
                    "host_metallicity",
                    "host_logg",
                    "host_age",
                    "host_v_mag",
                    "host_g_mag",
                    "host_k_mag",
                ),
                pa.field("host_spectral_type", pa.string()),
            ),
            EXOPLANET_SOURCES,
        ),
    ),
)

# Point source holds these names, so the orbit solution's astrometry takes the
# suffix `_nss`. A column of a source feeds every table that has its name.
NSS_ASTROMETRY = {
    name: name.replace(base, f"{base}_nss")
    for base in ("ra", "dec", "parallax", "pmra", "pmdec")
    for name in (base, f"{base}_error")
}

# One Gaia DR3 orbit solution per star (nss_two_body_orbit) and the masses of
# its two stars (binary_masses), with the published names and units: angles in
# deg, times in d, Thiele-Innes A, B, F, G in mas and C, H in AU. `corr_vec` is
# the published correlation vector with its NaN entries. A value is float32
# when float32 rounding stays under 1% of each published error, else float64.
BINARY_ORBIT = TableDef(
    number=2,
    slug="binary-orbit",
    groups=(
        ColumnGroup(
            "orbit",
            (
                pa.field("solution_id", pa.uint64()),
                pa.field("nss_solution_type", pa.string()),
                pa.field(NSS_ASTROMETRY["ra"], pa.float64()),
                pa.field(NSS_ASTROMETRY["ra_error"], pa.float32()),
                pa.field(NSS_ASTROMETRY["dec"], pa.float64()),
                *_fields(
                    pa.float32(),
                    *(
                        NSS_ASTROMETRY[name]
                        for name in (
                            "dec_error",
                            "parallax",
                            "parallax_error",
                            "pmra",
                            "pmra_error",
                            "pmdec",
                            "pmdec_error",
                        )
                    ),
                    *(
                        f"{element}_thiele_innes{suffix}"
                        for element in "abfgch"
                        for suffix in ("", "_error")
                    ),
                ),
                pa.field("period", pa.float64()),
                *_fields(
                    pa.float32(),
                    "period_error",
                    *(
                        f"{name}{suffix}"
                        for name in (
                            "t_periastron",
                            "eccentricity",
                            "center_of_mass_velocity",
                            "semi_amplitude_primary",
                            "semi_amplitude_secondary",
                            "mass_ratio",
                            "fill_factor_primary",
                            "fill_factor_secondary",
                        )
                        for suffix in ("", "_error")
                    ),
                ),
                pa.field("inclination", pa.float64()),
                *_fields(
                    pa.float32(),
                    "inclination_error",
                    "arg_periastron",
                    "arg_periastron_error",
                ),
                pa.field("temperature_ratio", pa.float64()),
                pa.field("temperature_ratio_error", pa.float32()),
                pa.field("temperature_ratio_definition", pa.int8()),
                *_fields(
                    pa.int32(),
                    *(
                        f"{kind}_n_{good}obs_{side}"
                        for kind, side in (
                            ("astrometric", "al"),
                            ("rv", "primary"),
                            ("rv", "secondary"),
                        )
                        for good in ("", "good_")
                    ),
                    "phot_g_n_obs",
                    "phot_g_n_good_obs",
                ),
                pa.field("bit_index", pa.uint32()),
                pa.field("corr_vec", pa.list_(pa.float32())),
                *_fields(
                    pa.float32(),
                    "obj_func",
                    "goodness_of_fit",
                    "efficiency",
                    "significance",
                ),
                pa.field("flags", pa.uint64()),
                *_fields(
                    pa.float32(),
                    "conf_spectro_period",
                    "r_pole_sum",
                    "r_l1_point_sum",
                    "r_spher_sum",
                    "ecl_time_primary",
                    "ecl_time_secondary",
                    "ecl_dur_primary",
                    "ecl_dur_secondary",
                    "g_luminosity_ratio",
                    "input_period_error",
                    "g_rank",
                    "astrometric_jitter",
                ),
            ),
            ("gaia-dr3", "gaia-dr3-named"),
        ),
        # Masses in solar masses, bounds at the 16th and 84th percentiles. The
        # flux ratio is the secondary over the primary in G.
        ColumnGroup(
            "masses",
            (
                *_fields(
                    pa.float32(),
                    *(
                        f"{name}{bound}"
                        for name in ("m1", "m2", "fluxratio")
                        for bound in ("", "_lower", "_upper")
                    ),
                ),
                *_fields(pa.string(), "combination_method", "m1_ref", "flag"),
            ),
            ("gaia-dr3", "gaia-dr3-named"),
        ),
    ),
)

TABLES: tuple[TableDef, ...] = (POINT_SOURCE, BINARY_ORBIT)


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
