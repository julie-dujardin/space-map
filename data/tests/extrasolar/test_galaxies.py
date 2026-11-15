"""The galaxy list and its ingest pass."""

from dataclasses import replace

import numpy as np
import pyarrow as pa
import pytest

from space_map_data.constants.galaxies.literature import (
    FACTS,
    GALAXIES,
    MILKY_WAY,
    REFERENCES,
    Distance,
    Galaxy,
    Position,
    Text,
    Value,
    galaxy_qids,
)
from space_map_data.export.extrasolar.build import export_extrasolar
from space_map_data.export.extrasolar.reader import ExportReader
from space_map_data.export.swap import ExportRefused
from space_map_data.extrasolar import sky
from space_map_data.extrasolar.engine import IngestRun
from space_map_data.extrasolar.ids import table_of
from space_map_data.extrasolar.match import (
    GALAXY_KIND,
    SYSTEM_KIND,
    Pairs,
    PositionMatcher,
)
from space_map_data.extrasolar.registry import Registry
from space_map_data.extrasolar.sources import galaxies, wikidata
from space_map_data.extrasolar.sources.galaxies import GALAXY_LIST
from space_map_data.extrasolar.sources.wikidata import WIKIDATA
from space_map_data.extrasolar.tables import (
    GALAXY_LITERATURE,
    METADATA,
    REDSHIFT,
    REDSHIFT_TABLE,
    TABLES,
)
from space_map_data.galaxy.geometry import R0
from tests.extrasolar.conftest import HIP, POINT, hip_rows, id_of, table_rows

# A point that moves 10 mas/yr east, 16 years before J2016.0.
SPIRAL = Galaxy(
    "Spiral",
    "Q42",
    Position(100.0, 0.0, 2000.0, 10.0, 0.0, ("position_paper",)),
    Distance(8000.0, 7900.0, 8100.0, "dynamical", ("orbit_paper", "error_paper")),
    morphological_type=Text("SBbc", ("type_paper",)),
    stellar_mass=Value(6e10, 5e10, 7e10, ("mass_paper",)),
    star_formation_rate=Value(2.0, None, None, ("rate_paper",)),
    mean_star_mass=Value(0.5, 0.4, 0.6, ("star_paper",)),
    facts={
        "age": Value(13.0, None, None, ("age_paper",)),
        "planets_per_star": Value(2.0, 1.0, 3.0, ("planet_paper",)),
        "circular_speed": Value(200.0, 190.0, 210.0, ("speed_paper",)),
    },
)
BARE = Galaxy(
    "Bare",
    None,
    Position(200.0, -30.0, 2016.0, 0.0, 0.0, ("position_paper",)),
    Distance(1e6, 9e5, 1.1e6, "dynamical", ("orbit_paper",)),
)
LIST = {"spiral": SPIRAL, "bare": BARE}
NO_ITEMS = pa.table(
    {
        "catalogue_id": pa.array([], pa.string()),
        "match_ra": pa.array([], pa.float64()),
        "match_dec": pa.array([], pa.float64()),
        "claims": pa.array([], galaxies.ITEM_SCHEMA.field("claims").type),
        "name": pa.array([], pa.string()),
        "mint": pa.array([], pa.bool_()),
    }
)


def ingest(root, backup, stars: pa.Table | None = None):
    with IngestRun.start(root, backup, (POINT, REDSHIFT), METADATA) as run:
        if stars is not None:
            run.add(HIP, [stars])
        run.add(GALAXY_LIST, [galaxies.engine_rows(LIST)])
        run.add(WIKIDATA, [galaxies.with_items(NO_ITEMS, LIST)])
        return run.commit()


