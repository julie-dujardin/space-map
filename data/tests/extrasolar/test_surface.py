"""The surface values of the star panel, computed for each Point source row."""

import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from space_map_data.constants.planets.families import SUN_TEFF
from space_map_data.export.extrasolar import tiles
from space_map_data.extrasolar import families, placement, store, surface
from space_map_data.extrasolar.interiors import inputs, photometry
from space_map_data.extrasolar.store import region_file
from space_map_data.extrasolar.tables import POINT_SOURCE

NAMES = [field.name for field in surface.FIELDS]
HIPPARCOS = "hipparcos-2007"
HOST = "nasa-exoplanet-archive"


def _rows(*stars: dict, binary: tuple[int, ...] = ()) -> pa.Table:
    """Point source rows with what `surface.columns` reads. The IDs run from
    100; `binary` holds the IDs of the points of two stars."""
    schema = pa.schema([POINT_SOURCE.schema.field(name) for name in surface.COLUMNS])
    rows = [{"id": 100 + k} | star for k, star in enumerate(stars)]
    table = pa.Table.from_pylist(rows, schema=schema)
    systems = pa.table(
        {
            "id": pa.array(binary, pa.int64()),
            "point": pa.array([True] * len(binary), pa.bool_()),
        }
    )
    masks = families.masks(table, pa.nulls(len(rows), pa.string()))
    table = inputs.with_compact(table, np.bitwise_or(*masks))
    return inputs.with_binary_points(
        placement.with_orbit_parallax(table, None), systems
    )


def _values(*stars: dict, binary: tuple[int, ...] = ()) -> list[dict]:
    table = _rows(*stars, binary=binary)
    columns = surface.columns(table, inputs.choose(table))
    return pa.table(dict(zip(NAMES, columns, strict=True))).to_pylist()


def _flame_star(**more) -> dict:
    """A single Gaia FGK dwarf at 10 pc with GSP-Phot and FLAME values."""
    return {
        "parallax": 100.0,
        "parallax_error": 0.1,
        "astrometry_source": "gaia-dr3",
        "fidelity_v2": 1.0,
        "phot_g_mean_mag": 5.0,
        "phot_bp_mean_mag": 5.4,
        "phot_rp_mean_mag": 4.6,
        "teff_gspphot": 5704.0,
        "teff_gspphot_lower": 5650.0,
        "teff_gspphot_upper": 5760.0,
        "logg_gspphot": 4.4,
        "logg_gspphot_lower": 4.35,
        "logg_gspphot_upper": 4.45,
        "lum_flame": 1.413,
        "lum_flame_lower": 1.38,
        "lum_flame_upper": 1.45,
    } | more


def _proxima() -> dict:
    """An M dwarf at 1.3 pc with GSP-Phot's Teff and the host's Teff and
    log g, but no GSP-Phot log g and no FLAME luminosity."""
    return {
        "parallax": 768.07,
        "parallax_error": 0.05,
        "astrometry_source": "gaia-dr3",
        "fidelity_v2": 1.0,
        "phot_g_mean_mag": 8.98,
        "phot_bp_mean_mag": 11.38,
        "phot_rp_mean_mag": 7.58,
        "teff_gspphot": 3000.0,
        "teff_gspphot_lower": 2980.0,
        "teff_gspphot_upper": 3020.0,
        "host_star_source": "nasa-exoplanet-archive",
        "host_teff": 3050.0,
        "host_logg": 5.2,
        "host_v_mag": 11.13,
        "v_mag": 11.01,
        "hipparcos_photometry_source": "hipparcos-2007",
    }


def _tau_ceti() -> dict:
    """A saturated Hipparcos FGK dwarf at 3.65 pc with a paper's radius."""
    return {
        "parallax": 273.96,
        "parallax_error": 0.17,
        "astrometry_source": "hipparcos-2007",
        "hipparcos_photometry_source": "hipparcos-2007",
        "v_mag": 3.49,
        "b_v": 0.727,
        "b_v_error": 0.002,
        "v_i": 0.80,
        "feh_pastel": -0.5,
        "radius_literature": 0.793,
    }


def _arcturus() -> dict:
    """A Hipparcos giant at 11.3 pc with an angular diameter only."""
    return {
        "parallax": 88.83,
        "parallax_error": 0.54,
        "astrometry_source": "hipparcos-2007",
        "hipparcos_photometry_source": "hipparcos-2007",
        "v_mag": -0.05,
        "b_v": 1.239,
        "b_v_error": 0.005,
        "v_i": 1.22,
        "angular_diameter": 21.06,
    }


