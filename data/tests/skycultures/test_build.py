"""Tests for the sky-culture ingest from downloads to matched output."""

import json
from pathlib import Path

import pytest

from space_map_data.skycultures import build
from space_map_data.skycultures.build import Sources
from space_map_data.skycultures.resolve import DEEP_SKY, NOT_IN_SIMBAD
from tests.skycultures.registry import write_registry
from tests.skycultures.test_read import DESCRIPTION
from tests.skycultures.test_resolve import simbad_files

STELLARIUM_CULTURE = {
    "id": "test",
    "region": "Europe",
    "constellations": [
        {
            "id": "CON test A",
            "lines": [[100, 32349, "5350358584482202880"], [32349, "DSO:M44"]],
            "common_name": {"english": "A", "native": "Α"},
        }
    ],
    "common_names": {"HIP 32349": [{"english": "Sirius"}]},
}
BUCUR_CULTURE = {
    "id": "Test",
    "name": "Test",
    "region": "Americas",
    "licence": "CC BY-SA",
    "source": [],
    "constellations": [{"id": "CON Test 001", "lines": [["* by hip", "M  45"]]}],
    "common_names": {"NAME Milky Way": [{"english": "Path"}]},
}


def _metadata(directory: Path, **fields) -> None:
    (directory / "metadata.json").write_text(json.dumps(fields))


@pytest.fixture
def sources(tmp_path) -> Sources:
    stellarium = tmp_path / "stellarium"
    culture = stellarium / "skycultures" / "test"
    culture.mkdir(parents=True)
    (culture / "index.json").write_text(json.dumps(STELLARIUM_CULTURE))
    (culture / "description.md").write_text(DESCRIPTION)
    (stellarium / "skycultures" / "CMakeLists.txt").write_text(
        "ADD_SUBDIRECTORY( test )\n"
    )
    (stellarium / "skycultures" / "common_star_names.fab").write_text(
        ' 32349|_("Sirius") 2\n'
    )
    _metadata(stellarium, commit="s1")
    bucur = tmp_path / "bucur"
    (bucur / "json").mkdir(parents=True)
    (bucur / "json" / "Test.json").write_text(json.dumps(BUCUR_CULTURE))
    (bucur / "sources.bib").write_text("")
    _metadata(bucur, commit="b1")
    simbad = simbad_files(tmp_path / "simbad")
    _metadata(simbad, bucur_commit="b1")
    return Sources(stellarium, bucur, simbad)


@pytest.fixture
def registry_root(tmp_path) -> tuple[Path, list[int]]:
    root = tmp_path / "registry"
    minted = write_registry(
        root,
        [
            (101.3, -16.7, [("hip", "2007", "32349")]),
            (161.0, -59.7, [("gaia", "dr3", "5350358584482202880")]),
            (12.0, 30.0, [("hip", "2007", "100")]),
        ],
    )
    return root, minted


def _read(path: Path) -> dict:
    return json.loads(path.read_text())


class TestIngest:
    """Each culture gets a file with its objects resolved, and an index entry."""

    def test_stellarium_culture(self, tmp_path, sources, registry_root):
        root, (sirius, eta_car, hip100) = registry_root
        out = tmp_path / "out"
        build.ingest(root, out, sources)
        record = _read(out / "stellarium" / "test.json")
        assert record["name"] == "Test Sky"
        assert record["source"] == {"commit": "s1", "path": "skycultures/test"}
        figure = record["culture"]["constellations"][0]
        assert figure["lines"] == [
            [hip100, sirius, eta_car],
            [sirius, {"ref": "DSO:M44", "reason": DEEP_SKY, "designation": "M44"}],
        ]
        assert figure["common_name"] == {"english": "A", "native": "Α"}
        assert record["culture"]["common_names"] == [
            {"object": sirius, "names": [{"english": "Sirius"}]}
        ]
        assert record["counts"]["refs"] == 6
        assert record["counts"]["matched"] == 5
        assert record["counts"]["unresolved"] == {DEEP_SKY: 1}
        assert record["licence"]["distribution"] == "open"

    def test_bucur_culture_through_simbad(self, tmp_path, sources, registry_root):
        root, (_, _, hip100) = registry_root
        out = tmp_path / "out"
        build.ingest(root, out, sources)
        record = _read(out / "bucur" / "test.json")
        (chain,) = record["culture"]["constellations"][0]["lines"]
        assert chain[0] == hip100
        assert chain[1]["reason"] == DEEP_SKY
        assert chain[1]["designation"] == "Cl Melotte   22"
        names = record["culture"]["common_names"]
        assert names[0]["object"] == {"ref": "NAME Milky Way", "reason": NOT_IN_SIMBAD}

    def test_index_report_and_common_names(self, tmp_path, sources, registry_root):
        root, (sirius, _, _) = registry_root
        out = tmp_path / "out"
        report = build.ingest(root, out, sources)
        index = _read(out / "cultures.json")
        assert index["registry_ingest"] == 1
        assert index["commits"] == {"stellarium": "s1", "bucur": "b1"}
        assert [(c["dataset"], c["key"]) for c in index["cultures"]] == [
            ("stellarium", "test"),
            ("bucur", "test"),
        ]
        assert index["cultures"][0]["file"] == "stellarium/test.json"
        common = _read(out / "stellarium" / "common_star_names.json")
        assert common["culture"]["common_names"][0]["object"] == sirius
        assert common["licence"]["parts"] == [
            {"applies_to": "all", "licence": "GPL-2.0"}
        ]
        assert "stellarium/test: 6 refs, 5 matched; deep-sky 1" in report
        assert (out / "report.txt").read_text() == report

    def test_files_of_an_earlier_run_are_removed(
        self, tmp_path, sources, registry_root
    ):
        out = tmp_path / "out"
        (out / "stellarium").mkdir(parents=True)
        (out / "stellarium" / "gone.json").write_text("{}")
        build.ingest(registry_root[0], out, sources)
        assert not (out / "stellarium" / "gone.json").exists()

    def test_crosswalk_of_another_bucur_commit_fails(
        self, tmp_path, sources, registry_root
    ):
        _metadata(sources.simbad, bucur_commit="old")
        with pytest.raises(ValueError, match="run skyculture_simbad again"):
            build.ingest(registry_root[0], tmp_path / "out", sources)