class TestList:
    """The entries of the galaxy list."""

    def test_the_milky_way(self):
        galaxy = GALAXIES[MILKY_WAY]
        assert (MILKY_WAY, galaxy.name, galaxy.qid) == (
            "milky-way",
            "Milky Way",
            "Q321",
        )
        assert galaxy_qids() == {"Q321"}
        assert galaxy.holds_sun

    def test_its_point_is_sgr_a_at_j2016(self):
        # Xu et al. 2022 at 2020.0, moved back four years.
        ra, dec = galaxies.position(GALAXIES[MILKY_WAY])
        assert ra == pytest.approx(266.4168076, abs=1e-7)
        assert dec == pytest.approx(-29.0078390, abs=1e-7)

    def test_its_distance_is_r0(self):
        distance = GALAXIES[MILKY_WAY].distance
        assert distance.value == R0
        assert (distance.lower, distance.upper) == (R0 - 34, R0 + 34)
        assert distance.references == ("gravity_2022", "gravity_2021")

    def test_the_suns_orbit_is_of_one_fit(self):
        # Reid et al. 2019, Table 3, fit A5: 8.15 ± 0.15 kpc, 236 ± 7 km/s.
        galaxy = GALAXIES[MILKY_WAY]
        assert galaxy.sun_orbit_radius == Value(8150, 8000, 8300, ("reid_2019",))
        assert galaxy.facts["circular_speed"] == Value(236, 229, 243, ("reid_2019",))

    def test_every_value_cites_a_known_work(self):
        for galaxy in GALAXIES.values():
            cited = [*galaxies.cited(galaxy).values()]
            cited += [fact.references for fact in galaxies.facts(galaxy).values()]
            assert all(works for works in cited)
            assert {work for works in cited for work in works} <= set(REFERENCES)

    def test_every_work_is_cited(self):
        galaxy = GALAXIES[MILKY_WAY]
        cited = [*galaxies.cited(galaxy).values()]
        cited += [fact.references for fact in galaxies.facts(galaxy).values()]
        assert {work for works in cited for work in works} == set(REFERENCES)

    def test_references(self):
        for reference in REFERENCES.values():
            assert reference.url.startswith(("https://doi.org/", "https://arxiv.org/"))
            assert reference.short and reference.title

    def test_facts(self):
        for galaxy in GALAXIES.values():
            found = galaxies.facts(galaxy)
            assert set(found) <= set(FACTS)
            for fact in found.values():
                bounds = [b for b in (fact.lower, fact.upper) if b is not None]
                if fact.value is None:
                    # A limit has one bound, a range two.
                    assert bounds == sorted(bounds) and bounds
                elif bounds:
                    assert bounds == sorted(bounds)
                    assert bounds[0] < fact.value < bounds[1]

    def test_the_mean_mass_of_a_star(self):
        # Chabrier 2003, Table 3: 0.047 M☉ pc⁻³ over 0.141 pc⁻³.
        mean = GALAXIES[MILKY_WAY].mean_star_mass
        assert mean is not None
        assert mean[:3] == pytest.approx((0.047 / 0.141, 0.043 / 0.162, 0.051 / 0.120))