def _white_dwarf(**more) -> dict:
    """40 Eri B at 5 pc: Gaia photometry below the main sequence, SIMBAD's
    type, and the values of the 40 pc sample."""
    return {
        "parallax": 199.69,
        "parallax_error": 0.05,
        "astrometry_source": "gaia-dr3",
        "fidelity_v2": 1.0,
        "phot_g_mean_mag": 9.54,
        "phot_bp_mean_mag": 9.41,
        "phot_rp_mean_mag": 9.60,
        "simbad_otype": "WD*",
        "simbad_photometry_source": "simbad",
        "simbad_b_mag": 9.50,
        "simbad_v_mag": 9.52,
        "teff_literature": 16265.0,
        "teff_literature_error": 278.0,
        "logg_literature": 7.916,
        "logg_literature_error": 0.021,
        "mass_literature": 0.568,
        "mass_literature_lower": 0.556,
        "mass_literature_upper": 0.580,
    } | more


def _pulsar() -> dict:
    """A pulsar host with a mass from its exoplanet catalogue only."""
    return {
        "parallax": 1.4,
        "parallax_error": 0.1,
        "astrometry_source": "simbad",
        "simbad_photometry_source": "simbad",
        "simbad_otype": "Psr",
        "host_star_source": "nasa-exoplanet-archive",
        "host_mass": 1.4,
    }


