"""Tests for the sky-culture table of the extrasolar export."""

import gzip
import json
from pathlib import Path

import numpy as np
import pytest

from space_map_data.export.extrasolar import render, skycultures
from space_map_data.export.extrasolar.build import ExportRefused, export_extrasolar
from space_map_data.export.extrasolar.reader import ExportReader, NodeInfo
from space_map_data.extrasolar.ids import cell_of
from space_map_data.extrasolar.registry import Registry
from space_map_data.extrasolar.sky import region_of
from space_map_data.skycultures.licences import NON_COMMERCIAL, UNDECIDED
from tests.extrasolar.export_registry import star, write_registry
from tests.extrasolar.test_export import _expected_position

STARS = [
    star(100.0, 20.0, 50.0, name="Gaia star"),
    star(101.0, 21.0, 40.0, gaia=False, name="Hipparcos star"),
    star(102.0, 22.0, 2.0, snr=3, name="No distance"),
    star(103.0, 23.0, 30.0),
]
DEEP_SKY = {"ref": "DSO:M44", "reason": "deep-sky", "designation": "M44"}


def _licence(distribution: str, flags: list[str]) -> dict:
    parts = (
        []
        if distribution == UNDECIDED
        else [{"applies_to": "all", "licence": "CC BY-SA 4.0"}]
    )
    return {"text": "", "parts": parts, "distribution": distribution, "flags": flags}


def _record(dataset: str, key: str, culture: dict, distribution: str = "open") -> dict:
    return {
        "dataset": dataset,
        "key": key,
        "name": key.title(),
        "region": "Europe",
        "subregion": None,
        "source": {"commit": "c1", "path": f"skycultures/{key}"},
        "packaged": True,
        "licence": _licence(
            distribution, [] if distribution == "open" else ["no-licence"]
        ),
        "authors": "By *Some One*, [some@one.test](mailto:some@one.test).",
        "culture": culture,
    }


def write_cultures(directory: Path, ids: list[int], ingest: int = 1) -> Path:
    """Matched cultures in the layout of `space-map-ingest --targets skycultures`."""
    a, b, c, d = ids
    figure = {
        "id": "CON test A",
        "lines": [[a, b, c], [b, DEEP_SKY, [19.4, -23.8]]],
        "common_name": {
            "native": "Α",
            "english": "A",
            "pronounce": "a",
            "context": "x",
        },
    }
    asterism = {"id": "AST test B", "lines": [[a, d]], "is_ray_helper": True}
    names = [
        {"object": d, "names": [{"english": "Dee", "references": [1]}]},
        {
            "object": {"ref": "NAME Venus", "reason": "solar-system"},
            "names": [{"english": "V"}],
        },
    ]
    stellarium = _record(
        "stellarium",
        "test",
        {"constellations": [figure], "asterisms": [asterism], "common_names": names},
    )
    bucur = _record(
        "bucur",
        "other",
        {
            "constellations": [
                {
                    "id": "CON other 1",
                    "names": [{"english": "O"}],
                    "lines": [],
                    "IAU": "Ori",
                }
            ]
        },
        UNDECIDED,
    )
    common = _record(
        "stellarium",
        "common_star_names",
        {"common_names": [{"object": a, "names": [{"english": "Ay"}]}]},
    )
    for record in (stellarium, bucur, common):
        path = directory / record["dataset"] / f"{record['key']}.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(record))
    index = {
        "registry_ingest": ingest,
        "commits": {"stellarium": "c1", "bucur": "c2"},
        "cultures": [
            {"file": "stellarium/test.json"},
            {"file": "bucur/other.json"},
        ],
    }
    (directory / "cultures.json").write_text(json.dumps(index))
    return directory


