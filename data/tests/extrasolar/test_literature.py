"""The literature table and its ingest pass."""

import numpy as np
import pytest

from space_map_data.constants.stars.literature import (
    DISTANCES,
    LOGGS,
    MASSES,
    PROCYON_B,
    RADII,
    REFERENCES,
    SIRIUS_B,
    TEFFS,
    Bounds,
    Distance,
    Measured,
    Radius,
)
from space_map_data.download.providers.stars import obrien_white_dwarfs
from space_map_data.download.providers.stars.wikidata_stars import (
    GAIA_PIXEL_LEVEL,
    GAIA_PIXEL_SHIFT,
)
from space_map_data.extrasolar import sky
from space_map_data.extrasolar.engine import IngestRun
from space_map_data.extrasolar.registry import Registry
from space_map_data.extrasolar.sources import distances, gaia, jmdc, literature
from space_map_data.extrasolar.sources.distances import REYLE_2021
from space_map_data.extrasolar.sources.gaia import GAIA_DR3
from space_map_data.extrasolar.sources.hipparcos import claim_lists
from space_map_data.extrasolar.sources.literature import LITERATURE
from space_map_data.extrasolar.tables import POINT_SOURCE
from tests.extrasolar.conftest import table_rows
from tests.extrasolar.test_simbad import NO_BEST
from tests.extrasolar.test_stars import at, fidelity, gaia_star, gaia_stars

METHODS = {
    "parallax",
    "photometric",
    "cluster",
    "association",
    "galaxy",
    "geometric",
    "expansion",
    "dynamical",
    "model",
}


def gaia_id(ra: float, dec: float, n: int) -> int:
    """A Gaia source id whose pixel holds the position, as Gaia's do."""
    pixel = int(sky.cells(np.array([ra]), np.array([dec]), GAIA_PIXEL_LEVEL)[0])
    return (pixel << GAIA_PIXEL_SHIFT) + n