class TestRoutes:
    """The values of representative stars, with their sources."""

    def test_a_flame_star_has_every_value_with_its_bounds(self):
        (row,) = _values(_flame_star())
        assert (row["teff"], row["teff_lower"], row["teff_upper"]) == (
            5704,
            5650,
            5760,
        )
        assert row["teff_source"] == inputs.GSPPHOT
        assert row["luminosity"] == pytest.approx(1.413)
        assert (row["luminosity_lower"], row["luminosity_source"]) == (
            pytest.approx(1.38),
            inputs.FLAME,
        )
        assert (row["logg"], row["logg_source"]) == (pytest.approx(4.4), inputs.GSPPHOT)
        assert row["logg_upper"] == pytest.approx(4.45)
        assert row["apparent_v_source"] == photometry.RIELLO_2021
        v = 5.0 - np.polynomial.polynomial.polyval(0.8, photometry.RIELLO_G_MINUS_V)
        assert row["apparent_v"] == pytest.approx(v, abs=1e-3)
        # Within 100 pc A_V is 0, so at 10 pc absolute V is apparent V.
        assert row["absolute_v"] == pytest.approx(row["apparent_v"], abs=2e-3)
        assert row["extinction_source"] == inputs.NEGLIGIBLE
        assert row["compact"] is False

    def test_proxima_takes_the_hosts_teff_and_log_g(self):
        (row,) = _values(_proxima())
        assert (row["teff"], row["teff_source"]) == (3050, inputs.HOST)
        assert row["teff_lower"] is None
        assert (row["logg"], row["logg_source"]) == (pytest.approx(5.2), inputs.HOST)
        assert row["logg_lower"] is None
        # No FLAME, no radius, and no BC for an M dwarf.
        assert (row["luminosity"], row["luminosity_source"]) == (None, None)
        assert (row["apparent_v"], row["apparent_v_source"]) == (
            pytest.approx(11.01),
            HIPPARCOS,
        )
        assert row["absolute_v"] == pytest.approx(
            11.01 - 5 * np.log10(1000 / 768.07) + 5, abs=1e-3
        )

    def test_a_saturated_star_takes_the_colour_teff_and_the_radius(self):
        (row,) = _values(_tau_ceti())
        assert row["teff_source"] == photometry.CASAGRANDE_2010
        assert (row["teff_lower"], row["teff_upper"]) == (None, None)
        assert row["luminosity_source"] == inputs.RADIUS
        assert row["luminosity"] == pytest.approx(
            0.793**2 * (row["teff"] / SUN_TEFF) ** 4, rel=1e-4
        )
        assert (row["logg"], row["logg_source"]) == (None, None)
        assert row["apparent_v_source"] == HIPPARCOS

    def test_a_giant_with_an_angular_diameter(self):
        (row,) = _values(_arcturus())
        assert row["teff_source"] == photometry.FLOWER_1996
        assert row["luminosity_source"] == inputs.RADIUS
        radius = 21.06 / 2 * 1000 / 88.83 * 1.495978707e8 / 695_700 / 1000
        assert row["luminosity"] == pytest.approx(
            radius**2 * (row["teff"] / SUN_TEFF) ** 4, rel=1e-3
        )
        assert row["absolute_v"] == pytest.approx(
            -0.05 - 5 * np.log10(1000 / 88.83) + 5, abs=1e-3
        )

    def test_a_white_dwarf_takes_its_paper(self):
        (row,) = _values(_white_dwarf())
        assert (row["teff"], row["teff_source"]) == (16265, inputs.PAPER)
        assert (row["teff_lower"], row["teff_upper"]) == (15987, 16543)
        assert (row["logg"], row["logg_source"]) == (
            pytest.approx(7.916),
            inputs.PAPER,
        )
        assert row["logg_lower"] == pytest.approx(7.895)
        assert row["luminosity_source"] == inputs.MASS_GRAVITY
        # R = √(GM/g) in cm, then L = R² T⁴ in solar units.
        radius = np.sqrt(1.3271244e26 * 0.568 / 10**7.916) / 6.957e10
        assert row["luminosity"] == pytest.approx(
            radius**2 * (16265 / SUN_TEFF) ** 4, rel=1e-4
        )
        assert row["apparent_v_source"] == "simbad"
        assert row["compact"] is True

    def test_a_white_dwarf_takes_no_relation_of_the_star_kinds(self):
        bare = {f"{name}_literature": None for name in ("teff", "logg", "mass")}
        (row,) = _values(_white_dwarf(b_v=0.0, v_mag=9.52, **bare))
        assert (row["teff"], row["luminosity"], row["logg"]) == (None, None, None)
        assert row["apparent_v"] == pytest.approx(9.52)

    def test_a_white_dwarf_takes_no_gaia_model(self):
        """GSP-Phot and FLAME fit a white dwarf as a main-sequence star."""
        bare = {f"{name}_literature": None for name in ("teff", "logg", "mass")}
        gaia = _flame_star()
        gaia = {k: v for k, v in gaia.items() if "gspphot" in k or "flame" in k}
        (row,) = _values(_white_dwarf(**bare, **gaia))
        assert (row["teff"], row["luminosity"], row["logg"]) == (None, None, None)

    def test_paper_values_make_a_white_dwarf(self):
        """A white dwarf that neither DSC nor SIMBAD types."""
        table = _rows(_white_dwarf(simbad_otype=None, **_flame_star()))
        assert inputs.read(table).out.tolist() == [inputs.COMPACT_STAR]
        (row,) = _values(_white_dwarf(simbad_otype=None, **_flame_star()))
        assert (row["teff_source"], row["logg_source"]) == (inputs.PAPER, inputs.PAPER)
        assert row["luminosity_source"] == inputs.MASS_GRAVITY
        assert row["compact"] is True

    def test_a_paper_teff_with_no_error_counts_as_none(self):
        (row,) = _values(_white_dwarf(teff_literature_error=None))
        assert (row["teff"], row["teff_source"]) == (None, None)
        assert row["luminosity"] is None

    def test_a_paper_radius_comes_before_mass_and_gravity(self):
        (row,) = _values(_white_dwarf(radius_literature=0.0131))
        assert row["luminosity_source"] == inputs.RADIUS

    def test_a_pulsar_with_a_host_mass_only_has_nothing(self):
        """A pulsar is a compact star, so Gaia's fits do not hold for it."""
        (row,) = _values(_pulsar())
        assert row.pop("compact") is True
        assert all(row[name] is None for name in row)

    def test_a_point_of_two_stars_has_v_and_the_hosts_teff_only(self):
        """V, absolute V, the source of its A_V, and the Teff that the planet
        catalogue gives its host."""
        rows = _values(
            _flame_star(),
            _flame_star(v_mag=4.9, hipparcos_photometry_source=HIPPARCOS),
            _flame_star(host_star_source="nasa-exoplanet-archive", host_teff=5900.0),
            binary=(101, 102),
        )
        assert rows[0]["teff"] is not None
        two = rows[1]
        assert (two["apparent_v"], two["apparent_v_source"]) == (
            pytest.approx(4.9),
            HIPPARCOS,
        )
        assert two["absolute_v"] == pytest.approx(4.9, abs=1e-3)
        assert two["extinction_source"] == inputs.NEGLIGIBLE
        point = {"apparent_v", "apparent_v_source", "absolute_v", "extinction_source"}
        assert all(two[name] is None for name in set(NAMES) - point)
        host = rows[2]
        assert (host["teff"], host["teff_source"]) == (5900, inputs.HOST)
        point |= {"teff", "teff_source"}
        assert all(host[name] is None for name in set(NAMES) - point)

    def test_absolute_v_takes_the_extinction(self):
        far = _flame_star(
            parallax=5.0,
            parallax_error=0.1,
            phot_g_mean_mag=11.5,
            phot_bp_mean_mag=11.9,
            phot_rp_mean_mag=11.1,
            azero_gspphot=0.3,
            v_mag=11.6,
        )
        (row,) = _values(far)
        assert row["absolute_v"] == pytest.approx(
            11.6 - 5 * np.log10(200) + 5 - 0.3, abs=1e-3
        )
        assert row["extinction_source"] == inputs.GSPPHOT

    def test_a_point_of_two_stars_takes_no_gspphot_extinction(self):
        """GSP-Phot's A0 is a one-star fit."""
        far = _flame_star(
            parallax=5.0, parallax_error=0.1, azero_gspphot=0.3, v_mag=11.6
        )
        (_, row) = _values(_flame_star(), far, binary=(101,))
        assert row["absolute_v"] == pytest.approx(
            11.6 - 5 * np.log10(200) + 5, abs=1e-3
        )
        assert row["extinction_source"] == inputs.UNKNOWN

    def test_an_unknown_extinction_is_taken_as_zero(self):
        far = _flame_star(parallax=5.0, parallax_error=0.1, v_mag=11.6)
        (row,) = _values(far)
        assert row["absolute_v"] == pytest.approx(
            11.6 - 5 * np.log10(200) + 5, abs=1e-3
        )
        assert row["extinction_source"] == inputs.UNKNOWN

    def test_the_extinction_reads_the_shown_v(self):
        """A naked-eye star by its host V or Gaia V takes no extinction."""
        far = {
            "parallax": 5.0,
            "parallax_error": 0.1,
            "astrometry_source": "gaia-dr3",
            "fidelity_v2": 1.0,
            "azero_gspphot": 0.3,
        }
        gaia = {"phot_g_mean_mag": 5.5, "phot_bp_mean_mag": 5.9}
        gaia["phot_rp_mean_mag"] = 5.1
        rows = _values(
            far | gaia | {"host_v_mag": 5.6, "host_star_source": HOST},
            far | gaia,
            far | {"host_v_mag": 7.0, "host_star_source": HOST},
        )
        assert [row["apparent_v_source"] for row in rows] == [
            HOST,
            photometry.RIELLO_2021,
            HOST,
        ]
        assert rows[0]["absolute_v"] == pytest.approx(5.6 - 5 * np.log10(20), abs=1e-3)
        assert rows[1]["absolute_v"] == pytest.approx(
            rows[1]["apparent_v"] - 5 * np.log10(20), abs=1e-3
        )
        assert rows[2]["absolute_v"] == pytest.approx(
            7.0 - 5 * np.log10(20) - 0.3, abs=1e-3
        )
        assert [row["extinction_source"] for row in rows] == [
            inputs.NEGLIGIBLE,
            inputs.NEGLIGIBLE,
            inputs.GSPPHOT,
        ]

    def test_no_distance_gives_no_absolute_v(self):
        (row,) = _values({"astrometry_source": "simbad", "simbad_v_mag": 7.0})
        assert (row["apparent_v"], row["absolute_v"]) == (pytest.approx(7.0), None)
        assert row["extinction_source"] == inputs.UNKNOWN
        (row,) = _values({"parallax": 100.0, "astrometry_source": "gaia-dr3"})
        assert row["extinction_source"] is None

    def test_the_panel_and_the_fit_agree(self):
        table = _rows(_flame_star(), _proxima(), _tau_ceti(), _arcturus())
        fitted = inputs.read(table)
        found = surface.rows(table, fitted.chosen)
        assert found["id"].to_pylist() == [100, 101, 102, 103]
        assert found["teff_source"].to_pylist() == fitted.chosen.teff_source.tolist()
        assert found["luminosity_source"].to_pylist() == (
            fitted.chosen.luminosity_source.tolist()
        )
        teff = found["teff"].to_numpy(zero_copy_only=False)
        assert np.log10(teff) == pytest.approx(fitted.log_teff, rel=1e-6)

    def test_no_rows(self):
        table = _rows()
        columns = surface.columns(table, inputs.choose(table))
        assert [len(column) for column in columns] == [0] * len(NAMES)

    def test_the_counts_of_the_sources(self):
        table = _rows(_flame_star(), _tau_ceti(), _arcturus())
        found = surface.counts(surface.rows(table, inputs.choose(table)))
        assert found == {
            "surface teff_source: gaia-dr3-gspphot": 1,
            "surface teff_source: casagrande-2010": 1,
            "surface teff_source: flower-1996": 1,
            "surface luminosity_source: gaia-dr3-flame": 1,
            "surface luminosity_source: radius": 2,
            "surface apparent_v_source: riello-2021": 1,
            "surface apparent_v_source: hipparcos-2007": 2,
        }


