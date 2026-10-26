"""Tests for the planets of the extrasolar export: the planet index, the
system files, the hosts in the render tree, the token and the checks."""

import gzip
import json
import math
from pathlib import Path

import numpy as np
import pytest

from space_map_data.export.extrasolar import build, orbits, planets, render
from space_map_data.export.extrasolar.build import (
    ExportRefused,
    export_extrasolar,
    export_extrasolar_only,
)
from space_map_data.export.extrasolar.reader import ExportReader, TokenMismatch
from space_map_data.extrasolar.exoplanets.catalogues import EU
from space_map_data.extrasolar.registry import ALIAS, RETIRED, Registry
from space_map_data.utils.paths import EXTRASOLAR_DIR
from tests.extrasolar.conftest import offset
from tests.extrasolar.exoplanet_files import eu_planet
from tests.extrasolar.export_registry import planet, star, write_registry
from tests.extrasolar.test_exoplanet_ingest import ZETA, downloads, ingest
from tests.extrasolar.test_export import _expected_position

HOST = {
    "host_star_source": "nasa-exoplanet-archive",
    "host_distance": 20.0,
    "host_teff": 5800.0,
    "host_radius": 1.1,
    "host_mass": 1.05,
}


def _literature(ra: float, dec: float, name: str, **values) -> dict:
    """A host that only an exoplanet catalogue gives, with no parallax."""
    row = {
        "ra": ra,
        "dec": dec,
        "epoch": 2000.0,
        "astrometry_source": "nasa-exoplanet-archive",
        "host_star_source": "nasa-exoplanet-archive",
        "host_name": name,
        "_name": name,
    }
    return row | values


STARS = [
    # 0: a Gaia host, placed by its parallax.
    star(100.0, 20.0, 50.0, name="Host A") | HOST | {"host_name": "HD 1"},
    # 1: a literature host at its catalogue distance, with V and Teff.
    _literature(
        101.0, 21.0, "Lit B", host_distance=500.0, host_v_mag=12.0, host_teff=4000.0
    ),
    # 2: a microlensing host: a distance and no magnitude.
    _literature(102.0, -20.0, "OGLE-1L", host_distance=3000.0),
    # 3: a host with no distance at all.
    _literature(103.0, 22.0, "PSR 1"),
    # 4: the companion of host 0, far off on the sky so it is in another region.
    star(250.0, -40.0, 30.0, name="Host A B") | HOST,
    # 5: no planets.
    star(104.0, 24.0, 10.0, name="Plain"),
]
PLANETS = [
    planet(
        0,
        1,
        eccentricity=0.3,
        omega=40.0,
        inclination=88.0,
        transit_time=2_459_000.5,
        discovery_method="Transit",
        assumed=["node"],
    ),
    planet(
        0,
        2,
        name="Lucky",
        name_source="iau-nameexoworlds",
        aliases=["Lucky", "Planet 0 2"],
        discovery_method="Imaging",
        semi_major_axis=30.0,
        period=60_000.0,
        node=120.0,
        node_inclination=30.0,
        sky_source="open-exoplanet-catalogue",
        assumed=["inclination"],
    ),
    planet(1, 1, semi_major_axis=None),
    planet(2, 1, eccentricity=280.0),
    planet(3, 1),
    planet(4, 1, system=0, semi_major_axis=0.5, period=100.0),
]


@pytest.fixture(autouse=True)
def _small(monkeypatch):
    monkeypatch.setattr(render, "NODE_ROWS", 6)
    monkeypatch.setattr(render, "BATCH_ROWS", 40)


@pytest.fixture
def out(tmp_path):
    return tmp_path / "out"


def _export(tmp_path: Path, out: Path, planet_rows=PLANETS, **kwargs):
    built = write_registry(tmp_path / "reg", STARS, planets=planet_rows, **kwargs)
    report = export_extrasolar(built.root, out, workers=1)
    return built, report, ExportReader(out / "v1" / "x")