class TestEstimates:
    """The facts that the export works out from cited values."""

    def test_the_stars_are_the_stellar_mass_over_the_mean_mass(self):
        stars = galaxies.estimates(SPIRAL)["star_count"]
        # 5e10 / 0.6 to 7e10 / 0.4, to one digit: a range with no value.
        assert stars == Value(
            None, 8e10, 2e11, ("mass_paper", "star_paper"), estimate=True
        )

    def test_the_planets_are_the_stars_times_the_planets_of_a_star(self):
        planets = galaxies.estimates(SPIRAL)["planet_count"]
        assert planets == Value(
            None,
            8e10,
            5e11,
            ("mass_paper", "star_paper", "planet_paper"),
            estimate=True,
        )

    def test_an_end_of_a_range_is_rounded_and_is_not_a_bound(self):
        mass = Value(6e10, 5.2e10, 8.24e10, ("mass_paper",))
        stars = galaxies.estimates(replace(SPIRAL, stellar_mass=mass))["star_count"]
        fewest, most = 5.2e10 / 0.6, 8.24e10 / 0.4
        # 8.67e10 to 2.06e11: each end goes to the nearest digit, here inside
        # the range.
        assert (stars.lower, stars.upper) == (9e10, 2e11)
        assert fewest < 9e10 and 2e11 < most

    def test_the_period_takes_the_radius_and_the_speed_of_one_fit(self):
        assert "orbital_period" not in galaxies.estimates(SPIRAL)
        radius = Value(8000.0, 7900.0, 8100.0, ("speed_paper",))
        home = replace(SPIRAL, sun_orbit_radius=radius)
        period = galaxies.estimates(home)["orbital_period"]
        # 2π · 8000 pc at 200 km/s, then 7900 pc at 210 and 8100 pc at 190.
        assert period[:3] == (246.0, 231.0, 262.0)
        assert period.references == ("speed_paper",)
        # The distance of the point is of another work.
        far = Distance(9000.0, 8900.0, 9100.0, "dynamical", ("orbit_paper",))
        assert galaxies.estimates(replace(home, distance=far)) == (
            galaxies.estimates(home)
        )

    def test_a_galaxy_without_the_inputs_has_none(self):
        assert galaxies.estimates(BARE) == {}

    def test_the_facts_are_those_of_the_list_then_the_estimates(self):
        assert list(galaxies.facts(SPIRAL)) == [
            "age",
            "planets_per_star",
            "circular_speed",
            "star_count",
            "planet_count",
        ]

    def test_the_milky_way(self):
        found = galaxies.estimates(GALAXIES[MILKY_WAY])
        stars, planets, period = (
            found[name] for name in ("star_count", "planet_count", "orbital_period")
        )
        assert stars[:3] == (None, 1e11, 2e11)
        assert stars.references == ("cautun_2020", "chabrier_2003")
        assert planets[:3] == (None, 8e10, 5e11)
        assert planets.references == ("cautun_2020", "chabrier_2003", "cassan_2012")
        # 2π · 8.15 kpc at 236 km/s, then 8.00 kpc at 243 and 8.30 kpc at 229.
        assert (period.value, period.lower, period.upper) == (212.0, 202.0, 223.0)
        assert period.references == ("reid_2019",)
        assert all(fact.estimate for fact in found.values())


class TestTable:
    """The Redshift table."""

    def test_it_is_table_4(self):
        assert (REDSHIFT.number, REDSHIFT.slug) == (4, "redshift")
        assert TABLES[-1] is REDSHIFT

    def test_each_group_has_its_source_column(self):
        names = REDSHIFT.schema.names
        for group in REDSHIFT.groups:
            assert group.sources == (GALAXY_LITERATURE,)
            assert names[names.index(group.names[-1]) + 1] == group.source_column

    def test_the_source_fills_every_group(self):
        assert set(galaxies.GROUP_FIELDS) == {group.name for group in REDSHIFT.groups}


class TestKind:
    """A galaxy is never the match of a star or a system, also with no kind."""

    def test_kinds(self):
        kinds = ["star", None, SYSTEM_KIND, GALAXY_KIND]
        n = len(kinds)
        pairs = Pairs(
            separation=np.zeros(n),
            row_error=np.full(n, 0.1),
            row_size=np.full(n, np.nan),
            row_mag=np.full(n, np.nan),
            row_kind=pa.array(kinds),
            key_error=np.full(n, 0.1),
            key_size=np.full(n, np.nan),
            key_mag=np.full(n, np.nan),
            key_kind=pa.array([GALAXY_KIND] * n),
        )
        score = PositionMatcher().score(pairs)
        assert np.isnan(score[:3]).all()
        assert np.isfinite(score[3])


