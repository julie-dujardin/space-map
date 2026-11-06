"""Tests for engine extensions and the exoplanet ingest through the engine."""

from dataclasses import dataclass, field
from typing import cast

import numpy as np
import pyarrow as pa
import pytest

from space_map_data.constants.stars.planet_hosts import HOSTS, STARS
from space_map_data.extrasolar import sky
from space_map_data.extrasolar.engine import ExtensionResult, IngestRun
from space_map_data.extrasolar.exoplanets import catalogues, twins
from space_map_data.extrasolar.exoplanets import ingest as exoplanets
from space_map_data.extrasolar.exoplanets.catalogues import (
    ARCHIVE,
    EU,
    OEC,
    check_papers,
    citation,
)
from space_map_data.extrasolar.exoplanets.names import WgsnName
from space_map_data.extrasolar.exoplanets.table import default_node
from space_map_data.extrasolar.registry import Registry
from space_map_data.extrasolar.sources import gaia, hipparcos, simbad
from space_map_data.extrasolar.sources.gaia import (
    GAIA_DR3,
    GAIA_DR3_NAMED,
    BestNeighbours,
)
from space_map_data.extrasolar.sources.hipparcos import HIPPARCOS
from space_map_data.extrasolar.sources.simbad import SIMBAD, SimbadList
from tests.extrasolar.conftest import (
    GAIA,
    META,
    POINT,
    centre,
    gaia_rows,
    offset,
    table_rows,
)
from tests.extrasolar.exoplanet_files import Downloads, archive_planet, eu_planet
from tests.extrasolar.test_gaia_orbits import build as build_orbits
from tests.extrasolar.test_gaia_orbits import solution
from tests.extrasolar.test_simbad import star as simbad_star
from tests.extrasolar.test_simbad import write_simbad
from tests.extrasolar.test_stars import fidelity, gaia_star, gaia_stars, hip_stars

RA, DEC = centre(4_000_777)
OEC_TABLE = ("open_exoplanet_catalogue", "systems")
NO_NEIGHBOURS = BestNeighbours(np.zeros(0, np.int64), np.zeros(0, np.int64))
# An orbit of the unpositionable host source 202.
HOST_ORBITS = build_orbits([solution(202, "SB1")])
HOST_GOLDEN_SAMPLE = gaia.GoldenSample(np.array([202], np.int64))


def at(arcsec: float, angle: float = 0.0) -> tuple[float, float]:
    return offset(RA, DEC, arcsec, angle)


@dataclass
class Tagger:
    """An extension that files one row per Gaia row under its ID."""

    name: str = "tags"
    sources: tuple[str, ...] = (GAIA.name,)
    unreviewed: int = 0
    fail: bool = False
    seen: dict | None = None

    def build(self, registry, ids, ingest, complete) -> ExtensionResult:
        if self.fail:
            raise RuntimeError("extension failed")
        self.seen = {k: v.to_pylist() for k, v in ids.items()}
        rows = ids[GAIA.name].filter(pa.array(ids[GAIA.name]["id"].to_numpy() > 0))
        return ExtensionResult(
            parts={},
            tables={"tags": rows.rename_columns(["tag", "host"])},
            key="host",
            counts={"tags": rows.num_rows},
            report="tags written\n",
            unreviewed=self.unreviewed,
        )


class TestExtension:
    """The engine gives an extension the IDs and commits what it returns."""

    def rows(self):
        return gaia_rows(
            [
                {"id": 1, "ra": RA, "dec": DEC, "mag": 5.0},
                {"id": 2, "ra": at(5)[0], "dec": at(5)[1], "mint": False},
            ]
        )

    def test_ids_tables_and_report(self, root, backup):
        tagger = Tagger(unreviewed=1)
        with IngestRun.start(root, backup, (POINT,), META) as run:
            run.add(GAIA, [self.rows()])
            run.extend(tagger)
            result = run.commit()
        registry = Registry(root)
        assert tagger.seen is not None
        assert sorted(r["catalogue_id"] for r in tagger.seen[GAIA.name]) == ["1", "2"]
        unminted = [r for r in tagger.seen[GAIA.name] if r["catalogue_id"] == "2"]
        assert unminted[0]["id"] == 0
        assert registry.manifest["tables"]["tags"] == 1
        tags = table_rows(root, "tags")
        assert tags["tag"].to_pylist() == ["1"]
        assert tags["host"].to_pylist() == table_rows(root, "point")["id"].to_pylist()
        assert result.entry["extensions"] == {"tags": {"tags": 1, "unreviewed": 1}}
        assert "tags written" in result.report
        assert registry.unreviewed() == [1]

    def test_a_failing_extension_leaves_nothing(self, root, backup):
        with IngestRun.start(root, backup, (POINT,), META) as run:
            run.add(GAIA, [self.rows()])
            run.extend(Tagger(fail=True))
            with pytest.raises(RuntimeError):
                run.commit()
        registry = Registry(root)
        assert registry.ingests == []
        assert not (root / "tables" / "tags" / "000001").exists()
        assert not (root / "tables" / "point" / "000001").exists()

    def test_an_extension_needs_its_passes(self, root, backup):
        with (
            IngestRun.start(root, backup, (POINT,), META) as run,
            pytest.raises(ValueError, match="no pass of"),
        ):
            run.extend(Tagger())


DELTA_A, DELTA_B = at(240, 45), at(250, 45)
ZETA = at(300, 135)
PULSAR = at(420, 60)


BETA = at(60, 90)


def _sexagesimal(value: float, sign: bool = False) -> str:
    """OEC's "hh mm ss.ss" or "+dd mm ss.s"."""
    text = "-" if value < 0 else ("+" if sign else "")
    value = abs(value)
    degrees, rest = divmod(value * 3600, 3600)
    minutes, seconds = divmod(rest, 60)
    return f"{text}{int(degrees):02d} {int(minutes):02d} {seconds:06.3f}"