class TestTable:
    """The entries of the literature table."""

    def test_entries(self):
        for key, distance in DISTANCES.items():
            assert key[:2] in {("gaia", "dr3"), ("hip", "2007"), ("hd", "1949")}
            assert distance.lower <= distance.value <= distance.upper
            assert distance.method in METHODS
            assert distance.reference in REFERENCES
            assert (distance.lower_percentile is None) == (
                distance.upper_percentile is None
            )

    def test_references(self):
        for reference in REFERENCES.values():
            assert reference.url.startswith(
                ("https://doi.org/", "https://ui.adsabs.harvard.edu/abs/")
            )
            assert reference.short and reference.title

    def test_eta_car(self):
        eta_car = DISTANCES[("gaia", "dr3", "5350358584482202880")]
        assert eta_car == Distance(2350, 2300, 2400, "expansion", "smith_2006")

    def test_polis_keeps_its_published_interval(self):
        polis = DISTANCES[("gaia", "dr3", "4093933487636355968")]
        assert (polis.lower_percentile, polis.upper_percentile) == (2.5, 97.5)

    def test_stars_that_no_catalogue_places(self):
        alnilam = DISTANCES[("hip", "2007", "26311")]
        assert (alnilam.value, alnilam.method) == (384, "association")
        wr_104 = DISTANCES[("gaia", "dr3", "4069167258796371712")]
        assert (wr_104.lower, wr_104.upper) == (1900, 3300)

    def test_sirius_takes_the_parallax_of_its_masses(self):
        sirius = DISTANCES[("hip", "2007", "32349")]
        assert 1000 / sirius.value == pytest.approx(378.9, abs=0.01)
        assert 1000 / sirius.lower - 1000 / sirius.upper == pytest.approx(2.8, abs=0.01)
        assert (sirius.method, sirius.reference) == ("parallax", "bond_2017")

    def test_stars_of_the_sky_cultures(self):
        beta_phe = DISTANCES[("hip", "2007", "5165")]
        assert beta_phe == Distance(55.77, 54.17, 57.47, "parallax", "argyle_2015")
        tau2_cap = DISTANCES[("hip", "2007", "101923")]
        assert (tau2_cap.method, tau2_cap.reference) == (
            "dynamical",
            "bartkevicius_2002",
        )
        hd_184268 = DISTANCES[("hip", "2007", "96274")]
        assert hd_184268 == Distance(400.5, 389.2, 412.4, "parallax", "gaia_dr2_2018")

    def test_masses(self):
        assert len(MASSES) == 100
        for key, mass in MASSES.items():
            assert key[:2] in {("gaia", "dr3"), ("hip", "2007"), ("simbad", "oid")}
            assert mass.value > 0
            if isinstance(mass, Bounds):
                assert 0 < mass.lower < mass.value < mass.upper
            else:
                assert mass.error is None or 0 < mass.error < mass.value
            assert mass.reference in REFERENCES

    def test_masses_with_bounds(self):
        assert sum(isinstance(mass, Bounds) for mass in MASSES.values()) == 35
        # These two tables print bounds and no error.
        for mass in MASSES.values():
            if mass.reference in {"david_hillenbrand_2015", "stock_2018"}:
                assert isinstance(mass, Bounds)

    def test_masses_of_the_bright_stars(self):
        arcturus = MASSES[("hip", "2007", "69673")]
        assert arcturus == Measured(1.08, 0.06, "ramirez_allende_prieto_2011")
        cebalrai = MASSES[("gaia", "dr3", "4473334474604992384")]
        assert cebalrai == Measured(1.44, 0.16, "baines_2018")
        # A range goes in as its middle, with its ends as the bounds.
        assert MASSES[("hip", "2007", "27989")] == Bounds(17.8, 16.5, 19, "joyce_2020")
        assert MASSES[("hip", "2007", "80763")] == Bounds(12.7, 11, 14.3, "ohnaka_2013")
        uy_sct = ("gaia", "dr3", "4152993273702130432")
        assert MASSES[uy_sct] == Bounds(8.5, 7, 10, "arroyo_torres_2013")
        assert RADII[uy_sct].reference == "arroyo_torres_2013"
        # An online table's symmetric error goes in.
        assert MASSES[("hip", "2007", "33579")] == Measured(10.1, 1.0, "tetzlaff_2011")
        muphrid = MASSES[("gaia", "dr3", "1244946371540479616")]
        assert muphrid == Measured(1.559, 0.072, "soubiran_2024")
        # An asymmetric error and a table's bounds go in as bounds.
        vega = MASSES[("hip", "2007", "91262")]
        assert vega == Bounds(2.15, 2.00, 2.25, "monnier_2012")
        cursa = MASSES[("gaia", "dr3", "3211922645854328832")]
        assert cursa == Bounds(1.8, 1.7, 1.9, "david_hillenbrand_2015")
        enif = MASSES[("hip", "2007", "107315")]
        assert enif == Bounds(7.2, 7.00, 7.72, "stock_2018")
        # Luck 2015 prints no error.
        assert MASSES[("hip", "2007", "82273")] == Measured(2.33, None, "luck_2015")
        # Miaplacidus: the table rounds its error to 0.00.
        miaplacidus = MASSES[("hip", "2007", "45238")]
        assert miaplacidus == Measured(2.96, None, "allende_prieto_lambert_1999")
        # γ2 Vel takes the mass of its O star.
        assert MASSES[("hip", "2007", "39953")] == Measured(28.5, 1.1, "north_2007")
        # Gacrux, Tiaki and Scheat have no mass in a paper.
        for hip in ("61084", "112122", "113881"):
            assert ("hip", "2007", hip) not in MASSES


# Three rows of O'Brien et al. 2024 Table A1: 40 Eri B, Sirius B (no fit) and
# a row with a Teff and no Teff error.
TABLE_A1 = """WDJ_Name,DR3_source_id,parallax,gaia_teff,gaia_teff_err,gaia_logg,gaia_logg_err,gaia_mass,gaia_mass_err,corrected_teff
WDJ041531.18-073933.08,3195919254111315712,199.69,16265,278,7.916,.021,.568,.012,16265
WDJ064510.49-164243.38,2947050466531873024,374.49,,,,,,,
WDJ000000.00+000000.00,1,30.0,5000,,8.0,.02,.6,.01,5000
"""


# No measured value, with the columns of each table, as the engine wants them.
NO_VALUES: dict = {name: {} for name in literature.MEASURED_TABLES}


def _table_a1(tmp_path) -> None:
    (tmp_path / obrien_white_dwarfs.TABLE_FILE).write_text(TABLE_A1)