class TestRows:
    """The rows of the pass."""

    def test_the_point_is_at_j2016(self):
        assert galaxies.position(SPIRAL) == pytest.approx((100.0 + 0.16 / 3600, 0.0))
        assert galaxies.position(BARE) == pytest.approx((200.0, -30.0))

    def test_values(self):
        rows = galaxies.engine_rows(LIST)
        assert rows.schema == galaxies.SCHEMA
        spiral, bare = rows.to_pylist()
        assert spiral["catalogue_id"] == "spiral" and spiral["mint"]
        assert (spiral["match_ra"], spiral["match_dec"]) == (
            spiral["ra"],
            spiral["dec"],
        )
        assert (spiral["name"], spiral["class"]) == ("Spiral", "galaxy")
        assert (spiral["distance"], spiral["distance_method"]) == (8000.0, "dynamical")
        assert (spiral["distance_lower"], spiral["distance_upper"]) == (7900.0, 8100.0)
        assert spiral["morphological_type"] == "SBbc"
        assert spiral["stellar_mass"] == pytest.approx(6e10)
        assert spiral["stellar_mass_lower"] == pytest.approx(5e10)
        assert spiral["total_mass"] is None
        assert spiral["star_formation_rate"] == 2.0
        assert spiral["star_formation_rate_upper"] is None
        assert bare["stellar_mass"] is None and bare["morphological_type"] is None

    def test_the_works_by_group(self):
        assert galaxies.cited(SPIRAL) == {
            "position": ("position_paper",),
            "distance": ("orbit_paper", "error_paper"),
            "morphology": ("type_paper",),
            "stellar_mass": ("mass_paper",),
            "star_formation_rate": ("rate_paper",),
        }

    def test_the_item_claims_the_galaxy_by_its_key(self):
        rows = galaxies.with_items(NO_ITEMS, LIST).to_pylist()
        assert [row["catalogue_id"] for row in rows] == ["Q42"]
        assert rows[0]["claims"] == [
            {"catalogue": "galaxy", "release": "key", "catalogue_id": "spiral"}
        ]
        assert not rows[0]["mint"] and rows[0]["name"] is None

    def test_an_item_of_the_list_is_the_galaxys(self):
        star = pa.table(
            {
                "catalogue_id": ["Q42", "Q7"],
                "match_ra": [1.0, 2.0],
                "match_dec": [1.0, 2.0],
                "claims": pa.array(
                    [
                        [{"catalogue": "hip", "release": "2007", "catalogue_id": n}]
                        for n in ("1", "2")
                    ],
                    NO_ITEMS.schema.field("claims").type,
                ),
                "name": ["Wrong", "Star"],
                "mint": [False, False],
            }
        )
        rows = galaxies.with_items(star, LIST).to_pylist()
        assert [(row["catalogue_id"], row["name"]) for row in rows] == [
            ("Q7", "Star"),
            ("Q42", None),
        ]