def downloads() -> Downloads:
    alpha, beta, lens, gamma = at(0), BETA, at(120, 180), at(180, 270)
    files = Downloads()
    files.archive = [
        archive_planet(
            "3.1",
            "Alpha b",
            "Alpha",
            "2.1",
            *alpha,
            gaia_dr3_id="Gaia DR3 101",
            pl_orbper="10",
            pl_bmassj="1.0",
            pl_tranmid="2455000.5",
            pl_orbincl="88",
            st_mass="1.0",
            sy_gaiamag="9.0",
            sy_dist="50",
        ),
        archive_planet(
            "3.2",
            "Alpha c",
            "Alpha",
            "2.1",
            *alpha,
            gaia_dr3_id="Gaia DR3 101",
            pl_orbper="100",
            pl_bmassj="2.0",
            pl_bmassprov="Msini",
            discoverymethod="Radial Velocity",
        ),
        archive_planet(
            "3.3",
            "Beta b",
            "Beta",
            "2.2",
            *beta,
            gaia_dr3_id="Gaia DR3 202",
            pl_orbper="5",
            pl_bmassj="20",
            st_mass="0.8",
            sy_dist="300",
        ),
        archive_planet(
            "3.4",
            "OGLE-2020-BLG-7L b",
            "OGLE-2020-BLG-7L",
            "2.3",
            *lens,
            discoverymethod="Microlensing",
            pl_orbsmax="2.0",
            pl_bmassj="0.3",
            st_mass="0.5",
            sy_dist="4000",
        ),
        # A planet around each star of a binary.
        archive_planet(
            "3.5",
            "Delta A b",
            "Delta A",
            "2.5",
            *DELTA_A,
            gaia_dr3_id="Gaia DR3 404",
            sy_name="Delta",
            pl_orbper="4",
        ),
        archive_planet(
            "3.6",
            "Delta B b",
            "Delta B",
            "2.6",
            *DELTA_B,
            gaia_dr3_id="Gaia DR3 505",
            sy_name="Delta",
            pl_orbper="6",
        ),
    ]
    files.eu = [
        eu_planet("Alpha b", "Alpha", *alpha, orbital_period="10.02"),
        eu_planet("Alpha c", "Alpha", *alpha, orbital_period="101", mass="2.5"),
        eu_planet("Alpha d", "Alpha", *alpha, orbital_period="900", mass="70"),
        eu_planet(
            "Gamma b",
            "Gamma",
            *gamma,
            orbital_period="3",
            mass="0.5",
            star_distance="80",
        ),
    ]
    files.oec = [
        (
            "<system><name>Alpha</name><star><name>Alpha</name>"
            "<planet><name>Alpha b</name><period>10.0</period>"
            "<ascendingnode>33</ascendingnode><list>Confirmed planets</list>"
            "</planet></star></system>"
        )
    ]
    files.simbad_names = [
        ("exoplanet_eu", "catalog", "star", "Gamma", "Gamma", "printed", "33"),
    ]
    files.simbad_basic = {"33": ("Gamma", "*")}
    files.simbad_ids = {"33": ["Gaia DR3 303", "NAME Gamma"]}
    files.gaia_sources = [
        {
            "source_id": 202,
            "ra": beta[0],
            "dec": beta[1],
            "ra_error": 0.5,
            "dec_error": 0.5,
            "parallax": 0.2,
            "parallax_error": 0.3,
            "parallax_over_error": 0.67,
            "phot_g_mean_mag": 15.0,
        }
    ]
    files.fidelity = [{"source_id": 202, "fidelity_v2": 0.8, "norm_dg": 0.0}]
    files.astrophysical = [
        {
            "source_id": 202,
            "radius_gspphot": 1.1,
            "radius_gspphot_lower": 1.0,
            "radius_gspphot_upper": 1.2,
            "mh_gspspec": 0.1,
            "fem_gspspec": 0.05,
            "logg_gspspec": 4.4,
            "flags_gspspec": "0" * 41,
        }
    ]
    files.xgboost = [
        {"source_id": 202, "mh_xgboost": -0.3, "in_vetted_rgb_sample": "false"}
    ]
    files.names = [
        {
            "edition": 2019,
            "row": 0,
            "kind": "star",
            "designation": "Alpha",
            "name": "Prima",
        },
        {
            "edition": 2019,
            "row": 0,
            "kind": "planet",
            "designation": "Alpha b",
            "name": "Primus",
        },
    ]
    return files


def gaia_pass(*more: dict) -> pa.Table:
    zeta = gaia_star(606, *ZETA, 11.0) | {
        "phot_bp_mean_mag": 11.4,
        "phot_rp_mean_mag": 10.6,
    }
    stars = gaia_stars(
        [
            gaia_star(101, *at(0.1), 9.0),
            gaia_star(303, *at(180, 270), 12.0),
            gaia_star(404, *DELTA_A, 10.0),
            gaia_star(505, *DELTA_B, 11.0),
            zeta,
            *more,
        ]
    )
    return gaia.engine_rows(
        gaia.join_fidelity(stars, fidelity([(101, 0.9), (303, 0.2)])), NO_NEIGHBOURS
    )


def ingest(
    root,
    backup,
    inputs,
    complete=True,
    systems=None,
    stars=None,
    simbad_rows=None,
    oids=None,
):
    with IngestRun.start(root, backup) as run:
        reader = gaia.GaiaReader(
            NO_NEIGHBOURS, orbits=HOST_ORBITS, golden_sample=HOST_GOLDEN_SAMPLE
        )
        read = exoplanets.read(reader, inputs)
        run.add(GAIA_DR3, [gaia_pass() if stars is None else stars], complete)
        run.add(GAIA_DR3_NAMED, [read.gaia_rows], complete)
        if simbad_rows is not None:
            run.add(SIMBAD, [simbad_rows], complete)
            if oids is None:
                oids = set(simbad_rows["catalogue_id"].to_pylist())
        prepared = exoplanets.prepare(read, run, {}, inputs, simbad_rows=oids or ())
        exoplanets.add_passes(run, prepared, complete)
        run.extend(exoplanets.PlanetsExtension(prepared, systems))
        return run.commit(), prepared


@dataclass
class StarSystems:
    """Star systems with no circumbinary host, and the root of some IDs."""

    roots: dict[int, int]
    stars: dict[int, int] = field(default_factory=dict)
    as_star: set[int] = field(default_factory=set)

    def host(self, record: int) -> int:
        return 0

    def star(self, record: int) -> int:
        return self.stars.get(record, 0)

    def drawn_as_star(self, record: int) -> bool:
        return record in self.as_star

    def root(self, id_: int) -> int:
        return self.roots.get(id_, 0)

    def node(self, id_: int) -> float | None:
        return None