class TestWhiteDwarfs:
    """The white-dwarf values of the literature table."""

    def test_entries(self):
        assert TEFFS.keys() == LOGGS.keys() == {SIRIUS_B, PROCYON_B}
        for values in (TEFFS, LOGGS, MASSES):
            for key in TEFFS:
                found = values[key]
                assert isinstance(found, Measured)
                assert found.reference in REFERENCES
                assert found.error is not None and 0 < found.error < found.value

    def test_the_sample_takes_the_rows_with_a_fit(self, tmp_path):
        _table_a1(tmp_path)
        found = literature.white_dwarfs(tmp_path)
        eri = ("gaia", "dr3", "3195919254111315712")
        assert found["teff"][eri] == Measured(16265, 278, "obrien_2024")
        assert found["logg"][eri] == Measured(7.916, 0.021, "obrien_2024")
        assert found["mass"][eri] == Measured(0.568, 0.012, "obrien_2024")
        assert SIRIUS_B not in found["teff"]
        assert found["teff"][("gaia", "dr3", "1")].error is None

    def test_a_star_with_its_own_paper_keeps_it(self, tmp_path):
        _table_a1(tmp_path)
        found = literature.measured_tables(tmp_path)
        assert found.keys() == literature.MEASURED_TABLES.keys()
        assert found["teff"][SIRIUS_B] == TEFFS[SIRIUS_B]
        assert found["teff"][PROCYON_B] == TEFFS[PROCYON_B]
        assert len(found["mass"]) == len(MASSES) + 2

    def test_a_value_cites_the_paper_that_measured_tables_keeps(self, tmp_path):
        """`measured_reference` names the work of each value that
        `measured_tables` gives, with no download."""
        _table_a1(tmp_path)
        found = literature.measured_tables(tmp_path)
        for name, values in found.items():
            for key, entry in values.items():
                assert literature.measured_reference(name, key) == entry.reference
        assert literature.measured_reference("teff", SIRIUS_B) == "bond_2017"

    def test_a_star_twice_is_an_error(self, tmp_path):
        row = TABLE_A1.splitlines()[1]
        (tmp_path / obrien_white_dwarfs.TABLE_FILE).write_text(TABLE_A1 + row + "\n")
        with pytest.raises(ValueError, match="3195919254111315712 twice"):
            literature.white_dwarfs(tmp_path)

    def test_sirius_b_and_procyon_b_take_their_own_papers(self):
        assert TEFFS[SIRIUS_B] == Measured(25369, 46, "bond_2017")
        assert LOGGS[SIRIUS_B] == Measured(8.591, 0.016, "bond_2017")
        assert MASSES[SIRIUS_B] == Measured(1.018, 0.011, "bond_2017")
        assert RADII[SIRIUS_B] == Radius(0.008098, "bond_2017")
        assert TEFFS[PROCYON_B] == Measured(7740, 50, "bond_2015")
        assert MASSES[PROCYON_B].value == 0.592
        assert RADII[PROCYON_B] == Radius(0.01232, "bond_2015")