@pytest.fixture
def exported(tmp_path, monkeypatch):
    monkeypatch.setattr(skycultures, "AUTHORS", {"test": ("Some One", "Gone Away")})
    built = write_registry(tmp_path / "reg", STARS)
    cultures = write_cultures(tmp_path / "cultures", built.ids)
    out = tmp_path / "out"
    report = export_extrasolar(built.root, out, workers=1, cultures_dir=cultures)
    return ExportReader(out / "v1" / "x"), built.ids, report


class TestCultureFile:
    """Figures index the members; a member has its ID and its tree position."""

    def test_members_figures_and_names(self, exported):
        reader, (a, b, c, d), _ = exported
        content = reader.culture("skycultures/test.json.gz")
        members = content["members"]
        assert [m.get("id") for m in members] == [a, b, c, None, None, d, None]
        assert members[3] == DEEP_SKY
        assert members[4] == {"ra_hours": 19.4, "dec": -23.8}
        assert members[6] == {"ref": "NAME Venus", "reason": "solar-system"}
        figure, asterism = content["figures"]
        assert figure == {
            "id": "CON test A",
            "kind": "constellation",
            "names": [{"native": "Α", "english": "A", "pronounce": "a"}],
            "lines": [[0, 1, 2], [1, 3, 4]],
        }
        assert asterism["kind"] == "asterism" and asterism["ray_helper"]
        assert asterism["lines"] == [[0, 5]]
        assert content["names"] == [
            {"member": 5, "names": [{"english": "Dee"}]},
            {"member": 6, "names": [{"english": "V"}]},
        ]

    def test_positions_are_the_render_positions(self, exported):
        reader, ids, _ = exported
        members = reader.culture("skycultures/test.json.gz")["members"]
        by_id = {m["id"]: m for m in members if "id" in m}
        for row, id_ in zip(STARS, ids):
            if row["_name"] == "No distance":
                assert "position" not in by_id[id_]
                continue
            position = np.array(by_id[id_]["position"])
            np.testing.assert_allclose(position, _expected_position(row), rtol=1e-12)
            # The rendered star: its node's centre plus the float32 offset.
            name, at = reader.find_render(id_, tuple(position))
            node = reader.node(name)
            info = NodeInfo.of(node)
            drawn = [
                info.centre[k] + float(node.numpy(axis)[at])
                for k, axis in enumerate("xyz")
            ]
            np.testing.assert_allclose(drawn, position, atol=info.half * 2.0**-23)

    def test_positions_equal_the_tree_build_float64(self, tmp_path, exported):
        reader, ids, _ = exported
        members = reader.culture("skycultures/test.json.gz")["members"]
        found = {m["id"]: m["position"] for m in members if "position" in m}
        assert set(found) == {ids[0], ids[1], ids[3]}
        registry = Registry(tmp_path / "reg")
        with registry.reader():
            for region in sorted({int(region_of(cell_of(i))) for i in found}):
                table = registry.read_table(
                    "point-source", region, list(render.COLUMNS)
                )
                rows, _ = render.render_rows(table)
                for at, id_ in enumerate(rows["id"].tolist()):
                    if id_ in found:
                        xyz = [float(rows[axis][at]) for axis in "xyz"]
                        assert found[id_] == xyz