class TestStarSystemRoots:
    def test_the_key_of_a_planet_system_takes_its_root(self, root, backup, tmp_path):
        """Delta A, the key of the Delta planets, is in a star system, and
        Delta B is in none. The planets of both go to the file of the root."""
        inputs = downloads().write(tmp_path / "one")
        ingest(root, backup, inputs)
        delta_a, delta_b = Registry(root).lookup("gaia", "dr3", ["404", "505"])
        system = 999
        ingest(root, backup, inputs, systems=StarSystems({int(delta_a): system}))
        planets = {
            r["host"]: r["system"] for r in table_rows(root, "planets").to_pylist()
        }
        assert planets[delta_a] == system and planets[delta_b] == system

    def test_a_record_names_the_star_that_it_also_is(self, root, backup, tmp_path):
        """The record stays on its host, and names its star and the side that
        is drawn."""
        inputs = downloads().write(tmp_path / "one")
        ingest(root, backup, inputs)
        (star,) = Registry(root).lookup("gaia", "dr3", ["505"])
        ingest(
            root,
            backup,
            inputs,
            systems=StarSystems({}, {0: int(star)}, {0}),
        )
        rows = table_rows(root, "planets").to_pylist()
        (record,) = [row for row in rows if row["star"] is not None]
        assert record["star"] == star and record["host"] != star
        assert record["as_star"] is True
        assert {row["as_star"] for row in rows if row["star"] is None} == {None}


class TestExoplanetIngest:
    """Hosts get IDs through the engine, planets get numbers at commit."""

    def test_two_ingests(self, root, backup, tmp_path):
        files = downloads()
        # One item names Alpha b; the other names two planets.
        files.wikidata_items = [
            ("Q100", ["Alpha b"], [], 3),
            ("Q101", ["Alpha c", "Beta b"], [], 9),
        ]
        result, _ = ingest(root, backup, files.write(tmp_path / "one"))

        def id_of(catalogue, release, value):
            return int(Registry(root).lookup(catalogue, release, [value])[0])

        alpha = id_of("gaia", "dr3", "101")
        beta = id_of("gaia", "dr3", "202")
        gamma = id_of("gaia", "dr3", "303")
        delta_a = id_of("gaia", "dr3", "404")
        delta_b = id_of("gaia", "dr3", "505")
        lens = id_of(ARCHIVE, "pscomppars", "2.3")
        assert 0 not in (alpha, beta, gamma, delta_a, delta_b, lens)
        assert id_of(ARCHIVE, "pscomppars", "2.1") == alpha
        assert id_of(EU, "catalog", "Alpha") == alpha
        assert id_of(OEC, "systems", "Alpha") == alpha
        assert id_of(EU, "catalog", "Gamma") == gamma

        meta = {r["id"]: r for r in table_rows(root, "metadata").to_pylist()}
        point = {r["id"]: r for r in table_rows(root, "point-source").to_pylist()}
        assert meta[alpha]["name"] == "Prima"
        assert meta[beta]["name"] == "Beta"
        assert meta[lens]["name"] == "OGLE-2020-BLG-7L"
        assert point[beta]["astrometry_source"] == GAIA_DR3_NAMED.name
        assert point[beta]["host_distance"] == 300
        assert point[beta]["radius_gspphot"] == pytest.approx(1.1)
        # An empty cell of the companion files is no value, also in a text column.
        assert point[beta]["libname_gspphot"] is None
        assert point[beta]["flame_source"] is None
        assert point[beta]["flame_spec_source"] is None
        assert point[beta]["feh_gspspec_calibrated"] is not None
        assert point[beta]["mh_xgboost"] == pytest.approx(-0.3)
        assert point[beta]["in_vetted_rgb_sample"] is False
        assert point[beta]["in_oba_golden_sample"] is True
        assert point[beta]["oba_golden_sample_source"] == GAIA_DR3_NAMED.name
        assert point[gamma]["radius_gspphot"] is None
        assert point[gamma]["mh_xgboost"] is None
        [orbit] = table_rows(root, "binary-orbit").to_pylist()
        assert (orbit["id"], orbit["nss_solution_type"]) == (beta, "SB1")
        assert point[lens]["astrometry_source"] == ARCHIVE
        assert point[lens]["host_star_source"] == ARCHIVE
        assert point[gamma]["fidelity_v2"] == pytest.approx(0.2)
        assert point[gamma]["host_star_source"] == EU

        planets = {
            (r["host"], r["number"]): r for r in table_rows(root, "planets").to_pylist()
        }
        assert set(planets) == {
            (alpha, 1),
            (alpha, 2),
            (beta, 1),
            (gamma, 1),
            (delta_a, 1),
            (delta_b, 1),
            (lens, 1),
        }
        b = planets[(alpha, 1)]
        assert (b["name"], b["designation"], b["system"]) == (
            "Primus",
            "Alpha b",
            alpha,
        )
        assert b["cross_ids"][-1] == {
            "catalogue": "wikidata",
            "release": "qid",
            "catalogue_id": "Q100",
        }
        assert not any(
            c["catalogue"] == "wikidata"
            for key, row in planets.items()
            if key != (alpha, 1)
            for c in row["cross_ids"]
        )
        # Each planet of a binary is under its own star, in one system.
        assert planets[(delta_b, 1)]["designation"] == "Delta B b"
        assert planets[(delta_a, 1)]["system"] == delta_a
        assert planets[(delta_b, 1)]["system"] == delta_a
        # The assumed orbits of one system share one plane.
        assert planets[(delta_b, 1)]["node"] == default_node(delta_a)
        assert planets[(delta_a, 1)]["node"] == default_node(delta_a)
        assert (b["node"], b["sky_source"]) == (33.0, OEC)
        assert planets[(alpha, 2)]["mass_kind"] == "true"
        assert planets[(alpha, 2)]["mass_source"] == EU
        assert planets[(beta, 1)]["class"] == "brown dwarf"
        assert planets[(lens, 1)]["computed"] == ["period"]
        assert "node" in planets[(lens, 1)]["assumed"]
        assert result.entry["extensions"]["planets"]["new"] == 7
        assert "Exoplanets" in result.report and "above 60 MJ 1" in result.report
        assert "Wikidata: 1 planets have an item" in result.report
        assert "Wikidata items whose ids name several planets: 1\n  Q101" in (
            result.report
        )

        # The next ingest: Alpha c is gone, Alpha e is new, and Zeta, a host
        # without ids, is the Gaia star 0.8″ away.
        files.archive = [r for r in files.archive if r["pl_name"] != "Alpha c"]
        files.eu = [r for r in files.eu if r["name"] != "Alpha c"]
        files.archive.append(
            archive_planet(
                "3.9",
                "Alpha e",
                "Alpha",
                "2.1",
                *at(0),
                gaia_dr3_id="Gaia DR3 101",
                pl_orbper="400",
            )
        )
        files.eu.append(
            eu_planet(
                "Zeta b",
                "Zeta",
                *offset(*ZETA, 0.8, 30),
                orbital_period="7",
                mag_v="11.2",
                star_distance="100",
            )
        )
        # OEC lists Beta under another name, which no id joins.
        files.oec.append(
            "<system><name>2M Beta</name><star><name>2M Beta</name>"
            "<planet><name>2M Beta b</name><period>5.0</period>"
            "<list>Confirmed planets</list></planet></star>"
            f"<rightascension>{_sexagesimal(BETA[0] / 15)}</rightascension>"
            f"<declination>{_sexagesimal(BETA[1], sign=True)}</declination>"
            "</system>"
        )
        again, prepared = ingest(root, backup, files.write(tmp_path / "two"))
        assert again.entry["counts"]["minted"] == 0
        assert id_of(EU, "catalog", "Zeta") == id_of("gaia", "dr3", "606")
        assert sorted(t.name for t in prepared.twins.targets) == ["2M Beta", "Zeta"]
        assert "check: twins" in again.report
        assert id_of(OEC, "systems", "2M Beta") == beta
        assert prepared.twins.joined == [
            "2M Beta (open-exoplanet-catalogue) is Beta: the same component"
        ]
        beta_planets = [
            r for r in table_rows(root, "planets").to_pylist() if r["host"] == beta
        ]
        assert [r["designation"] for r in beta_planets] == ["Beta b"]
        planets = {
            (r["host"], r["number"]): r["designation"]
            for r in table_rows(root, "planets").to_pylist()
        }
        assert planets[(alpha, 1)] == "Alpha b"
        assert planets[(alpha, 3)] == "Alpha e"
        assert (alpha, 2) not in planets
        assert again.entry["extensions"]["planets"]["retired"] == 1
        assert Registry(root).unreviewed() == []


