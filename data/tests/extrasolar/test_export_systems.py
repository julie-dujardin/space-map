"""The star systems in the extrasolar export: the System tiles, their checks,
the tier and the render tree."""

import pyarrow as pa
import pytest

from space_map_data.download.providers.stars import el_badry, msc, wds
from space_map_data.export.extrasolar import build, render, skycultures, tiles
from space_map_data.export.extrasolar.build import ExportRefused, export_extrasolar
from space_map_data.export.extrasolar.reader import ExportReader, NodeInfo
from space_map_data.extrasolar.registry import Registry
from space_map_data.extrasolar.tables import METADATA, SYSTEM, TABLES
from tests.extrasolar.export_registry import (
    Node,
    random_stars,
    star,
    write_registry,
)
from tests.extrasolar.test_export import _files


@pytest.fixture(autouse=True)
def _small(monkeypatch):
    monkeypatch.setitem(tiles.MAX_ROWS, "metadata", 12)
    monkeypatch.setitem(tiles.MAX_ROWS, "point-source", 4)
    monkeypatch.setitem(tiles.MAX_ROWS, "binary-orbit", 2)
    monkeypatch.setitem(tiles.MAX_ROWS, "system", 2)
    monkeypatch.setattr(render, "NODE_ROWS", 6)
    monkeypatch.setattr(render, "BATCH_ROWS", 40)


@pytest.fixture
def out(tmp_path):
    return tmp_path / "space-map-extrasolar"


# Node indexes of SYSTEMS.
AB, ALPHA_CEN, POINT, PAIR = range(4)


def _stars() -> list[dict]:
    """α Cen A, B and C (C has no 5σ parallax and its system's distance), a
    point that holds two stars, a resolved pair, and stars in no system."""
    proxima = star(217.43, -62.68, 768.0, 11.1, snr=3, distance=1.3)
    proxima |= {"distance_method": "system", "distance_source": "star-systems"}
    return [
        star(219.902, -60.834, 750.0, 0.5),
        star(219.896, -60.8375, 750.0, 1.4),
        proxima,
        star(80.0, 46.0, 76.0, 0.1, name="Capella"),
        star(120.0, -30.0, 5.0, 9.0),
        star(120.001, -30.0, 5.0, 9.5),
        *random_stars(30, seed=31),
    ]


SYSTEMS = [
    Node((("star", 0, "A"), ("star", 1, "B"))),
    Node(
        (("system", AB, "AB"), ("star", 2, "C")),
        label="AB-C",
        name="Alpha Centauri",
        qid="Q1",
    ),
    Node((("entry", None, "Aa"), ("entry", None, "Ab")), point=3),
    Node((("star", 4, "A"), ("star", 5, "B"))),
]


def _registry(path, systems=SYSTEMS, **kwargs):
    return write_registry(path, _stars(), systems=systems, **kwargs)


def _registry_rows(root) -> dict[int, dict]:
    with Registry(root).reader() as registry:
        parts = [
            registry.read_table(SYSTEM.slug, region)
            for region in registry.table_regions(SYSTEM.slug)
        ]
    rows = pa.concat_tables([part for part in parts if part is not None])
    return {row["id"]: row for row in rows.to_pylist()}


def _render_ids(reader: ExportReader) -> set[int]:
    found: set[int] = set()
    stack = ["r"]
    while stack:
        name = stack.pop()
        found.update(reader.node_ids(name).tolist())
        info = NodeInfo.of(reader.node(name))
        stack += [name + str(k) for k in range(8) if info.child_mask >> k & 1]
    return found