class TestMetadata:
    """The table is listed with its token, and each culture with its terms."""

    def test_index_entry(self, exported):
        reader, _, report = exported
        entry = reader.metadata["skycultures"]
        assert entry["token"] == report["tokens"]["skycultures"]
        assert entry["file"] == "skycultures/{key}.json.gz"
        assert entry["international_names"] == "skycultures/common_star_names.json.gz"
        assert entry["units"] == "pc" and "J2016.0" in entry["frame"]
        test, other = entry["cultures"]
        assert test["file"] == "skycultures/test.json.gz"
        assert test["licence"]["distribution"] == "open"
        assert test["distribution"] == NON_COMMERCIAL
        assert test["credit"]["source"] == (
            "https://github.com/Stellarium/stellarium/tree/c1/skycultures/test"
        )
        assert (test["members"], test["positioned"], test["unresolved"]) == (7, 3, 2)
        assert other["distribution"] == UNDECIDED
        assert other["flags"] == ["no-licence"]
        assert report["skycultures"]["files"] == 3

    def test_every_file_has_the_token(self, exported):
        reader, _, _ = exported
        entry = reader.metadata["skycultures"]
        paths = [c["file"] for c in entry["cultures"]] + [entry["international_names"]]
        for path in paths:
            assert reader.culture(path)["token"] == entry["token"]

    def test_rerun_keeps_token_and_bytes(self, tmp_path, exported):
        reader, _, _ = exported
        before = (reader.root / "skycultures/test.json.gz").read_bytes()
        cultures = tmp_path / "cultures"
        export_extrasolar(
            tmp_path / "reg", tmp_path / "out", workers=1, cultures_dir=cultures
        )
        again = ExportReader(tmp_path / "out" / "v1" / "x")
        assert (
            again.metadata["skycultures"]["token"]
            == reader.metadata["skycultures"]["token"]
        )
        assert (again.root / "skycultures/test.json.gz").read_bytes() == before
        assert gzip.decompress(before).endswith(b"\n")


class TestCredit:
    """A culture's credit names its authors as plain text."""

    def test_names_only_and_only_those_in_the_section(self, exported, caplog):
        reader, _, _ = exported
        test, other = reader.metadata["skycultures"]["cultures"]
        assert test["credit"]["authors"] == ["Some One"]
        assert "attribution" not in test["credit"]
        assert "authors" not in other["credit"]
        setup = caplog.get_records("setup")
        assert any("'Gone Away' is not in" in r.getMessage() for r in setup)

    def test_a_name_missing_from_the_section_is_logged(self, caplog):
        record = {"dataset": "stellarium", "key": "test", "authors": "Ra&#250;l Pé"}
        with caplog.at_level("WARNING"):
            names = skycultures.authors(record)
        assert names == []
        assert "no author names" in caplog.text

    def test_entities_spacing_and_case_do_not_matter(self, monkeypatch):
        monkeypatch.setattr(skycultures, "AUTHORS", {"x": ("Raúl Pérez", "Yang Bo")})
        record = {
            "dataset": "stellarium",
            "key": "x",
            "authors": "**Ra&#250;l Pérez**: [mail](mailto:a@b.c), Dr. YANG  Bo",
        }
        assert skycultures.authors(record) == ["Raúl Pérez", "Yang Bo"]


def _figures(*names_and_lines) -> dict:
    return {
        "constellations": [
            {"id": f"CON {i}", "names": [{"english": name}], "lines": lines}
            for i, (name, lines) in enumerate(names_and_lines)
        ]
    }


STELLARIUM_FIGURES = _figures(("Net", [[1, 2, 3, 4]]), ("Bird", [[5, 6, 7]]))


