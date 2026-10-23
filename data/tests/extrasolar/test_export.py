import json
import os
import socket
from pathlib import Path

import numpy as np
import pytest

from space_map_data.export.extrasolar import build, container, render, tiles
from space_map_data.export.extrasolar.build import ExportRefused, export_extrasolar
from space_map_data.export.extrasolar.container import Column
from space_map_data.export.extrasolar.reader import ExportReader, NodeInfo
from space_map_data.extrasolar import ids
from space_map_data.extrasolar.registry import Registry, RegistryBusy
from space_map_data.extrasolar.sources.hipparcos import propagate
from tests.extrasolar.export_registry import HOST, random_stars, star, write_registry


@pytest.fixture(autouse=True)
def _small(monkeypatch):
    """Tiles, nodes and batches small enough to split a few hundred stars."""
    monkeypatch.setitem(tiles.MAX_ROWS, "metadata", 12)
    monkeypatch.setitem(tiles.MAX_ROWS, "point-source", 4)
    monkeypatch.setattr(render, "NODE_ROWS", 6)
    monkeypatch.setattr(render, "BATCH_ROWS", 40)


@pytest.fixture
def out(tmp_path):
    return tmp_path / "space-map-extrasolar"


def _special() -> list[dict]:
    return [
        star(10.0, 5.0, 2.0, gaia=False, snr=3),  # no 5σ parallax
        star(11.0, 5.0, 50.0, gaia=False, v_i=1.0, name="Hipparcos only"),
        star(12.0, 5.0, 20.0, fidelity=0.2),  # flagged, not rendered
        star(13.0, 5.0, 20.0, fidelity=0.2, hipparcos=True),  # flagged, matched
        star(14.0, 5.0, 20.0, fidelity=None),
        star(15.0, 5.0, 20.0, g=None),  # no magnitude
    ]