class TestApparentV:
    """V from Gaia G with BP − RP (Riello et al. 2021, Table C.2)."""

    def test_the_polynomial(self):
        found = photometry.v_from_gaia(np.array([10.0, 10.0]), np.array([0.0, 1.0]))
        assert found[0] == pytest.approx(10.02704)
        assert found[1] == pytest.approx(10 - (-0.02704 + 0.01424 - 0.2156 + 0.01426))

    def test_outside_the_colour_range_there_is_none(self):
        found = photometry.v_from_gaia(np.full(2, 10.0), np.array([-0.6, 5.1]))
        assert np.isnan(found).all()

    def test_the_source_order(self):
        gaia = {"phot_g_mean_mag": 9.0, "phot_bp_mean_mag": 9.4}
        gaia["phot_rp_mean_mag"] = 8.6
        hipparcos = {"v_mag": 1.0, "hipparcos_photometry_source": "hipparcos-1997"}
        simbad = {"simbad_v_mag": 2.0, "simbad_photometry_source": "simbad"}
        host = {"host_v_mag": 3.0, "host_star_source": HOST}
        rows = _values(
            hipparcos | simbad | host | gaia,
            simbad | host | gaia,
            host | gaia,
            gaia,
            {"phot_g_mean_mag": 9.0, "phot_bp_mean_mag": 14.0, "phot_rp_mean_mag": 8.0},
        )
        assert [row["apparent_v_source"] for row in rows] == [
            "hipparcos-1997",
            "simbad",
            HOST,
            photometry.RIELLO_2021,
            None,
        ]