class TestHostsFromPapers:
    """A host of `planet_hosts` keeps its one point through the engine."""

    def simbad_rows(self, tmp_path):
        # GJ 229 B: no Gaia DR3 id and no HIP number.
        directory = write_simbad(
            tmp_path / "simbad-stars",
            [
                simbad_star(
                    864867,
                    92.64434,
                    -21.86984,
                    "HD 42581B",
                    otype="BD*",
                    plx_value=173.19,
                    plx_err=0.1,
                )
            ],
        )
        stars = SimbadList.read(directory)
        return simbad.engine_rows(stars, stars.handed(), set(), {}, {})[0]

    def gj_229_b(self, root, backup, tmp_path, name):
        files = downloads()
        # The rows name the primary, 8″ from B.
        files.eu += [
            eu_planet(
                "GJ 229 Ba", "GJ 229", 92.64423, -21.86464, orbital_period="12.1346"
            ),
            eu_planet(
                "GJ 229 Bb", "GJ 229", 92.64423, -21.86464, orbital_period="12.1346"
            ),
        ]
        return ingest(
            root,
            backup,
            files.write(tmp_path / name),
            simbad_rows=self.simbad_rows(tmp_path / name),
        )

    def test_a_simbad_key_claims_its_point(self, root, backup, tmp_path):
        result, _ = self.gj_229_b(root, backup, tmp_path, "one")
        assert result.entry["counts"]["conflicts"] == 0
        registry = Registry(root)
        point = int(registry.lookup("simbad", "oid", ["864867"])[0])
        assert point
        assert int(registry.lookup(EU, "catalog", ["GJ 229 B"])[0]) == point
        planets = table_rows(root, "planets").to_pylist()
        rows = [p for p in planets if p["designation"].startswith("GJ 229 B")]
        assert [(p["host"], p["number"]) for p in rows] == [(point, 1), (point, 2)]
        assert [p["letter"] for p in rows] == [None, None]

    def test_it_mints_no_second_star(self, root, backup, tmp_path):
        self.gj_229_b(root, backup, tmp_path, "one")
        rows = table_rows(root, "point-source").to_pylist()
        near = [
            row
            for row in rows
            if abs(row["ra"] - 92.6443) < 0.01 and abs(row["dec"] + 21.87) < 0.01
        ]
        assert [row["id"] for row in near] == [
            int(Registry(root).lookup("simbad", "oid", ["864867"])[0])
        ]

    def test_the_point_keeps_simbads_astrometry(self, root, backup, tmp_path):
        self.gj_229_b(root, backup, tmp_path, "one")
        point = int(Registry(root).lookup("simbad", "oid", ["864867"])[0])
        rows = table_rows(root, "point-source").to_pylist()
        row = next(r for r in rows if r["id"] == point)
        assert row["astrometry_source"] == "simbad"
        assert row["parallax"] == pytest.approx(173.19)
        assert row["ra"] == pytest.approx(92.64434)

    def test_the_next_ingest_keeps_the_point(self, root, backup, tmp_path):
        self.gj_229_b(root, backup, tmp_path, "one")
        registry = Registry(root)
        point = int(registry.lookup("simbad", "oid", ["864867"])[0])
        result, _ = self.gj_229_b(root, backup, tmp_path, "two")
        assert result.entry["counts"]["conflicts"] == 0
        assert int(Registry(root).lookup(EU, "catalog", ["GJ 229 B"])[0]) == point
        rows = table_rows(root, "planets").to_pylist()
        assert sum(p["host"] == point for p in rows) == 2

    def test_a_catalogue_star_keeps_its_values(self, root, backup, tmp_path):
        files = downloads()
        files.oec = [
            """<system><name>GJ 229</name>
            <rightascension>06 10 34.6</rightascension>
            <declination>-21 51 52.7</declination><distance>5.75</distance>
            <binary><star><name>GJ 229</name></star>
            <star><name>GJ 229 B</name><spectraltype>T6</spectraltype></star>
            </binary></system>"""
        ]
        files.simbad_names = [
            (*OEC_TABLE, "star", "GJ 229 B", "GJ 229 B", "printed", "864867")
        ]
        files.simbad_basic = {"864867": ("HD 42581B", "BD*")}
        files.eu.append(
            eu_planet("GJ 229 Bb", "GJ 229", 92.64423, -21.86464, orbital_period="12")
        )
        result, _ = ingest(
            root,
            backup,
            files.write(tmp_path / "one"),
            simbad_rows=self.simbad_rows(tmp_path),
        )
        assert result.entry["counts"]["conflicts"] == 0
        registry = Registry(root)
        point = int(registry.lookup("simbad", "oid", ["864867"])[0])
        assert int(registry.lookup(OEC, "systems", ["GJ 229 B"])[0]) == point
        assert not registry.lookup(EU, "catalog", ["GJ 229 B"])[0]
        rows = table_rows(root, "point-source").to_pylist()
        row = next(r for r in rows if r["id"] == point)
        assert row["host_star_source"] == OEC
        assert row["host_spectral_type"] == "T6"
        assert row["astrometry_source"] == "simbad"

    def nltt_31450(self):
        files = downloads()
        # The row has NLTT 730's star and position, on the other side of the sky.
        files.eu.append(eu_planet("NLTT 31450 b", "NLTT 730", 3.77, 29.93))
        dr3 = 1514394443389500288
        return files, dr3, gaia_pass(gaia_star(dr3, 189.95550, 32.14722, 13.6))

    def test_a_claim_reaches_a_star_far_from_the_row(self, root, backup, tmp_path):
        files, dr3, stars = self.nltt_31450()
        result, _ = ingest(root, backup, files.write(tmp_path / "one"), stars=stars)
        assert result.entry["counts"]["conflicts"] == 0
        registry = Registry(root)
        point = int(registry.lookup("gaia", "dr3", [str(dr3)])[0])
        assert int(registry.lookup(EU, "catalog", ["NLTT 31450"])[0]) == point
        # The old star has no planet left, so it has no row.
        assert not registry.lookup(EU, "catalog", ["NLTT 730"])[0]
        planets = table_rows(root, "planets").to_pylist()
        assert [p["host"] for p in planets if p["designation"] == "NLTT 31450 b"] == [
            point
        ]

    def test_the_report_names_the_papers(self, root, backup, tmp_path):
        result, _ = self.gj_229_b(root, backup, tmp_path, "one")
        xuan, thompson = citation("xuan_2024"), citation("thompson_2025")
        assert f"GJ 229 Bb ({EU}): GJ 229 B ({xuan})" in result.report
        assert f"GJ 229 B: simbad/oid/864867 ({thompson}; {xuan})" in result.report

    def test_a_host_move_names_its_paper(self, root, backup, tmp_path, monkeypatch):
        files, _, stars = self.nltt_31450()
        # A planet of its own keeps NLTT 730, so that only the row moves.
        files.eu.append(
            eu_planet("NLTT 730 b", "NLTT 730", 3.77, 29.93, orbital_period="5")
        )
        with monkeypatch.context() as patch:
            patch.delitem(HOSTS, (EU, "NLTT 31450 b"))
            ingest(root, backup, files.write(tmp_path / "one"), stars=stars)
        result, _ = ingest(root, backup, files.write(tmp_path / "two"), stars=stars)
        [line] = [line for line in result.report.splitlines() if "the host of" in line]
        assert "NLTT 31450 b" in line and citation("deacon_2014") in line

    def gj_229_bb(self, star_name="GJ 229"):
        files = downloads()
        files.eu.append(
            eu_planet(
                "GJ 229 Bb", star_name, 92.64423, -21.86464, orbital_period="12.1346"
            )
        )
        return files

    def test_the_entry_wins_when_the_catalogue_names_the_star(
        self, root, backup, tmp_path
    ):
        result, _ = ingest(
            root,
            backup,
            self.gj_229_bb("GJ 229 B").write(tmp_path / "one"),
            simbad_rows=self.simbad_rows(tmp_path / "one"),
        )
        assert result.entry["counts"]["conflicts"] == 0
        registry = Registry(root)
        point = int(registry.lookup("simbad", "oid", ["864867"])[0])
        assert int(registry.lookup(EU, "catalog", ["GJ 229 B"])[0]) == point
        rows = table_rows(root, "point-source").to_pylist()
        assert (
            next(r for r in rows if r["id"] == point)["astrometry_source"] == "simbad"
        )
        assert "so the entry can go: 1" in result.report
        assert f"GJ 229 Bb ({EU}): GJ 229 B\n" in result.report

    def test_a_key_that_reaches_no_object_raises(self, root, backup, tmp_path):
        inputs = self.gj_229_bb().write(tmp_path / "one")
        with pytest.raises(ValueError, match="GJ 229 B .* claims simbad/oid/864867"):
            ingest(root, backup, inputs)
        assert Registry(root).ingests == []

    def test_a_key_in_conflict_raises(self, root, backup, tmp_path):
        files = downloads()
        # The point holds another star of exoplanet.eu, so the row cannot take it.
        files.eu.append(
            eu_planet("Old b", "Old", 92.64434, -21.86984, orbital_period="5")
        )
        files.simbad_names.append(
            ("exoplanet_eu", "catalog", "star", "Old", "Old", "printed", "864867")
        )
        files.simbad_basic["864867"] = ("HD 42581B", "BD*")
        ingest(
            root,
            backup,
            files.write(tmp_path / "one"),
            simbad_rows=self.simbad_rows(tmp_path / "one"),
        )
        assert int(Registry(root).lookup(EU, "catalog", ["Old"])[0])
        with pytest.raises(ValueError, match="GJ 229 B .* claims simbad/oid/864867"):
            ingest(
                root,
                backup,
                self.gj_229_bb().write(tmp_path / "two"),
                simbad_rows=self.simbad_rows(tmp_path / "two"),
            )
        assert len(Registry(root).ingests) == 1

    def test_a_partial_ingest_reports_a_missed_key(self, root, backup, tmp_path):
        inputs = self.gj_229_bb().write(tmp_path / "one")
        result, prepared = ingest(root, backup, inputs, complete=False)
        assert prepared.missed_claims == [f"GJ 229 B ({EU}) claims simbad/oid/864867"]
        assert "claim linked no object: 1" in result.report


