"""Checks for the census of the extrasolar export: the objects of each kind,
the bytes of their files, and the objects that each source feeds."""

import pytest

from space_map_data.export.extrasolar import census
from space_map_data.export.extrasolar.build import export_extrasolar
from space_map_data.export.extrasolar.planets import read_planets
from space_map_data.export.extrasolar.reader import ExportReader
from space_map_data.extrasolar.registry import Registry
from tests.extrasolar.export_registry import Built, Node, planet, star, write_registry


def _registry(root) -> Built:
    """A Gaia and Hipparcos star with a Gaia orbit, a Gaia star named from
    Wikidata, a SIMBAD star that is a point of two stars, the resolved pair
    of the first two, and a planet of the first."""

    def names(_systems, meta):
        meta[1] |= {"name_source": "wikidata"}
        meta[2] |= {"name_source": "simbad"}

    orbit = {"nss_solution_type": "Orbital", "orbit_source": "gaia-dr3"}
    return write_registry(
        root,
        [
            star(10.0, 10.0, hipparcos=True),
            star(10.001, 10.0),
            star(200.0, -40.0, gaia=False, simbad=True),
        ],
        orbits={0: orbit | {"masses_source": "gaia-dr3"}},
        systems=[
            Node((("star", 0, "A"), ("star", 1, "B"))),
            Node((("entry", None, "Aa"), ("entry", None, "Ab")), point=2),
        ],
        # A host in a system has the file of its root.
        planets=[planet(0, 1, system=("node", 0))],
        tamper=names,
    )


def _serial(task, jobs, _label):
    return [task(job) for job in jobs]


class TestSourceKey:
    def test_another_pass_is_its_catalogue(self):
        assert census.source_key("gaia-dr3-named", "astrometry") == "gaia-dr3"
        assert census.source_key("simbad-hip", "simbad_photometry") == "simbad"
        assert census.source_key("bailer-jones-2021", "distance") == "bailer-jones-2021"

    def test_a_group_of_its_own_catalogue(self):
        assert census.source_key("gaia-dr3", "apogee") == "apogee-dr17"
        assert census.source_key("hipparcos-2007", "pastel") == "pastel-2020"
        assert census.source_key("gaia-dr3", "fidelity") == "rybizki-2022"
        assert census.source_key("gaia-dr3", "masses") == "gaia-dr3-nss"

    def test_a_planet_orbit_is_its_pass(self):
        assert census.source_key("nasa-exoplanet-archive") == "nasa-exoplanet-archive"

    def test_wikidata_is_left_out(self):
        assert census.source_key("wikidata", "name") is None


class TestCensus:
    @pytest.fixture
    def objects(self, tmp_path) -> dict[str, dict]:
        built = _registry(tmp_path / "reg")
        with Registry(built.root).reader() as registry:
            return census.census(registry, _serial, read_planets(registry)).objects

    def test_each_id_counts_once_by_its_home_table(self, objects):
        # The point of two stars has its home in Point source.
        counts = {kind: entry["count"] for kind, entry in objects.items()}
        assert counts == {"star": 3, "star_system": 1, "planet": 1}

    def test_star_sources(self, objects):
        assert objects["star"]["sources"] == {
            "gaia-dr3": 2,
            "rybizki-2022": 2,
            "gaia-dr3-nss": 1,
            "hipparcos-2007": 1,
            "simbad": 1,
            "star-systems": 1,
        }

    def test_most_objects_first(self, objects):
        assert list(objects["star"]["sources"])[:2] == ["gaia-dr3", "rybizki-2022"]

    def test_system_and_planet_sources(self, objects):
        assert objects["star_system"]["sources"] == {"star-systems": 1}
        assert objects["planet"]["sources"] == {"nasa-exoplanet-archive": 1}


class TestServedCensus:
    def test_metadata_json_has_the_census_and_its_bytes(self, tmp_path):
        built = _registry(tmp_path / "reg")
        out = tmp_path / "space-map-extrasolar"
        export_extrasolar(built.root, out, workers=1)
        root = out / "v1" / "x"
        objects = ExportReader(root).metadata["objects"]
        assert {kind: entry["count"] for kind, entry in objects.items()} == {
            "star": 3,
            "star_system": 1,
            "planet": 1,
        }
        assert objects["star"]["sources"]["gaia-dr3"] == 2
        files = [
            path
            for path in root.rglob("*")
            if path.is_file()
            and path.name != "metadata.json"
            and "skycultures" not in path.parts
        ]
        total = sum(path.stat().st_size for path in files)
        sizes = [entry["size_bytes"] for entry in objects.values()]
        assert sum(sizes) == pytest.approx(total, abs=2)
        assert all(size > 0 for size in sizes)

        def tree(name):
            return sum(
                p.stat().st_size for p in (root / name).rglob("*") if p.is_file()
            )

        # The pair is one of two System rows and one of four live IDs; the
        # point's System row is that of a star.
        assert objects["star_system"]["size_bytes"] == pytest.approx(
            tree("system") / 2 + tree("metadata") / 4, abs=1
        )