class TestPlanetFiles:
    """The planet index and the system files."""

    def test_the_index_lists_each_host_with_its_system(self, tmp_path, out):
        built, _, reader = _export(tmp_path, out)
        ids = built.ids
        index = reader.planet_hosts()
        assert sorted(index) == sorted(ids[:5])
        assert index[ids[0]]["planets"] == [1, 2]
        assert index[ids[0]]["system"] == ids[0]
        assert index[ids[4]]["system"] == ids[0]
        assert index[ids[0]]["outer_orbit"] == 30.0
        assert index[ids[1]]["outer_orbit"] is None
        assert index[ids[3]]["position"] is None
        assert index[ids[0]]["position"] == pytest.approx(
            _expected_position(STARS[0]).tolist(), abs=1e-9
        )

    def test_a_system_spans_regions(self, tmp_path, out):
        built, _, reader = _export(tmp_path, out)
        ids = built.ids
        system = reader.system(ids[0])
        assert system["system"] == ids[0]
        assert [h["id"] for h in system["hosts"]] == [ids[0], ids[4]]
        assert [(p["host"], p["number"]) for p in system["planets"]] == [
            (ids[0], 1),
            (ids[0], 2),
            (ids[4], 1),
        ]
        assert system["hosts"][1]["planets"] == [1]

    def test_a_host_record(self, tmp_path, out):
        built, _, reader = _export(tmp_path, out)
        host = reader.system(built.ids[0])["hosts"][0]
        assert host["name"] == "Host A"
        assert host["catalogue_name"] == "HD 1"
        assert host["placement"] == render.PARALLAX
        assert host["distance"] == pytest.approx(20.0, rel=1e-6)
        assert (host["teff"], host["teff_source"]) == (5800.0, "nasa-exoplanet-archive")
        assert (host["radius"], host["mass"]) == (1.1, 1.05)
        assert host["bp_rp"] == pytest.approx(0.9)
        literature = reader.system(built.ids[1])["hosts"][0]
        assert literature["placement"] == render.CATALOGUE_DISTANCE
        assert literature["distance"] == 500.0
        assert reader.system(built.ids[3])["hosts"][0]["placement"] is None

    def test_a_planet_record(self, tmp_path, out):
        built, _, reader = _export(tmp_path, out)
        lucky = reader.planet(built.ids[0], 2)
        assert lucky is not None
        assert (lucky["name"], lucky["designation"]) == ("Lucky", "Planet 0 2")
        assert lucky["class"] == "planet" and lucky["status"] == "confirmed"
        assert lucky["values"]["semi_major_axis"] == 30.0
        assert lucky["values"]["node_inclination"] == 30.0
        assert "status" not in lucky["values"]
        assert lucky["sources"]["sky"] == "open-exoplanet-catalogue"
        assert lucky["sources"]["status"] == "nasa-exoplanet-archive"
        assert lucky["assumed"] == ["inclination"]
        direction = np.array(reader.planet_hosts()[built.ids[0]]["position"])
        expected = orbits.elements({**PLANETS[1], "transit_time": None}, direction)
        assert expected is not None
        assert lucky["elements"].pop("phase") == expected.pop("phase")
        assert lucky["elements"] == pytest.approx(expected)

    def test_the_orbits_of_the_odd_planets(self, tmp_path, out):
        built, report, reader = _export(tmp_path, out)
        assert reader.planet(built.ids[1], 1)["elements"] is None
        odd = reader.planet(built.ids[2], 1)["elements"]
        assert odd["e"] == 0.0 and odd["replaced"] == ["eccentricity"]
        assert reader.planet(built.ids[2], 1)["values"]["eccentricity"] == 280.0
        # A host with no distance still points its orbit by its RA and Dec.
        assert reader.planet(built.ids[3], 1)["elements"] is not None
        assert report["planets"]["no semi-major axis, a fixed dot"] == 1
        assert report["planets"]["eccentricity outside [0, 1), drawn as 0"] == 1

    def test_metadata_lists_the_planets(self, tmp_path, out):
        _, report, reader = _export(tmp_path, out)
        entry = reader.metadata["planets"]
        assert entry["token"] == report["tokens"]["planets"]
        assert entry["index"] == planets.INDEX_FILE
        assert entry["system"] == "planets/{key}.json.gz"
        assert (entry["systems"], entry["hosts"], entry["planets"]) == (4, 5, 6)
        assert entry["distribution"] == "non-commercial"
        assert entry["frame"] == build.FRAME
        assert "credits" not in entry
        sources = {credit["source"] for credit in reader.metadata["credits"]}
        assert {credit["source"] for credit in planets.CREDITS} <= sources

    def test_every_file_carries_the_token(self, tmp_path, out):
        _, report, reader = _export(tmp_path, out)
        token = report["tokens"]["planets"]
        files = sorted((reader.root / "planets").glob("*.json.gz"))
        assert len(files) == 5
        for path in files:
            assert json.loads(gzip.decompress(path.read_bytes()))["token"] == token

    def test_a_file_of_another_export_is_refused(self, tmp_path, out):
        built, _, reader = _export(tmp_path, out)
        path = reader.root / planets.system_path(built.ids[0])
        content = json.loads(gzip.decompress(path.read_bytes()))
        content["token"] = "f" * 16
        path.write_bytes(gzip.compress(json.dumps(content).encode()))
        with pytest.raises(TokenMismatch):
            reader.system(built.ids[0])

    def test_the_token_follows_the_planets(self, tmp_path, out):
        _, first, _ = _export(tmp_path, out)
        changed = [PLANETS[0] | {"mass": 2.0}, *PLANETS[1:]]
        _, second, _ = _export(tmp_path / "again", tmp_path / "out2", changed)
        assert first["tokens"]["planets"] != second["tokens"]["planets"]
        assert first["tokens"]["metadata"] == second["tokens"]["metadata"]

    def test_rerun_keeps_tokens_and_bytes(self, tmp_path, out):
        built, first, reader = _export(tmp_path, out)
        files = {
            p.relative_to(reader.root).as_posix(): p.read_bytes()
            for p in sorted(reader.root.rglob("*"))
            if p.is_file() and p.name != "metadata.json"
        }
        second = export_extrasolar(built.root, out, workers=1)
        assert first["tokens"] == second["tokens"]
        for path, data in files.items():
            assert (reader.root / path).read_bytes() == data, path

    def test_worker_processes_give_the_same_files(self, tmp_path, out):
        built, _, reader = _export(tmp_path, out)
        export_extrasolar(built.root, tmp_path / "pool", workers=2)
        pooled = tmp_path / "pool" / "v1" / "x"
        for path in sorted((reader.root / "planets").glob("*.json.gz")):
            assert (pooled / "planets" / path.name).read_bytes() == path.read_bytes()

    def test_no_planets_table(self, tmp_path, out):
        built = write_registry(tmp_path / "reg", STARS)
        report = export_extrasolar(built.root, out, workers=1)
        reader = ExportReader(out / "v1" / "x")
        assert "planets" not in reader.metadata
        assert "planets" not in report["tokens"]
        assert not (reader.root / "planets").exists()