class TestStalePapers:
    """A stale entry of `planet_hosts` stops the ingest in its read step."""

    def test_nothing_is_written(self, root, backup, tmp_path, monkeypatch):
        monkeypatch.setattr(catalogues, "check_papers", check_papers)
        with pytest.raises(ValueError, match="planet_hosts: no row for"):
            ingest(root, backup, downloads().write(tmp_path / "in"))
        assert Registry(root).ingests == []


class TestHostsBySimbad:
    """A host with no Gaia DR3 id or HIP number claims its SIMBAD point."""

    PULSAR = 777

    def simbad_rows(self, tmp_path, *more):
        directory = write_simbad(
            tmp_path / "simbad-stars",
            [
                simbad_star(
                    self.PULSAR,
                    *PULSAR,
                    "PSR B1257+12",
                    otype="Psr",
                    plx_value=1.41,
                    plx_err=0.08,
                    pmra=46.44,
                    pmdec=-84.87,
                ),
                *more,
            ],
        )
        stars = SimbadList.read(directory)
        return simbad.engine_rows(stars, stars.handed(), set(), {}, {})[0]

    def files(self):
        ra, dec = offset(*PULSAR, 7, 40)
        files = downloads()
        files.archive.append(
            archive_planet(
                "3.8",
                "PSR B1257+12 b",
                "PSR B1257+12",
                "2.8",
                ra,
                dec,
                discoverymethod="Pulsar Timing",
                pl_orbper="25",
                sy_dist="600",
            )
        )
        files.eu.append(
            eu_planet(
                "PSR B1257+12 b",
                "PSR B1257+12",
                ra,
                dec,
                orbital_period="25",
                star_distance="710",
            )
        )
        files.simbad_names += [
            (
                "exoplanet_archive",
                "stellarhosts",
                "star",
                "PSR B1257+12",
                "PSR B1257+12",
                "printed",
                str(self.PULSAR),
            ),
            (
                "exoplanet_eu",
                "catalog",
                "star",
                "PSR B1257+12",
                "PSR B1257+12",
                "printed",
                str(self.PULSAR),
            ),
        ]
        files.simbad_basic[str(self.PULSAR)] = ("PSR B1257+12", "Psr")
        return files

    def double(self, root, backup, tmp_path):
        """A first ingest in which the host and SIMBAD hold one point each."""
        inputs = self.files().write(tmp_path / "one")
        ingest(
            root,
            backup,
            inputs,
            simbad_rows=self.simbad_rows(tmp_path / "one"),
            oids=set(),
        )
        registry = Registry(root)
        host = int(registry.lookup(ARCHIVE, "pscomppars", ["2.8"])[0])
        point = int(registry.lookup("simbad", "oid", [str(self.PULSAR)])[0])
        assert host and point and host != point
        return host, point

    def merge(self, root, backup, tmp_path, name):
        return ingest(
            root,
            backup,
            self.files().write(tmp_path / name),
            simbad_rows=self.simbad_rows(tmp_path / name),
        )

    def test_a_new_host_makes_no_second_star(self, root, backup, tmp_path):
        result, prepared = self.merge(root, backup, tmp_path, "one")
        registry = Registry(root)
        point = int(registry.lookup("simbad", "oid", [str(self.PULSAR)])[0])
        assert int(registry.lookup(ARCHIVE, "pscomppars", ["2.8"])[0]) == point
        assert int(registry.lookup(EU, "catalog", ["PSR B1257+12"])[0]) == point
        counts = result.entry["counts"]
        assert (counts["merged"], counts["conflicts"]) == (0, 0)
        assert prepared.by_simbad == [f"PSR B1257+12: simbad/oid/{self.PULSAR}"]
        assert "claim their SIMBAD object: 1" in result.report

    def test_a_double_merges(self, root, backup, tmp_path):
        host, point = self.double(root, backup, tmp_path)
        result, _ = self.merge(root, backup, tmp_path, "two")
        counts = result.entry["counts"]
        assert (counts["merged"], counts["conflicts"]) == (1, 0)
        survivor, alias = sorted((host, point))
        registry = Registry(root)
        assert registry.aliases()[alias] == survivor
        [merge] = registry.merges(registry.last_ingest).to_pylist()
        assert (merge["survivor"], merge["loser"]) == (survivor, alias)
        assert f"simbad/oid/{self.PULSAR}" in merge["evidence"]
        assert str(alias) in result.report

    def test_the_planet_goes_to_the_survivor(self, root, backup, tmp_path):
        host, point = self.double(root, backup, tmp_path)
        self.merge(root, backup, tmp_path, "two")
        rows = table_rows(root, "planets").to_pylist()
        hosts_ = [p["host"] for p in rows if p["designation"] == "PSR B1257+12 b"]
        assert hosts_ == [min(host, point)]

    def test_a_merged_star_keeps_simbads_astrometry(self, root, backup, tmp_path):
        host, point = self.double(root, backup, tmp_path)
        before = table_rows(root, "point-source").to_pylist()
        assert next(r for r in before if r["id"] == host)["ra"] != PULSAR[0]
        self.merge(root, backup, tmp_path, "two")
        rows = table_rows(root, "point-source").to_pylist()
        [row] = [r for r in rows if r["id"] in (host, point)]
        assert row["id"] == min(host, point)
        assert row["astrometry_source"] == "simbad"
        assert row["parallax"] == pytest.approx(1.41)
        assert row["ra"] == pytest.approx(PULSAR[0])
        # The catalogue's star stays, with its distance.
        assert row["host_star_source"] == ARCHIVE
        assert row["host_distance"] == 600

    def test_a_second_ingest_stays_stable(self, root, backup, tmp_path):
        host, point = self.double(root, backup, tmp_path)
        self.merge(root, backup, tmp_path, "two")
        before = table_rows(root, "planets").to_pylist()
        result, _ = self.merge(root, backup, tmp_path, "three")
        counts = result.entry["counts"]
        assert (counts["minted"], counts["merged"]) == (0, 0)
        assert counts["conflicts"] == 0
        assert result.entry["extensions"]["planets"]["moved"] == 0
        registry = Registry(root)
        survivor = min(host, point)
        assert int(registry.lookup(ARCHIVE, "pscomppars", ["2.8"])[0]) == survivor
        assert int(registry.lookup("simbad", "oid", [str(self.PULSAR)])[0]) == survivor
        planets = table_rows(root, "planets").to_pylist()
        assert [(p["host"], p["number"]) for p in planets] == [
            (p["host"], p["number"]) for p in before
        ]

    def test_a_missed_claim_is_in_the_report(self, root, backup, tmp_path):
        # The list of objects names it, but no SIMBAD row reaches the ingest.
        oid = str(self.PULSAR)
        inputs = self.files().write(tmp_path / "one")
        result, prepared = ingest(root, backup, inputs, oids={oid})
        # The first row mints the star, and the next rows reach it.
        assert prepared.missed_claims == [
            f"PSR B1257+12 ({ARCHIVE}) claims simbad/oid/{oid}"
        ]
        assert result.entry["extensions"]["planets"]["missed_claims"] == 1
        assert "claim linked no object: 1" in result.report
        host = int(Registry(root).lookup(ARCHIVE, "pscomppars", ["2.8"])[0])
        rows = table_rows(root, "point-source").to_pylist()
        assert next(r for r in rows if r["id"] == host)["ra"] is None

    def test_a_claim_that_hits_is_not_in_the_report(self, root, backup, tmp_path):
        result, prepared = self.merge(root, backup, tmp_path, "one")
        assert prepared.missed_claims == []
        assert "claim linked no object" not in result.report

    def test_an_object_on_two_stars_is_not_merged(self, root, backup, tmp_path):
        files = self.files()
        ra, dec = offset(*PULSAR, 90, 40)
        files.eu = [
            *files.eu,
            eu_planet("HD 9 A b", "HD 9 A", ra, dec, orbital_period="9"),
            eu_planet("HD 9 B b", "HD 9 B", ra, dec, orbital_period="19"),
        ]
        oid = "888"
        files.simbad_names += [
            ("exoplanet_eu", "catalog", "star", name, name, "printed", oid)
            for name in ("HD 9 A", "HD 9 B")
        ]
        files.simbad_basic[oid] = ("HD 9", "PM*")
        rows = self.simbad_rows(tmp_path / "one", simbad_star(888, ra, dec, "HD 9"))
        result, prepared = ingest(
            root, backup, files.write(tmp_path / "one"), simbad_rows=rows
        )
        assert result.entry["counts"]["merged"] == 0
        assert len(prepared.by_simbad) == 1
        registry = Registry(root)
        point = int(registry.lookup("simbad", "oid", [oid])[0])
        stars = registry.lookup(EU, "catalog", ["HD 9 A", "HD 9 B"])
        assert point not in {int(found) for found in stars}