class TestSelect:
    """One directory: Stellarium wins a key, and Bucur's copies are left out."""

    def test_stellarium_wins_a_key_in_any_case(self):
        records = [
            _record("stellarium", "anutan", STELLARIUM_FIGURES),
            _record("bucur", "Anutan", _figures(("Other", [[8, 9]]))),
            _record("bucur", "common_star_names", _figures(("Other", [[8, 9]]))),
        ]
        kept, left_out = skycultures.select(records)
        assert [(r["dataset"], r["key"]) for r in kept] == [("stellarium", "anutan")]
        assert left_out == [
            "bucur/Anutan: Stellarium has the key Anutan",
            "bucur/common_star_names: Stellarium has the key common_star_names",
        ]

    def test_a_copy_under_another_key_is_left_out(self):
        copy = _figures(("Net", [[1, 2, 3, 4]]), ("bird", [[5, 6], [6, 7]]))
        records = [
            _record("stellarium", "anutan", STELLARIUM_FIGURES),
            _record("bucur", "anuta", copy),
        ]
        kept, left_out = skycultures.select(records)
        assert [r["key"] for r in kept] == ["anutan"]
        assert left_out == [
            (
                "bucur/anuta: a copy of stellarium/anutan, sharing 1.00 of the"
                " segments and 1.00 of the figure names"
            )
        ]

    def test_a_culture_that_adds_figures_is_kept(self):
        more = _figures(
            ("Net", [[1, 2, 3, 4]]),
            ("Bird", [[5, 6, 7]]),
            ("Canoe", [[10, 11, 12, 13, 14, 15]]),
            ("Shark", [[16, 17, 18, 19]]),
        )
        records = [
            _record("stellarium", "anutan", STELLARIUM_FIGURES),
            _record("bucur", "anuta", more),
        ]
        shared_segments, shared_names = skycultures.same_culture(records[1], records[0])
        assert shared_segments < skycultures.SAME_SEGMENTS <= shared_names
        assert [r["key"] for r in skycultures.select(records)[0]] == ["anutan", "anuta"]

    def test_the_same_lines_under_other_names_are_kept(self):
        renamed = _figures(("Fish", [[1, 2, 3, 4]]), ("Spear", [[5, 6, 7]]))
        records = [
            _record("stellarium", "anutan", STELLARIUM_FIGURES),
            _record("bucur", "other", renamed),
        ]
        assert skycultures.same_culture(records[1], records[0]) == (1.0, 0.0)
        assert len(skycultures.select(records)[0]) == 2

    def test_the_export_leaves_them_out_and_reports_them(self, tmp_path):
        built = write_registry(tmp_path / "reg", STARS)
        cultures = write_cultures(tmp_path / "cultures", built.ids)
        twin = json.loads((cultures / "stellarium" / "test.json").read_text())
        twin |= {"dataset": "bucur", "key": "Test"}
        (cultures / "bucur" / "Test.json").write_text(json.dumps(twin))
        index = json.loads((cultures / "cultures.json").read_text())
        index["cultures"].append({"file": "bucur/Test.json"})
        (cultures / "cultures.json").write_text(json.dumps(index))
        out = tmp_path / "out"
        report = export_extrasolar(built.root, out, workers=1, cultures_dir=cultures)
        entry = ExportReader(out / "v1" / "x").metadata["skycultures"]
        assert [c["key"] for c in entry["cultures"]] == ["test", "other"]
        assert report["skycultures_left_out"] == [
            "bucur/Test: Stellarium has the key Test"
        ]
        assert sorted(p.name for p in (out / "v1/x/skycultures").iterdir()) == [
            "common_star_names.json.gz",
            "other.json.gz",
            "test.json.gz",
        ]


class TestChecks:
    """Cultures of another registry ingest are refused; none is no table."""

    def test_another_ingest_is_refused(self, tmp_path):
        built = write_registry(tmp_path / "reg", STARS)
        cultures = write_cultures(tmp_path / "cultures", built.ids, ingest=2)
        with pytest.raises(ExportRefused, match="--targets skycultures"):
            export_extrasolar(
                built.root, tmp_path / "out", workers=1, cultures_dir=cultures
            )

    def test_no_matched_cultures_gives_no_table(self, tmp_path):
        built = write_registry(tmp_path / "reg", STARS)
        report = export_extrasolar(built.root, tmp_path / "out", workers=1)
        meta = ExportReader(tmp_path / "out" / "v1" / "x").metadata
        assert "skycultures" not in meta
        assert report["skycultures"]["files"] == 0


class TestCombined:
    """The tier of a file is the strictest of the culture and Gaia."""

    def test_ladder(self):
        assert skycultures.combined("open", NON_COMMERCIAL) == NON_COMMERCIAL
        assert skycultures.combined("site-only", NON_COMMERCIAL) == "site-only"
        assert skycultures.combined(UNDECIDED, NON_COMMERCIAL) == UNDECIDED