class TestHostsInTheTree:
    """Hosts without a 5σ parallax have render rows at their catalogue
    distance."""

    def _row(self, reader: ExportReader, id_: int, position) -> dict:
        found = reader.find_render(id_, tuple(position))
        assert found is not None, id_
        name, row = found
        node = reader.node(name)
        return {column: float(node.numpy(column)[row]) for column in ("mag", "colour")}

    def test_a_literature_host(self, tmp_path, out):
        built, _, reader = _export(tmp_path, out)
        position = reader.planet_hosts()[built.ids[1]]["position"]
        assert np.linalg.norm(position) == pytest.approx(500.0)
        row = self._row(reader, built.ids[1], position)
        # V as G, at 500 pc.
        assert row["mag"] == pytest.approx(12.0 - 5 * math.log10(500.0) + 5, abs=1e-3)
        assert row["colour"] == pytest.approx(1.73 + (1.7 - 1.73) * 10 / 110, abs=1e-3)

    def test_an_orbit_parallax_gives_the_distance(self, tmp_path, out):
        """A 5σ orbit parallax comes before the single-star parallax and the
        catalogue distance, and a host it places says parallax."""
        stars = [
            star(100.0, 20.0, 50.0, name="By parallax") | HOST,
            star(101.0, 21.0, 30.0, snr=3.0, name="By catalogue")
            | HOST
            | {"host_distance": 500.0},
        ]
        solution = {
            "nss_solution_type": "Orbital",
            "parallax_nss_error": 0.1,
            "orbit_source": "gaia-dr3",
        }
        orbit_rows = {
            0: solution | {"parallax_nss": 40.0},
            1: solution | {"parallax_nss": 25.0},
        }
        built = write_registry(
            tmp_path / "reg",
            stars,
            orbits=orbit_rows,
            planets=[planet(0, 1), planet(1, 1)],
        )
        report = export_extrasolar(built.root, out, workers=1)
        reader = ExportReader(out / "v1" / "x")
        assert report["render"]["distance from an orbit solution"] == 2
        assert report["render"]["placed by parallax"] == 2
        assert "placed by catalogue distance" not in report["render"]
        index = reader.planet_hosts()
        expected = ((render.PARALLAX, 25.0), (render.PARALLAX, 40.0))
        for id_, (placed, distance) in zip(built.ids, expected):
            host = reader.system(id_)["hosts"][0]
            assert host["placement"] == placed
            assert host["distance"] == pytest.approx(distance, rel=1e-6)
            position = index[id_]["position"]
            assert np.linalg.norm(position) == pytest.approx(distance, rel=1e-6)

    def test_a_host_with_no_magnitude(self, tmp_path, out):
        built, report, reader = _export(tmp_path, out)
        position = reader.planet_hosts()[built.ids[2]]["position"]
        row = self._row(reader, built.ids[2], position)
        assert row["mag"] == render.HOST_PLACEHOLDER_MAG
        assert math.isnan(row["colour"])
        assert report["render"]["planet host with no magnitude, placeholder"] == 1

    def test_a_host_with_no_distance_is_not_drawn(self, tmp_path, out):
        built, report, reader = _export(tmp_path, out)
        assert report["render"]["planet host with no distance"] == 1
        assert report["render"]["placed by catalogue distance"] == 2
        dropped = "dropped: no distance, nasa-exoplanet-archive astrometry"
        assert report["render"][dropped] == 1
        assert reader.find_render(built.ids[3], (0.0, 0.0, 0.0)) is None

    def test_bp_rp_from_teff(self):
        teff = np.array([2000.0, 5770.0, 5815.0, 20_000.0, np.nan])
        colour = render.bp_rp_from_teff(teff)
        assert colour[:4] == pytest.approx([5.1, 0.823, 0.813, -0.12])
        assert math.isnan(colour[4])