class TestStarsFromPapers:
    """A catalogue star with a key and position from `planet_hosts`."""

    def test_a_row_with_the_wrong_sign_reaches_its_star(self, root, backup, tmp_path):
        files = downloads()
        # exoplanet.eu gives the declination with the wrong sign.
        files.eu.append(
            eu_planet(
                "2MASS J1315-2649 b",
                "2MASS J1315-2649",
                198.87858,
                26.83106,
                orbital_period="19162.5",
                star_distance="19",
            )
        )
        dr3 = 6186534394250282752
        stars = gaia_pass(gaia_star(dr3, 198.87515, -26.83235, 20.3))
        result, _ = ingest(root, backup, files.write(tmp_path / "one"), stars=stars)
        assert result.entry["counts"]["conflicts"] == 0
        registry = Registry(root)
        point = int(registry.lookup("gaia", "dr3", [str(dr3)])[0])
        assert int(registry.lookup(EU, "catalog", ["2MASS J1315-2649"])[0]) == point
        rows = table_rows(root, "point-source").to_pylist()
        row = next(r for r in rows if r["id"] == point)
        assert row["astrometry_source"] == GAIA_DR3.name
        assert row["host_distance"] == 19
        assert not [r for r in rows if r["dec"] and abs(r["dec"] - 26.83) < 0.01]
        again, _ = ingest(root, backup, files.write(tmp_path / "two"), stars=stars)
        counts = again.entry["counts"]
        assert (counts["minted"], counts["merged"], counts["conflicts"]) == (0, 0, 0)
        assert (
            int(Registry(root).lookup(EU, "catalog", ["2MASS J1315-2649"])[0]) == point
        )

    def twa_42(self, tmp_path):
        directory = write_simbad(
            tmp_path / "simbad-stars",
            [simbad_star(9910123, 169.885597, -11.629638, "TWA 42", otype="BD*")],
        )
        found = SimbadList.read(directory)
        rows = simbad.engine_rows(found, found.handed(), set(), {}, {})[0]
        files = downloads()
        files.oec.append(
            "<system><name>2MASS J1119-1137</name>"
            "<star><name>2MASS J1119-1137</name>"
            "<planet><name>2MASS J1119-1137 b</name><period>32850</period>"
            "<list>Confirmed planets</list></planet></star>"
            f"<rightascension>{_sexagesimal(169.88558 / 15)}</rightascension>"
            f"<declination>{_sexagesimal(-11.62964, sign=True)}</declination>"
            "</system>"
        )
        # The row names no star: its paper's join gives it OEC's.
        files.eu.append(
            eu_planet(
                "2MASS J1119-1137 b",
                "",
                169.88558,
                -11.62964,
                orbital_period="32850",
                mass="3.7",
            )
        )
        return files, rows

    def test_a_star_merge_names_its_paper(self, root, backup, tmp_path, monkeypatch):
        files, rows = self.twa_42(tmp_path)
        with monkeypatch.context() as patch:
            patch.delitem(STARS, (OEC, "2MASS J1119-1137"))
            ingest(root, backup, files.write(tmp_path / "one"), simbad_rows=rows)
        ingest(root, backup, files.write(tmp_path / "two"), simbad_rows=rows)
        registry = Registry(root)
        [merge] = registry.merges(registry.last_ingest).to_pylist()
        assert "simbad/oid/9910123" in merge["evidence"]
        assert citation("best_2017") in merge["evidence"]

    def test_a_row_with_no_object_claims_its_key(self, root, backup, tmp_path):
        files, rows = self.twa_42(tmp_path)
        result, _ = ingest(
            root, backup, files.write(tmp_path / "one"), simbad_rows=rows
        )
        assert result.entry["counts"]["conflicts"] == 0
        registry = Registry(root)
        point = int(registry.lookup("simbad", "oid", ["9910123"])[0])
        found_id = registry.lookup(OEC, "systems", ["2MASS J1119-1137"])[0]
        assert int(found_id) == point
        planets = table_rows(root, "planets").to_pylist()
        assert [p["host"] for p in planets if "J1119" in p["designation"]] == [point]