class TestSystemTiles:
    def test_every_table_has_tiles(self):
        assert set(tiles.MAX_ROWS) == {table.slug for table in (METADATA, *TABLES)}

    def test_each_node_is_found_with_its_row(self, tmp_path, out):
        built = _registry(tmp_path / "reg")
        report = export_extrasolar(built.root, out, workers=1)
        reader = ExportReader(out / "v1" / "x")
        entry = reader.metadata["tables"]["system"]
        assert entry["number"] == 3 and entry["rows"] == 4
        assert entry["distribution"] == "non-commercial"
        types = {c["name"]: c["type"] for c in entry["columns"]}
        assert types["members"] == types["tree"] == types["sources"] == "list"
        assert types["members.id"] == types["tree.id"] == types["parent"] == "id"
        assert types["members.kind"] == types["sources.item"] == "dict"
        assert types["members.known"] == "list"
        assert types["members.known.item"] == "dict"
        assert types["members.ids"] == "cross_ids"
        names = [c["name"] for c in entry["columns"]]
        assert names.index("members.id") == names.index("members") + 1
        assert report["systems"] == {
            "nodes": 4,
            "points": 1,
            "resolved": 3,
            "roots": 3,
            "member stars": 5,
            "member nodes": 1,
            "entries": 2,
            "deepest": 1,
            "largest system": 2,
        }

        stored = _registry_rows(built.root)
        for node_id in built.nodes:
            found = reader.lookup(str(node_id))
            assert found is not None
            assert found.rows["system"] == stored[node_id]
            assert found.metadata["mask"] >> 3 & 1
        root = reader.lookup(str(built.nodes[ALPHA_CEN]))
        assert root is not None and set(root.rows) == {"system"}
        assert root.metadata["name"] == "Alpha Centauri"
        assert root.metadata["class"] == "multiple star"
        assert root.metadata["system"] is None
        tree = root.rows["system"]["tree"]
        assert [n["id"] for n in tree] == sorted(built.nodes[:2])
        point = reader.lookup(str(built.nodes[POINT]))
        assert point is not None and set(point.rows) == {"point-source", "system"}
        assert point.metadata["class"] == "binary star"
        assert [m["letter"] for m in point.rows["system"]["members"]] == ["Aa", "Ab"]
        member = reader.lookup(str(built.ids[0]))
        assert member is not None and set(member.rows) == {"point-source"}
        assert member.metadata["system"] == built.nodes[ALPHA_CEN]
        inner = reader.lookup(str(built.nodes[AB]))
        assert inner is not None
        assert inner.metadata["system"] == built.nodes[ALPHA_CEN]

    def test_no_systems_still_has_the_table(self, tmp_path, out):
        built = write_registry(tmp_path / "reg", random_stars(10, seed=3))
        export_extrasolar(built.root, out, workers=1)
        entry = ExportReader(out / "v1" / "x").metadata["tables"]["system"]
        assert entry["rows"] == 0 and entry["tiles"] == 12

    def test_a_real_ingest_exports_its_systems(self, tmp_path, out, monkeypatch):
        """The System rows of chunk 3's ingest test, through the checks and the
        tiles."""
        from tests.extrasolar.test_systems_ingest import ingest

        root = tmp_path / "registry"
        ingest(root)
        report = export_extrasolar(root, out, workers=1)
        assert report["systems"]["nodes"] == 5
        reader = ExportReader(out / "v1" / "x")
        for node_id, row in _registry_rows(root).items():
            found = reader.lookup(str(node_id))
            assert found is not None and found.rows["system"] == row


class TestTiers:
    def test_the_strictest_tier_of_every_source(self):
        tiers = [wds.DISTRIBUTION, msc.DISTRIBUTION, el_badry.DISTRIBUTION]
        assert tiers == ["non-commercial", "non-commercial", "open"]
        assert [m.TERMS["distribution"] for m in (wds, msc, el_badry)] == tiers
        assert build.DISTRIBUTION == skycultures.combined("non-commercial", *tiers)
        assert build.DISTRIBUTION == "non-commercial"


class TestRenderTree:
    def test_a_resolved_system_is_not_drawn_and_a_star_at_its_distance_is(
        self, tmp_path, out
    ):
        built = _registry(tmp_path / "reg")
        report = export_extrasolar(built.root, out, workers=1)
        drawn = _render_ids(ExportReader(out / "v1" / "x"))
        resolved = {built.nodes[k] for k in (AB, ALPHA_CEN, PAIR)}
        assert not drawn & resolved
        assert built.ids[2] in drawn and built.nodes[POINT] in drawn
        assert report["render"]["placed by star-systems"] == 1
        assert drawn == set(built.ids)