class TestChecks:
    """The checks that keep a planet's URL working."""

    def test_a_host_that_is_not_live(self, tmp_path, out):
        built = write_registry(
            tmp_path / "reg", STARS, planets=PLANETS[:1], retired=[0]
        )
        with pytest.raises(ExportRefused, match="planet host or system: not live"):
            export_extrasolar(built.root, out, workers=1)

    def test_a_served_planet_goes_missing(self, tmp_path, out):
        _export(tmp_path, out)
        dropped = [p for p in PLANETS if (p["_host"], p["number"]) != (0, 2)]
        built = write_registry(tmp_path / "reg2", STARS, planets=dropped)
        with pytest.raises(ExportRefused, match="a served planet is gone"):
            export_extrasolar(built.root, out, workers=1)

    def test_a_retired_number_may_go(self, tmp_path, out):
        _export(tmp_path, out)
        dropped = [p for p in PLANETS if (p["_host"], p["number"]) != (0, 2)]
        built = write_registry(
            tmp_path / "reg2",
            STARS,
            planets=dropped,
            planet_status=[(0, 2, RETIRED, None)],
        )
        export_extrasolar(built.root, out, workers=1)
        assert ExportReader(out / "v1" / "x").planet(built.ids[0], 2) is None

    def test_an_alias_number_points_at_its_planet(self, tmp_path, out):
        _export(tmp_path, out)
        dropped = [p for p in PLANETS if (p["_host"], p["number"]) != (0, 2)]
        built = write_registry(
            tmp_path / "reg2",
            STARS,
            planets=dropped,
            planet_status=[(0, 2, ALIAS, (0, 1))],
        )
        export_extrasolar(built.root, out, workers=1)
        reader = ExportReader(out / "v1" / "x")
        host = built.ids[0]
        assert reader.planet_index()["aliases"] == {f"{host}/2": [host, 1]}
        assert reader.planet_hosts()[host]["planets"] == [1]
        aliased = reader.planet(host, 2)
        assert aliased is not None and aliased["number"] == 1

    def test_an_alias_leads_to_another_host(self, tmp_path, out):
        # Host 4 merged into host 0: its planet is now 0/b/3, and 4/b/1 an alias.
        _export(tmp_path, out)
        moved = [p for p in PLANETS if p["_host"] != 4]
        moved.append(planet(0, 3, semi_major_axis=0.5, period=100.0))
        built = write_registry(
            tmp_path / "reg2",
            STARS,
            aliases=[(4, 0)],
            planets=moved,
            planet_status=[(4, 1, ALIAS, (0, 3))],
        )
        report = export_extrasolar(built.root, out, workers=1)
        reader = ExportReader(out / "v1" / "x")
        old, new = built.ids[4], built.ids[0]
        assert reader.planet_index()["aliases"] == {f"{old}/1": [new, 3]}
        assert old not in reader.planet_hosts()
        found = reader.planet(old, 1)
        assert found is not None and (found["host"], found["number"]) == (new, 3)
        assert report["planets"]["alias numbers to another host"] == 1

    def test_an_alias_to_no_planet_is_a_404(self, tmp_path, out):
        built = write_registry(
            tmp_path / "reg",
            STARS,
            planets=PLANETS,
            planet_status=[(0, 7, ALIAS, (0, 9))],
        )
        export_extrasolar(built.root, out, workers=1)
        reader = ExportReader(out / "v1" / "x")
        assert reader.planet_index()["aliases"] == {}
        assert reader.planet(built.ids[0], 7) is None

    def test_a_host_in_two_systems(self, tmp_path, out):
        built = write_registry(
            tmp_path / "reg",
            STARS,
            planets=[PLANETS[0], planet(0, 2, system=4)],
        )
        with pytest.raises(ExportRefused, match="a host in two systems"):
            export_extrasolar(built.root, out, workers=1)

    def test_a_number_given_twice(self, tmp_path, out):
        built = write_registry(
            tmp_path / "reg", STARS, planets=[PLANETS[0], PLANETS[0]]
        )
        with pytest.raises(ExportRefused, match="a planet number given twice"):
            export_extrasolar(built.root, out, workers=1)

    def test_a_failed_check_keeps_the_served_export(self, tmp_path, out):
        _, first, _ = _export(tmp_path, out)
        built = write_registry(tmp_path / "reg2", STARS, planets=PLANETS[:1])
        with pytest.raises(ExportRefused):
            export_extrasolar(built.root, out, workers=1)
        reader = ExportReader(out / "v1" / "x")
        assert reader.metadata["planets"]["token"] == first["tokens"]["planets"]
        assert not (out / "v1" / ".x-staging").exists()
        assert not (out / ".build").exists()

    def test_another_registry_never_writes_the_served_export(self, tmp_path):
        built = write_registry(tmp_path / "reg", STARS, planets=PLANETS)
        with pytest.raises(ExportRefused, match="name an output root"):
            export_extrasolar_only(1, built.root, EXTRASOLAR_DIR)