class TestWgsnStarNames:
    """A host row leaves out a NameExoWorlds star name only when the IAU WGSN
    pass claims that name on its star."""

    @pytest.mark.parametrize(
        ("wgsn", "left"),
        [
            ([WgsnName("Prima", "Alpha", gaia_dr3=101)], True),
            ([WgsnName("PRIMA", "HD 1", hip=7, gaia_dr3=101)], True),
            # The pass places it by position, or on another star.
            ([WgsnName("Prima", "Alpha")], False),
            ([WgsnName("Prima", "Alpha", gaia_dr3=303)], False),
            ([WgsnName("Secunda", "HD 2", gaia_dr3=101)], False),
        ],
    )
    def test_route(self, root, backup, tmp_path, wgsn, left):
        inputs = downloads().write(tmp_path / "in")
        with IngestRun.start(root, backup) as run:
            reader = gaia.GaiaReader(
                NO_NEIGHBOURS, orbits=HOST_ORBITS, golden_sample=HOST_GOLDEN_SAMPLE
            )
            read = exoplanets.read(reader, inputs)
            prepared = exoplanets.prepare(read, run, {}, inputs, wgsn)
        host_names = {
            name
            for rows in prepared.host_rows.values()
            for name in rows["name"].to_pylist()
        }
        assert ("Prima" in host_names) is not left
        assert prepared.named.wgsn == (["Prima"] if left else [])
        assert prepared.wgsn_stars == int(left)