class TestIngest:
    """The pass mints each galaxy once, in table 4."""

    def test_a_galaxy_has_an_id_of_table_4_in_the_cell_of_its_point(self, root, backup):
        ingest(root, backup)
        id_ = id_of(root, GALAXY_LIST, "spiral")
        assert table_of(id_) == REDSHIFT_TABLE
        ra, dec = galaxies.position(SPIRAL)
        assert id_ & 0xFFFFFF == int(sky.cells(np.array([ra]), np.array([dec]))[0])

    def test_rows(self, root, backup):
        ingest(root, backup)
        spiral = id_of(root, GALAXY_LIST, "spiral")
        (row,) = (
            r for r in table_rows(root, "redshift").to_pylist() if r["id"] == spiral
        )
        assert (row["distance"], row["distance_source"]) == (8000.0, GALAXY_LITERATURE)
        assert (row["morphological_type"], row["morphology_source"]) == (
            "SBbc",
            GALAXY_LITERATURE,
        )
        assert row["total_mass"] is None and row["total_mass_source"] is None
        meta = {r["id"]: r for r in table_rows(root, "metadata").to_pylist()}
        found = meta[spiral]
        assert (found["name"], found["name_source"]) == ("Spiral", GALAXY_LITERATURE)
        assert (found["class"], found["class_source"]) == ("galaxy", GALAXY_LITERATURE)
        assert found["mask"] == 1 << REDSHIFT_TABLE
        assert found["cross_ids"] == [
            {"catalogue": "galaxy", "release": "key", "catalogue_id": "spiral"},
            {"catalogue": "wikidata", "release": "qid", "catalogue_id": "Q42"},
        ]

    def test_a_galaxy_of_the_list_has_an_entry_with_no_item_too(self, root, backup):
        ingest(root, backup)
        meta = {r["id"]: r for r in table_rows(root, "metadata").to_pylist()}
        assert meta[id_of(root, GALAXY_LIST, "spiral")]["object"]
        assert meta[id_of(root, GALAXY_LIST, "bare")]["object"]

    def test_the_next_ingest_keeps_the_id(self, root, backup):
        ingest(root, backup)
        first = id_of(root, GALAXY_LIST, "spiral")
        result = ingest(root, backup)
        assert id_of(root, GALAXY_LIST, "spiral") == first
        assert result.entry["counts"]["minted"] == 0
        assert Registry(root).last_ingest == 2

    def test_the_milky_way_with_the_star_tables_and_the_star_items(self, root, backup):
        items = galaxies.with_items(wikidata.engine_rows([], {}, {}))
        with IngestRun.start(root, backup) as run:
            run.add(GALAXY_LIST, [galaxies.engine_rows()])
            run.add(WIKIDATA, [items])
            run.commit()
        id_ = id_of(root, GALAXY_LIST, MILKY_WAY)
        (row,) = table_rows(root, "redshift").to_pylist()
        assert (row["id"], row["distance"]) == (id_, R0)
        assert row["morphological_type"] == "SAB(rs)bc"
        (meta,) = table_rows(root, "metadata").to_pylist()
        assert (meta["name"], meta["class"], meta["object"]) == (
            "Milky Way",
            "galaxy",
            True,
        )
        assert meta["cross_ids"] == [
            {"catalogue": "galaxy", "release": "key", "catalogue_id": "milky-way"},
            {"catalogue": "wikidata", "release": "qid", "catalogue_id": "Q321"},
        ]
        assert id_of(root, WIKIDATA, "Q321") == id_

    def test_the_export_names_the_galaxy_of_the_sun(self, root, backup, tmp_path):
        with IngestRun.start(root, backup) as run:
            run.add(GALAXY_LIST, [galaxies.engine_rows()])
            run.commit()
        id_ = id_of(root, GALAXY_LIST, MILKY_WAY)
        with Registry(root).reader() as registry:
            assert galaxies.home_galaxy(registry) == id_
            assert galaxies.home_galaxy(registry, LIST) is None
        export_extrasolar(root, tmp_path / "out", workers=1)
        metadata = ExportReader(tmp_path / "out" / "v1" / "x").metadata
        assert metadata["home_galaxy"] == id_
        assert metadata["objects"]["galaxy"]["count"] == 1

    def test_a_registry_with_no_galaxy_names_none(self, root, backup, tmp_path):
        star = hip_rows([{"id": 1, "ra": 10.0, "dec": 10.0, "mag": 5.0}])
        with IngestRun.start(root, backup, (POINT, REDSHIFT), METADATA) as run:
            run.add(HIP, [star])
            run.commit()
        with Registry(root).reader() as registry:
            assert galaxies.home_galaxy(registry) is None

    def test_a_registry_with_other_galaxies_names_none(self, root, backup):
        ingest(root, backup)
        with Registry(root).reader() as registry:
            assert galaxies.home_galaxy(registry) is None

    def test_a_point_that_left_the_region_of_the_id_refuses_the_export(
        self, root, backup, tmp_path, monkeypatch
    ):
        with IngestRun.start(root, backup) as run:
            run.add(GALAXY_LIST, [galaxies.engine_rows()])
            run.commit()
        id_ = id_of(root, GALAXY_LIST, MILKY_WAY)
        elsewhere = Position(100.0, 0.0, 2016.0, 0.0, 0.0, ("xu_2022",))
        moved = replace(GALAXIES[MILKY_WAY], position=elsewhere)
        with (
            Registry(root).reader() as registry,
            pytest.raises(galaxies.GalaxyMoved, match=f"ID {id_} of region"),
        ):
            galaxies.home_galaxy(registry, {MILKY_WAY: moved})
        monkeypatch.setitem(GALAXIES, MILKY_WAY, moved)
        with pytest.raises(ExportRefused, match="galaxy of the Sun"):
            export_extrasolar(root, tmp_path / "out", workers=1)
        assert not (tmp_path / "out" / "v1" / "x").exists()

    def test_a_star_at_the_point_is_another_object(self, root, backup):
        ra, dec = galaxies.position(SPIRAL)
        star = hip_rows([{"id": 1, "ra": ra, "dec": dec, "mag": 5.0}])
        # The galaxy is in the registry when the star's matcher looks.
        ingest(root, backup)
        ingest(root, backup, star)
        spiral, found = id_of(root, GALAXY_LIST, "spiral"), id_of(root, HIP, 1)
        assert found != spiral
        assert (table_of(found), table_of(spiral)) == (1, REDSHIFT_TABLE)
        assert spiral in table_rows(root, "redshift")["id"].to_pylist()