def _tampered(change):
    """A tamper hook that changes the rows by node index and Metadata ID."""

    def tamper(system_rows: list[dict], meta_rows: list[dict]) -> None:
        change({n: row for n, row in enumerate(system_rows)}, meta_rows)

    return tamper


def _cycle(rows, _):
    rows[ALPHA_CEN]["parent"] = rows[AB]["id"]
    rows[AB]["members"].append({"id": rows[ALPHA_CEN]["id"], "kind": "system"})


def _two_parents(rows, _):
    rows[PAIR]["members"].append({"id": rows[AB]["id"], "kind": "system"})


def _two_systems(rows, _):
    rows[PAIR]["members"].append({"id": rows[AB]["members"][0]["id"], "kind": "star"})


def _short_tree(rows, _):
    rows[ALPHA_CEN]["tree"] = rows[ALPHA_CEN]["tree"][:1]


def _unlisted(rows, _):
    rows[ALPHA_CEN]["members"] = rows[ALPHA_CEN]["members"][1:]


def _depth(rows, _):
    rows[AB]["depth"] = 4


def _wrong_root(rows, _):
    rows[AB]["root"] = rows[PAIR]["id"]


def _foreign_primary(rows, _):
    rows[PAIR]["primary"] = rows[AB]["primary"]


def _metadata_system(rows, meta):
    star_a = rows[AB]["members"][0]["id"]
    next(row for row in meta if row["id"] == star_a)["system"] = None


def _stray_system(rows, meta):
    lone = next(row for row in meta if row["system"] is None and row["mask"] == 2)
    lone["system"] = rows[PAIR]["id"]


def _unmarked(rows, meta):
    next(row for row in meta if row["id"] == rows[POINT]["id"])["mask"] = 2


class TestChecks:
    """Each broken tree is refused, and the served export stays."""

    @pytest.mark.parametrize(
        ("change", "message"),
        [
            (_cycle, "node in a cycle of parents"),
            (_two_parents, "ID that is a member of two nodes"),
            (_two_systems, "ID that is a member of two nodes"),
            (_short_tree, "root whose tree does not hold its nodes"),
            (_unlisted, "node that its parent does not list"),
            (_depth, "depth that does not count the steps"),
            (_wrong_root, "root that is not the end of the node's parents"),
            (_foreign_primary, "primary outside its node's system"),
            (_metadata_system, "Metadata system that is not the root"),
            (_stray_system, "Metadata system on an ID that no tree holds"),
            (_unmarked, "node without the System bit"),
        ],
    )
    def test_a_broken_tree(self, tmp_path, out, change, message):
        export_extrasolar(_registry(tmp_path / "a").root, out, workers=1)
        served = _files(out / "v1" / "x")
        broken = _registry(tmp_path / "b", tamper=_tampered(change))
        with pytest.raises(ExportRefused, match=message):
            export_extrasolar(broken.root, out, workers=1)
        assert _files(out / "v1" / "x") == served

    def test_a_member_that_is_not_live(self, tmp_path, out):
        retired = _registry(tmp_path / "reg", retired=[2])
        with pytest.raises(ExportRefused, match="no live Metadata row"):
            export_extrasolar(retired.root, out, workers=1)

    def test_a_served_system_id_keeps_the_rule_of_every_id(self, tmp_path, out):
        export_extrasolar(_registry(tmp_path / "a").root, out, workers=1)
        dropped = _registry(tmp_path / "b", systems=SYSTEMS[:PAIR])
        with pytest.raises(ExportRefused, match="served ID missing"):
            export_extrasolar(dropped.root, out, workers=1)

        def relabel(_, meta):
            for row in meta:
                for item in row["cross_ids"] or []:
                    if item["catalogue"] == "star-system":
                        item["catalogue_id"] += "x"

        changed = _registry(tmp_path / "c", tamper=relabel)
        with pytest.raises(ExportRefused, match="served ID lost catalogue ids"):
            export_extrasolar(changed.root, out, workers=1)