class TestRows:
    """The pass rows of the table."""

    def test_ids(self):
        key = ("gaia", "dr3", "5350358584482202880")
        assert literature.catalogue_id(key) == "gaia/dr3/5350358584482202880"
        assert literature.key_of(literature.catalogue_id(key)) == key

    def test_positions(self):
        ra, dec = at(0)
        source = gaia_id(ra, dec, 7)
        table = {
            ("gaia", "dr3", str(source)): Distance(
                10,
                9,
                11,
                "parallax",
                "smith_2006",
                lower_percentile=2.5,
                upper_percentile=97.5,
            ),
            ("hip", "2007", "5"): Distance(20, 19, 21, "parallax", "smith_2006"),
            ("hd", "1949", "6"): Distance(30, 29, 31, "parallax", "smith_2006"),
        }
        rows = literature.engine_rows(
            {"5": (1.0, 2.0)}, {"6": (3.0, 4.0)}, {}, table, radii={}, measured={}
        )
        assert rows["catalogue_id"].to_pylist() == [
            f"gaia/dr3/{source}",
            "hip/2007/5",
            "hd/1949/6",
        ]
        assert not any(rows["mint"].to_pylist())
        # The centre of the Gaia pixel, within a pixel of level 12 (52″).
        assert (
            sky.separation(
                np.array([rows["match_ra"][0].as_py()]),
                np.array([rows["match_dec"][0].as_py()]),
                ra,
                dec,
            )[0]
            < 52
        )
        assert rows["match_ra"].to_pylist()[1:] == [1.0, 3.0]
        assert rows["distance"].to_pylist() == [10, 20, 30]
        assert rows["distance_lower_percentile"].to_pylist() == [2.5, None, None]
        assert rows["distance_upper_percentile"].to_pylist() == [97.5, None, None]
        assert [c[0]["catalogue_id"] for c in rows["claims"].to_pylist()] == [
            str(source),
            "5",
            "6",
        ]

    def test_measured_values_and_a_simbad_key(self):
        key = ("simbad", "oid", "988144")
        rows = literature.engine_rows(
            {},
            {},
            {"988144": (114.8, 5.2)},
            table={},
            radii={},
            measured={
                "teff": {key: Measured(7740, 50, "bond_2015")},
                "logg": {key: Measured(8.028, None, "bond_2015")},
                "mass": {},
            },
        )
        assert rows["catalogue_id"].to_pylist() == ["simbad/oid/988144"]
        assert rows["match_ra"].to_pylist() == [114.8]
        assert rows["teff_literature"].to_pylist() == [7740]
        assert rows["teff_literature_error"].to_pylist() == [50]
        assert rows["logg_literature_error"].to_pylist() == [None]
        assert rows["mass_literature"].to_pylist() == [None]
        assert rows["mass_literature_lower"].to_pylist() == [None]
        assert rows["claims"].to_pylist()[0][0]["catalogue"] == "simbad"

    def test_the_rows_of_the_tables(self):
        distance = {
            ("hip", "2007", "5"): Distance(20, 19, 21, "parallax", "smith_2006")
        }
        radius = {("hip", "2007", "6"): Radius(3, "baron_2012")}
        masses = {
            ("hip", "2007", "5"): Measured(2.5, 0.1, "north_2007"),
            ("hip", "2007", "7"): Measured(1.08, None, "luck_2015"),
            ("hip", "2007", "8"): Bounds(2.06, 1.8, 2.2, "david_hillenbrand_2015"),
        }
        positions = {"5": (1.0, 2.0), "6": (3.0, 4.0), "7": (5.0, 6.0), "8": (7.0, 8.0)}
        rows = literature.engine_rows(
            positions, {}, {}, distance, radius, {**NO_VALUES, "mass": masses}
        )
        assert rows["catalogue_id"].to_pylist() == [
            "hip/2007/5",
            "hip/2007/6",
            "hip/2007/7",
            "hip/2007/8",
        ]
        assert rows["distance"].to_pylist() == [20, None, None, None]
        assert rows["radius_literature"].to_pylist() == [None, 3, None, None]
        mass = rows["mass_literature"].to_pylist()
        assert mass == pytest.approx([2.5, None, 1.08, 2.06])
        # A 1σ error gives the value ∓ the error. Bounds stay as printed.
        lower = rows["mass_literature_lower"].to_pylist()
        assert lower == pytest.approx([2.4, None, None, 1.8])
        upper = rows["mass_literature_upper"].to_pylist()
        assert upper == pytest.approx([2.6, None, None, 2.2])
        assert "mass_literature_error" not in rows.column_names

    def test_unknown_star(self):
        table = {("hip", "2007", "5"): Distance(20, 19, 21, "parallax", "smith_2006")}
        with pytest.raises(ValueError, match="no star has hip/2007/5"):
            literature.engine_rows({}, {}, {}, table)
        masses = {**NO_VALUES, "mass": {("hd", "1949", "5"): Measured(2, None, "x")}}
        with pytest.raises(ValueError, match="no star has hd/1949/5"):
            literature.engine_rows({}, {}, {}, {}, {}, masses)
        table = {("tyc", "2", "5"): Distance(20, 19, 21, "parallax", "smith_2006")}
        with pytest.raises(ValueError, match="not a Gaia, HIP, HD or SIMBAD id"):
            literature.engine_rows({}, {}, {}, table)