def sunlike(source_id: int, ra: float, dec: float) -> dict:
    """A G = 11 star at 100 pc with BP − RP 0.8, so G − V is −0.15."""
    return gaia_star(source_id, ra, dec, 11.0) | {
        "phot_bp_mean_mag": 11.4,
        "phot_rp_mean_mag": 10.6,
    }


class TestTwins:
    """A host without ids claims a lone star that agrees with it."""

    def rows(self) -> pa.Table:
        stars = gaia_stars(
            [
                sunlike(1, *at(0)),
                sunlike(2, *at(60)),
                sunlike(3, *offset(*at(60), 2, 0)),
                sunlike(4, *at(120)),
                sunlike(5, *at(180)),
                sunlike(6, *at(60, 180)),
            ]
        )
        return gaia.engine_rows(gaia.join_fidelity(stars, fidelity([])), NO_NEIGHBOURS)

    def target(self, key, centre, arcsec, **values) -> twins.Target:
        ra, dec = offset(*centre, arcsec, 45)
        return twins.Target(key, f"T{key}", ra, dec, **values)

    def targets(self) -> list[twins.Target]:
        return [
            self.target(1, at(0), 0.5, v_mag=11.2, distance=100.0),
            # Two stars within 5″.
            self.target(2, at(60), 1.0, v_mag=11.2),
            self.target(3, at(120), 0.5, parallax=50.0, parallax_error=1.0),
            self.target(4, at(180), 4.0, parallax=10.0),
            self.target(5, at(240), 0.5, v_mag=11.2),
            self.target(6, at(60, 180), 0.5, parallax=10.0, companion=True),
        ]

    def test_checks_in_a_first_ingest(self, root, backup):
        with IngestRun.start(root, backup) as run:
            run.add(GAIA_DR3, [self.rows()])
            found = twins.find(run, self.targets())
        assert set(found.twins) == {1}
        twin = found.twins[1]
        assert twin.claim == ("gaia", "dr3", "1")
        assert twin.checks == ("parallax", "V")
        assert found.counts["stars within 5″: 2+"] == 1
        assert found.counts["stars within 5″: 0"] == 1
        assert found.counts["lone candidate refused: disagrees"] == 1
        assert (
            found.counts["lone candidate refused: farther than 3″ with no magnitude"]
            == 1
        )
        assert any("companion star" in text for text in found.refused)

    def test_the_next_ingest_finds_the_same_twins(self, root, backup):
        with IngestRun.start(root, backup) as run:
            run.add(GAIA_DR3, [self.rows()])
            first = twins.find(run, self.targets())
            run.commit()
        with IngestRun.start(root, backup) as run:
            run.add(GAIA_DR3, [self.rows()])
            again = twins.find(run, self.targets())
        assert again.twins == first.twins
        assert again.counts == first.counts

    def test_a_star_of_two_passes_is_one_candidate(self, root, backup):
        """The Hipparcos row joins the Gaia star, so the target has one star
        within 5″, with Gaia's values."""
        table = hip_stars(
            [
                {
                    "hip": 77,
                    "ra": at(0)[0],
                    "dec": at(0)[1],
                    "parallax": 10.0,
                    "v_mag": 11.3,
                }
            ]
        )
        hip, _ = hipparcos.engine_rows(
            table, BestNeighbours(np.array([1]), np.array([77]))
        )
        with IngestRun.start(root, backup) as run:
            run.add(GAIA_DR3, [self.rows()])
            run.add(HIPPARCOS, [hip])
            found = twins.find(run, self.targets()[:1])
        assert found.counts["stars within 5″: 1"] == 1
        assert found.twins[1].claim == ("gaia", "dr3", "1")

    def test_a_root_in_two_regions_is_one_candidate(self, monkeypatch):
        monkeypatch.setattr(
            sky,
            "disc_ranges",
            lambda *args: (
                np.array([0, 0]),
                np.array([1, 2]),
                np.array([2, 3]),
            ),
        )
        monkeypatch.setattr(sky, "regions_of_ranges", lambda low, high: [int(low[0])])

        class Run:
            def objects(self, region):
                source = GAIA_DR3.name if region == 1 else HIPPARCOS.name
                return pa.table(
                    {
                        "key": [7],
                        "ra": [0.0],
                        "dec": [0.0],
                        "source": [source],
                    }
                )

        nearby = twins._nearby(
            cast(IngestRun, Run()), [twins.Target(1, "T1", 0.0, 0.0)]
        )
        assert nearby == {1: [(7, 0.0, GAIA_DR3.name)]}

    def test_a_held_or_wanted_star_is_no_twin(self, root, backup):
        both = [
            self.target(1, at(0), 0.5, v_mag=11.2),
            self.target(2, at(0), 1.0, v_mag=11.0),
        ]
        with IngestRun.start(root, backup) as run:
            run.add(GAIA_DR3, [self.rows()])
            assert twins.find(run, both).twins == {}
            held = twins.find(run, both[:1], {("gaia", "dr3", "1")})
        assert held.refused == ["T1 → gaia/dr3/1 (0.50″): another host holds it"]