class TestTiles:
    """The shipped Point source tiles."""

    def test_the_schema_carries_the_surface_and_lacks_the_dropped(self):
        names = tiles.tile_schema(POINT_SOURCE).names
        assert names[-len(NAMES) :] == NAMES
        assert not tiles.DROPPED[POINT_SOURCE.slug] & set(names)
        for name in ("phot_g_mean_flux_over_error", "bc_flame", "ag_gspphot_upper"):
            assert name in POINT_SOURCE.schema.names
            assert name not in names
        for kept in ("gravredshift_flame", "vbroad", "teff_literature"):
            assert kept in names
        assert len(names) == len(set(names))

    def test_the_surface_columns_are_dictionaries_floats_or_a_flag(self):
        kinds = dict(tiles.column_types(POINT_SOURCE))
        assert kinds["compact"] == "bool"
        for field in surface.FIELDS:
            if field.name == "compact":
                continue
            want = "dict" if field.name.endswith("_source") else "float32"
            assert kinds[field.name] == want, field.name

    def test_the_tiles_take_the_values_of_the_interior_step(self, tmp_path):
        table = _rows(_flame_star(), _proxima())
        pq.write_table(
            surface.rows(table, inputs.choose(table)), region_file(tmp_path, 3)
        )
        rows = pa.table({"id": pa.array([101, 100], pa.int64())})
        found = store.with_computed(rows, (3,), tmp_path)
        assert found.column_names == ["id", *NAMES]
        assert found["teff"].to_pylist() == [3050, 5704]
        missing = pa.table({"id": pa.array([100, 7], pa.int64())})
        with pytest.raises(ValueError, match="1 rows have no computed values"):
            store.with_computed(missing, (3,), tmp_path)