class TestPass:
    """The literature pass through the engine."""

    def test_a_radius_and_a_mass_leave_the_distance_to_its_catalogue(self, tmp_path):
        root = tmp_path / "root"
        p1 = at(0)
        source = gaia_id(*p1, 1)
        stored = gaia.engine_rows(
            gaia.join_fidelity(gaia_stars([gaia_star(source, *p1, 5.0)]), fidelity([])),
            NO_BEST,
        )
        key = ("gaia", "dr3", str(source))
        rows = literature.engine_rows(
            {},
            {},
            {},
            {},
            {key: Radius(1420, "baron_2012")},
            {**NO_VALUES, "mass": {key: Bounds(17.8, 16.5, 19, "joyce_2020")}},
        )
        reyle = distances.rows(
            np.array([p1[0]]),
            np.array([p1[1]]),
            [key],
            np.array([100.0]),
            np.array([99.0]),
            np.array([101.0]),
            ["parallax"],
        )
        diameters = jmdc.engine_rows({"7": p1}, {"7": (44.0, 3)}).set_column(
            6, "claims", claim_lists([[key]])
        )
        with IngestRun.start(root, root / "backup") as run:
            run.add(GAIA_DR3, [stored])
            run.add(REYLE_2021, [reyle])
            run.add(LITERATURE, [rows])
            run.add(jmdc.JMDC, [diameters])
            run.commit()
        star = int(Registry(root).lookup("gaia", "dr3", [str(source)])[0])
        row = {r["id"]: r for r in table_rows(root, POINT_SOURCE.slug).to_pylist()}[
            star
        ]
        assert (row["radius_literature"], row["paper_radius_source"]) == (
            1420,
            "literature",
        )
        assert row["mass_literature"] == pytest.approx(17.8)
        bounds = (row["mass_literature_lower"], row["mass_literature_upper"])
        assert bounds == pytest.approx((16.5, 19))
        assert row["paper_mass_source"] == "literature"
        assert (row["distance"], row["distance_source"]) == (100, "reyle-2021")
        assert (row["angular_diameter"], row["angular_diameter_count"]) == (44, 3)
        assert row["angular_diameter_source"] == "jmdc"

    def test_a_white_dwarf_takes_its_paper_values(self, tmp_path):
        root = tmp_path / "root"
        p1 = at(0)
        source = gaia_id(*p1, 1)
        stored = gaia.engine_rows(
            gaia.join_fidelity(gaia_stars([gaia_star(source, *p1, 8.5)]), fidelity([])),
            NO_BEST,
        )
        key = ("gaia", "dr3", str(source))
        rows = literature.engine_rows(
            {},
            {},
            {},
            table={},
            radii={},
            measured={
                "teff": {key: Measured(25369, 46, "bond_2017")},
                "logg": {key: Measured(8.591, 0.016, "bond_2017")},
                "mass": {key: Measured(1.018, 0.011, "bond_2017")},
            },
        )
        with IngestRun.start(root, root / "backup") as run:
            run.add(GAIA_DR3, [stored])
            run.add(LITERATURE, [rows])
            run.commit()
        star = int(Registry(root).lookup("gaia", "dr3", [str(source)])[0])
        row = {r["id"]: r for r in table_rows(root, POINT_SOURCE.slug).to_pylist()}[
            star
        ]
        assert (row["teff_literature"], row["paper_teff_source"]) == (
            25369,
            "literature",
        )
        assert row["logg_literature"] == pytest.approx(8.591)
        bounds = (row["mass_literature_lower"], row["mass_literature_upper"])
        assert bounds == pytest.approx((1.007, 1.029))
        assert row["paper_mass_source"] == "literature"

    def test_ingest(self, tmp_path):
        root = tmp_path / "root"
        p1, p2 = at(0), at(120)
        source = gaia_id(*p1, 1)
        stored = gaia.engine_rows(
            gaia.join_fidelity(
                gaia_stars([gaia_star(source, *p1, 5.0), gaia_star(2, *p2, 6.0)]),
                fidelity([]),
            ),
            NO_BEST,
        )
        key = ("gaia", "dr3", str(source))
        rows = literature.engine_rows(
            {},
            {},
            {},
            {key: Distance(2350, 2300, 2400, "expansion", "smith_2006")},
            radii={},
            measured=NO_VALUES,
        )
        # A catalogue distance of the same star ranks below the paper.
        reyle = distances.rows(
            np.array([p1[0]]),
            np.array([p1[1]]),
            [key],
            np.array([100.0]),
            np.array([99.0]),
            np.array([101.0]),
            ["parallax"],
        )
        with IngestRun.start(root, root / "backup") as run:
            run.add(GAIA_DR3, [stored])
            run.add(REYLE_2021, [reyle])
            run.add(LITERATURE, [rows])
            result = run.commit()
        assert result.entry["counts"]["minted"] == 2
        star = int(Registry(root).lookup("gaia", "dr3", [str(source)])[0])
        point = {r["id"]: r for r in table_rows(root, POINT_SOURCE.slug).to_pylist()}
        row = point[star]
        assert (row["distance_source"], row["distance_method"]) == (
            "literature",
            "expansion",
        )
        assert (row["distance"], row["distance_lower"], row["distance_upper"]) == (
            2350,
            2300,
            2400,
        )
        meta = {r["id"]: r for r in table_rows(root, "metadata").to_pylist()}
        assert {
            "catalogue": "literature",
            "release": "star",
            "catalogue_id": f"gaia/dr3/{source}",
        } in meta[star]["cross_ids"]
        # The literature id gives the star an object entry.
        assert meta[star]["object"]
        assert [r["object"] for i, r in meta.items() if i != star] == [False]