def _files(root):
    return {
        path.relative_to(root).as_posix(): path.read_bytes()
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


def _expected_position(row: dict) -> np.ndarray:
    ra, dec = np.array([row["ra"]]), np.array([row["dec"]])
    if row["epoch"] != render.EPOCH:
        ra, dec = propagate(
            ra,
            dec,
            np.array([row["pmra"]], np.float32).astype(float),
            np.array([row["pmdec"]], np.float32).astype(float),
            render.EPOCH - row["epoch"],
        )
    # The table stores parallax as float32.
    d = 1000 / float(np.float32(row["parallax"]))
    ra, dec = np.radians(ra[0]), np.radians(dec[0])
    return d * np.array(
        [np.cos(dec) * np.cos(ra), np.cos(dec) * np.sin(ra), np.sin(dec)]
    )


class TestExport:
    """Tiles, the render tree and metadata.json of a synthetic registry."""

    def test_every_star_is_found_as_a_client_finds_it(self, tmp_path, out):
        stars = random_stars(150, around=(100, 20)) + random_stars(60) + _special()
        built = write_registry(tmp_path / "reg", stars)
        report = export_extrasolar(built.root, out, workers=1)
        reader = ExportReader(out / "v1" / "x")
        meta = reader.metadata
        assert meta["registry"] == {"ingest": 1, "host": "test-host"}
        assert set(meta["tables"]) == {"metadata", "point-source"}
        assert meta["tables"]["point-source"]["number"] == 1
        assert meta["tables"]["metadata"]["number"] is None
        assert meta["trees"]["mw"]["range_limit_mag"] == render.RANGE_LIMIT_MAG
        assert meta["tables"]["point-source"]["distribution"] == "non-commercial"
        assert meta["tables"]["point-source"]["tiles"] > 12
        assert (
            report["tables"]["point-source"]["files"]
            == (meta["tables"]["point-source"]["tiles"])
        )

        rendered = 0
        for id_, row in zip(built.ids, stars):
            found = reader.lookup(str(id_))
            assert found is not None and found.id == id_
            assert found.metadata["name"] == (row["_name"] or f"Star {id_}")
            point = found.rows["point-source"]
            assert point["ra"] == row["ra"] and point["dec"] == row["dec"]
            position = _expected_position(row)
            hit = reader.find_render(id_, tuple(position))
            positioned = row["parallax"] / row["parallax_error"] > 5
            trusted = (row.get("fidelity_v2") or 1) >= 0.5 or "hp_mag" in row
            has_mag = row.get("phot_g_mean_mag") is not None or "hp_mag" in row
            assert (hit is not None) == (positioned and trusted and has_mag), row
            if hit is None:
                continue
            rendered += 1
            name, at = hit
            node = reader.node(name)
            info = NodeInfo.of(node)
            drawn = [
                node.column(axis)[at].as_py() + c for axis, c in zip("xyz", info.centre)
            ]
            # float32 relative to the centre: steps of half · 2^-24 or finer.
            assert np.abs(np.array(drawn) - position).max() <= info.half * 2**-23
        assert rendered == report["render"]["rendered"] == len(stars) - 3

        assert reader.lookup(str(ids.encode(5, 1, 1234))) is None
        assert reader.lookup(str(ids.encode(0, 2, 1234))) is None
        assert reader.lookup("0" + str(built.ids[0])) is None

    def test_tree_invariants(self, tmp_path, out):
        built = write_registry(tmp_path / "reg", random_stars(300, seed=4))
        export_extrasolar(built.root, out, workers=1)
        reader = ExportReader(out / "v1" / "x")
        assert reader.tree["centre"] == list(render.ROOT_CENTRE)
        assert NodeInfo.of(reader.node("r")).centre == render.ROOT_CENTRE
        seen = 0
        stack = [("r", np.inf)]
        while stack:
            name, ceiling = stack.pop()
            node = reader.node(name)
            info = NodeInfo.of(node)
            ranges = node.numpy("range")
            assert 0 < node.rows <= render.NODE_ROWS
            assert reader.node_ids(name).size == node.rows
            assert ranges.max() == pytest.approx(info.max_range)
            assert ranges.min() == pytest.approx(info.min_range)
            assert info.max_range <= ceiling
            for axis in "xyz":
                assert np.abs(node.numpy(axis)).max() <= info.half * 1.0001
            seen += node.rows
            for k in range(8):
                if info.child_mask >> k & 1:
                    child = NodeInfo.of(reader.node(name + str(k)))
                    assert child.max_range == info.child_range[k]
                    assert child.half == info.half / 2
                    stack.append((name + str(k), info.min_range))
                else:
                    assert info.child_range[k] == 0
        assert seen == 300

    def test_aliases_collapse_and_retired_ids_have_no_row(self, tmp_path, out):
        stars = random_stars(8, seed=2)
        built = write_registry(
            tmp_path / "reg",
            stars,
            aliases=[(0, 1), (1, 2), (3, 4)],
            retired=[4, 5],
        )
        export_extrasolar(built.root, out, workers=1)
        reader = ExportReader(out / "v1" / "x")
        a, b, c = built.ids[:3]
        for alias in (a, b):
            row = reader.row("metadata", alias)
            assert row is not None and row["alias_target"] == c
            found = reader.lookup(str(alias))
            assert found is not None
            assert found.id == c and found.redirected_from == alias
            assert reader.row("point-source", alias) is None
        # An alias whose chain ends at a retired ID is a 404, as the retired IDs.
        for gone in built.ids[3:6]:
            assert reader.lookup(str(gone)) is None
            assert reader.row("metadata", gone) is None
        assert reader.lookup(str(built.ids[6])) is not None

    def test_rerun_keeps_tokens_and_bytes(self, tmp_path, out):
        built = write_registry(tmp_path / "reg", random_stars(120, seed=3))
        first = export_extrasolar(built.root, out, workers=1)
        files = _files(out / "v1" / "x")
        second = export_extrasolar(built.root, out, workers=1)
        assert first["tokens"] == second["tokens"]
        again = _files(out / "v1" / "x")
        assert files.keys() == again.keys()
        for path, data in files.items():
            if path != "metadata.json":
                assert again[path] == data, path
        tokens = json.loads(again["metadata.json"])
        assert tokens["tables"]["metadata"]["token"] == first["tokens"]["metadata"]

    def test_only_the_tiles_read_every_column(self, tmp_path, out, monkeypatch):
        built = write_registry(tmp_path / "reg", random_stars(30, seed=15))
        reads = set()
        real = Registry.read_table

        def read_table(self, slug, region, columns=None):
            reads.add((slug, None if columns is None else tuple(columns)))
            return real(self, slug, region, columns)

        monkeypatch.setattr(Registry, "read_table", read_table)
        export_extrasolar(built.root, out, workers=1)
        assert reads == {
            ("metadata", ("id",)),
            ("metadata", None),
            ("point-source", ("id",)),
            ("point-source", None),
            ("point-source", render.COLUMNS),
        }

    def test_worker_processes_give_the_same_files(self, tmp_path, out):
        built = write_registry(tmp_path / "reg", random_stars(80, seed=9))
        inline = export_extrasolar(built.root, tmp_path / "inline", workers=1)
        pooled = export_extrasolar(built.root, out, workers=2)
        assert inline["tokens"] == pooled["tokens"]


class TestChecks:
    """The export refuses, and the served export stays as it was."""

    def test_unreviewed_merges(self, tmp_path, out):
        built = write_registry(
            tmp_path / "reg", random_stars(5), aliases=[(0, 1)], reviewed=False
        )
        with pytest.raises(ExportRefused, match="reviewed"):
            export_extrasolar(built.root, out, workers=1)
        assert not (out / "v1").exists()

    def test_an_id_the_registry_lacks(self, tmp_path, out):
        stray = ids.encode(9, 1, 4321)
        built = write_registry(
            tmp_path / "reg", random_stars(5), extra_table_ids=[stray]
        )
        with pytest.raises(ExportRefused, match="not in the registry"):
            export_extrasolar(built.root, out, workers=1)
        assert not (out / "v1" / "x").exists()
        assert not (out / "v1" / ".x-staging").exists()

    def test_a_served_id_goes_missing(self, tmp_path, out):
        stars = random_stars(40, seed=5)
        export_extrasolar(write_registry(tmp_path / "a", stars).root, out, workers=1)
        served = _files(out / "v1" / "x")
        rolled_back = write_registry(tmp_path / "b", stars, missing=[7])
        with pytest.raises(ExportRefused, match="served ID missing"):
            export_extrasolar(rolled_back.root, out, workers=1)
        assert _files(out / "v1" / "x") == served
        assert sorted(p.name for p in (out / "v1").iterdir()) == ["x"]
        assert not (out / ".build").exists()
        # Retired, the same ID may go.
        retired = write_registry(tmp_path / "c", stars, retired=[7])
        export_extrasolar(retired.root, out, workers=1)
        assert ExportReader(out / "v1" / "x").lookup(str(retired.ids[7])) is None

    def test_a_served_id_changes_its_catalogue_ids(self, tmp_path, out):
        stars = random_stars(20, seed=6)
        export_extrasolar(write_registry(tmp_path / "a", stars).root, out, workers=1)
        stars[3]["_xid"] = "999"
        with pytest.raises(ExportRefused, match="lost catalogue ids"):
            export_extrasolar(
                write_registry(tmp_path / "b", stars).root, out, workers=1
            )
        # An alias may lose its catalogue ids to its survivor.
        merged = write_registry(tmp_path / "c", stars, aliases=[(3, 4)])
        export_extrasolar(merged.root, out, workers=1)

    def test_a_failed_build_keeps_the_served_export(self, tmp_path, out, monkeypatch):
        built = write_registry(tmp_path / "reg", random_stars(30, seed=7))
        export_extrasolar(built.root, out, workers=1)
        served = _files(out / "v1" / "x")

        def broken(job):
            raise OSError("disk full")

        monkeypatch.setattr(render, "build_batch", broken)
        with pytest.raises(OSError):
            export_extrasolar(built.root, out, workers=1)
        assert _files(out / "v1" / "x") == served
        assert sorted(p.name for p in (out / "v1").iterdir()) == ["x"]
        assert not (out / ".build").exists()

    def test_a_stopped_swap_is_undone(self, tmp_path, out):
        built = write_registry(tmp_path / "reg", random_stars(30, seed=8))
        export_extrasolar(built.root, out, workers=1)
        (out / "v1" / "x").rename(out / "v1" / ".x-old")
        (out / "v1" / ".x-staging").mkdir()
        export_extrasolar(built.root, out, workers=1)
        assert sorted(p.name for p in (out / "v1").iterdir()) == ["x"]

    def test_a_failed_swap_keeps_the_served_export(self, tmp_path, out, monkeypatch):
        built = write_registry(tmp_path / "reg", random_stars(30, seed=12))
        export_extrasolar(built.root, out, workers=1)
        served = _files(out / "v1" / "x")
        real = Path.rename

        def rename(self, target):
            if self.name == ".x-staging":
                raise OSError("rename failed")
            return real(self, target)

        monkeypatch.setattr(Path, "rename", rename)
        with pytest.raises(OSError, match="rename failed"):
            export_extrasolar(built.root, out, workers=1)
        assert _files(out / "v1" / "x") == served
        assert sorted(p.name for p in (out / "v1").iterdir()) == ["x"]

    def test_a_short_served_split_table_is_named(self, tmp_path, out):
        built = write_registry(tmp_path / "reg", random_stars(10, seed=13))
        export_extrasolar(built.root, out, workers=1)
        short = [Column("split", "bits", np.array([True]))]
        container.write(
            out / "v1" / "x",
            f"metadata/{tiles.SPLIT_FILE}",
            container.encode(container.KIND_SPLIT, 1, short),
        )
        with pytest.raises(container.FormatError, match="metadata/split.bin.gz"):
            export_extrasolar(built.root, out, workers=1)


class TestRegistryLock:
    """The export reads one state of the registry, and no ingest changes it."""

    @pytest.fixture(autouse=True)
    def _minting_host(self, monkeypatch):
        monkeypatch.setattr(socket, "gethostname", lambda: HOST)

    def test_an_ingest_cannot_start_during_the_export(self, tmp_path, out, monkeypatch):
        built = write_registry(tmp_path / "reg", random_stars(30, seed=10))
        busy = []
        real = tiles.build_unit

        def build_unit(job):
            try:
                with Registry(built.root).writer():
                    busy.append(False)
            except RegistryBusy:
                busy.append(True)
            return real(job)

        monkeypatch.setattr(tiles, "build_unit", build_unit)
        export_extrasolar(built.root, out, workers=1)
        assert busy and all(busy)

    def test_the_export_refuses_while_an_ingest_runs(self, tmp_path, out):
        built = write_registry(tmp_path / "reg", random_stars(5))
        with (
            Registry(built.root).writer(),
            pytest.raises(ExportRefused, match="an ingest"),
        ):
            export_extrasolar(built.root, out, workers=1)
        assert not (out / "v1").exists()

    def test_no_registry(self, tmp_path, out):
        with pytest.raises(ExportRefused, match="no registry"):
            export_extrasolar(tmp_path / "none", out, workers=1)
        (tmp_path / "empty" / "registry").mkdir(parents=True)
        with pytest.raises(ExportRefused, match="no registry"):
            export_extrasolar(tmp_path / "empty", out, workers=1)

    def test_workers_read_the_tables_named_at_the_start(
        self, tmp_path, out, monkeypatch
    ):
        stars = random_stars(40, seed=11)
        built = write_registry(tmp_path / "reg", stars)
        manifest_path = built.root / "registry" / "manifest.json"
        real = build._previous

        def previous(layout):
            # The manifest on disk names table versions that have no files.
            manifest = json.loads(manifest_path.read_text())
            manifest["tables"] = {"metadata": 2, "point-source": 2}
            manifest_path.write_text(json.dumps(manifest))
            return real(layout)

        monkeypatch.setattr(build, "_previous", previous)
        report = export_extrasolar(built.root, out, workers=2)
        reader = ExportReader(out / "v1" / "x")
        assert reader.metadata["tables"]["metadata"]["rows"] == len(stars)
        assert report["render"]["rows"] == len(stars)
        assert all(reader.lookup(str(id_)) is not None for id_ in built.ids)


class TestRootCentre:
    """The root's place: the Sun is well inside a node at every depth."""

    def test_the_sun_is_a_third_of_a_node_from_each_face(self):
        centre, half = np.array(render.ROOT_CENTRE), render.HALF_SIZE
        keys = render.morton_keys(np.zeros(1), np.zeros(1), np.zeros(1))
        for depth in range(render.KEY_LEVELS + 1):
            assert (half - np.abs(centre)).min() > 0.32 * 2 * half, depth
            if depth == render.KEY_LEVELS:
                break
            # The Sun's side of the centre on each axis, and the key's digit.
            plus = centre <= 0
            digit = int(keys[0]) >> (3 * (render.KEY_LEVELS - 1 - depth)) & 7
            assert digit == sum(1 << axis for axis in range(3) if plus[axis])
            half /= 2
            centre = centre + np.where(plus, half, -half)

    def test_the_root_holds_the_galaxy(self):
        assert np.abs(render.ROOT_CENTRE).max() + 50_000 < render.HALF_SIZE


class TestRenderScratch:
    """The scratch files between the steps of the render build."""

    def test_batch_files_hold_no_octree_key(self, tmp_path, out, monkeypatch):
        built = write_registry(tmp_path / "reg", random_stars(60, seed=14))
        members: set[str] = set()
        real = render.build_batch

        def build_batch(job):
            batch = render.batch_file(job.scratch, job.batch, 0).parent
            for path in batch.glob("*.npz"):
                with np.load(path) as part:
                    members.update(part.files)
            return real(job)

        monkeypatch.setattr(render, "build_batch", build_batch)
        export_extrasolar(built.root, out, workers=1)
        assert "id" in members and "node" in members
        assert "key" not in members

    def test_build_batch_closes_its_pieces(self, tmp_path, monkeypatch):
        scratch = tmp_path / "scratch"
        regions = 40
        for region in range(regions):
            for name, dtype in render.ROW_ARRAYS.items():
                path = render.scratch_file(scratch, region, name)
                path.parent.mkdir(parents=True, exist_ok=True)
                np.save(path, np.full(1, region + 1, dtype))
            np.save(render.scratch_file(scratch, region, "node"), np.zeros(1, np.int32))
            render.split_region(render.SplitJob(scratch, region, (0, 1)))
        open_files = []
        real = render.node_payloads

        def node_payloads(node, rows):
            open_files.append(len(os.listdir("/proc/self/fd")))
            return real(node, rows)

        monkeypatch.setattr(render, "node_payloads", node_payloads)
        node = render.Node("r", 0, (0.0, 0.0, 0.0), render.HALF_SIZE, rows=regions)
        before = len(os.listdir("/proc/self/fd"))
        render.build_batch(render.BatchJob(scratch, 0, tmp_path / "out", 0, (node,)))
        assert open_files and max(open_files) <= before
