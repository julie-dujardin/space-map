"""Tests for engine extensions and the exoplanet ingest through the engine."""

from dataclasses import dataclass

import numpy as np
import pyarrow as pa
import pytest

from space_map_data.extrasolar.engine import ExtensionResult, IngestRun
from space_map_data.extrasolar.exoplanets import ingest as exoplanets
from space_map_data.extrasolar.exoplanets import twins
from space_map_data.extrasolar.exoplanets.catalogues import ARCHIVE, EU, OEC
from space_map_data.extrasolar.exoplanets.table import default_node
from space_map_data.extrasolar.registry import Registry
from space_map_data.extrasolar.sources import gaia
from space_map_data.extrasolar.sources.gaia import GAIA_DR3, BestNeighbours
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
from tests.extrasolar.test_stars import fidelity, gaia_star, gaia_stars

RA, DEC = centre(4_000_777)
NO_NEIGHBOURS = BestNeighbours(np.zeros(0, np.int64), np.zeros(0, np.int64))
# An orbit of the unpositionable host source 202.
HOST_ORBITS = build_orbits([solution(202, "SB1")])


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


def gaia_pass() -> pa.Table:
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
        ]
    )
    return gaia.engine_rows(
        gaia.join_fidelity(stars, fidelity([(101, 0.9), (303, 0.2)])), NO_NEIGHBOURS
    )


def ingest(root, backup, inputs, complete=True):
    with IngestRun.start(root, backup) as run:
        reader = gaia.GaiaReader(NO_NEIGHBOURS, orbits=HOST_ORBITS)
        prepared = exoplanets.prepare(reader, run.registry, {}, inputs)
        run.add(GAIA_DR3, [gaia_pass(), prepared.gaia_rows], complete)
        exoplanets.add_passes(run, prepared, complete)
        return run.commit(), prepared


class TestExoplanetIngest:
    """Hosts get IDs through the engine, planets get numbers at commit."""

    def test_two_ingests(self, root, backup, tmp_path):
        files = downloads()
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
        assert point[beta]["astrometry_source"] == GAIA_DR3.name
        assert point[beta]["host_distance"] == 300
        assert point[beta]["radius_gspphot"] == pytest.approx(1.1)
        assert point[beta]["feh_gspspec_calibrated"] is not None
        assert point[beta]["mh_xgboost"] == pytest.approx(-0.3)
        assert point[beta]["in_vetted_rgb_sample"] is False
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


def sunlike(source_id: int, ra: float, dec: float) -> dict:
    """A G = 11 star at 100 pc with BP − RP 0.8, so G − V is −0.15."""
    return gaia_star(source_id, ra, dec, 11.0) | {
        "phot_bp_mean_mag": 11.4,
        "phot_rp_mean_mag": 10.6,
    }


class TestTwins:
    """A host without ids claims a lone registry star that agrees with it."""

    def registry(self, root, backup) -> Registry:
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
        rows = gaia.engine_rows(gaia.join_fidelity(stars, fidelity([])), NO_NEIGHBOURS)
        with IngestRun.start(root, backup) as run:
            run.add(GAIA_DR3, [rows])
            run.commit()
        return Registry(root)

    def target(self, key, centre, arcsec, **values) -> twins.Target:
        ra, dec = offset(*centre, arcsec, 45)
        return twins.Target(key, f"T{key}", ra, dec, **values)

    def test_checks(self, root, backup):
        registry = self.registry(root, backup)
        found = twins.find(
            registry,
            [
                self.target(1, at(0), 0.5, v_mag=11.2, distance=100.0),
                # Two stars within 5″.
                self.target(2, at(60), 1.0, v_mag=11.2),
                self.target(3, at(120), 0.5, parallax=50.0, parallax_error=1.0),
                self.target(4, at(180), 4.0, parallax=10.0),
                self.target(5, at(240), 0.5, v_mag=11.2),
                self.target(6, at(60, 180), 0.5, parallax=10.0, companion=True),
            ],
        )
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

    def test_a_held_or_wanted_star_is_no_twin(self, root, backup):
        registry = self.registry(root, backup)
        both = [
            self.target(1, at(0), 0.5, v_mag=11.2),
            self.target(2, at(0), 1.0, v_mag=11.0),
        ]
        assert twins.find(registry, both).twins == {}
        held = twins.find(registry, both[:1], {("gaia", "dr3", "1")})
        assert held.refused == ["T1 → " + held.refused[0].split(" → ")[1]]
        assert "another host holds it" in held.refused[0]