class TestHostMerge:
    """A literature host that the second ingest joins to its Gaia twin, since
    only then does the catalogue give the values to compare."""

    def test_the_old_url_leads_to_the_planet_on_its_new_host(
        self, root, backup, tmp_path, out
    ):
        files = downloads()
        zeta = eu_planet("Zeta b", "Zeta", *offset(*ZETA, 0.8, 30), orbital_period="7")
        files.eu.append(zeta)
        ingest(root, backup, files.write(tmp_path / "one"))
        registry = Registry(root)
        literature = int(registry.lookup(EU, "catalog", ["Zeta"])[0])
        twin = int(registry.lookup("gaia", "dr3", ["606"])[0])
        assert literature != twin
        export_extrasolar(root, out, workers=1)
        first = ExportReader(out / "v1" / "x").planet(literature, 1)
        assert first is not None and first["designation"] == "Zeta b"

        zeta |= {"mag_v": "11.2", "star_distance": "100"}
        ingest(root, backup, files.write(tmp_path / "two"))
        assert Registry(root).lookup(EU, "catalog", ["Zeta"])[0] == twin
        with Registry(root).writer() as writer:
            for ingest_number in writer.unreviewed():
                writer.mark_reviewed(ingest_number)
        export_extrasolar(root, out, workers=1)
        reader = ExportReader(out / "v1" / "x")
        moved = reader.planet(literature, 1)
        assert moved is not None
        assert (moved["host"], moved["designation"]) == (twin, "Zeta b")
        assert reader.planet_index()["aliases"][f"{literature}/1"] == [
            twin,
            moved["number"],
        ]
        assert literature not in reader.planet_hosts()
        assert twin in reader.planet_hosts()
