"""Tests for the pass over the tree, the duplicates, the export and the gates."""

import hashlib
import json
import logging.config
from contextlib import contextmanager

import numpy as np
import pyarrow as pa
import pytest

from space_map_data.dust import gates as dust_gates
from space_map_data.export import glow as glow_export
from space_map_data.export import swap
from space_map_data.export.extrasolar import container
from space_map_data.export.extrasolar.render import NODE_INFO
from space_map_data.extrasolar.placement import GAIA_ASTROMETRY
from space_map_data.galaxy.credits import PAPERS
from space_map_data.glow import build, deposit, duplicates, form, gates, sky_map, tree
from space_map_data.glow.grid import SkyGrid

GRID = SkyGrid(8, 6, 20.0, 400_000.0)
ROWS = 40


def _write_node(directory, name: str, seed: int) -> None:
    rng = np.random.default_rng(seed)
    columns = [
        container.Column(axis, "float32", _floats(rng.normal(0, 300, ROWS)))
        for axis in "xyz"
    ]
    columns.append(
        container.Column("mag", "float32", _floats(rng.uniform(-2, 9, ROWS)))
    )
    columns.append(
        container.Column("colour", "float32", _floats(rng.uniform(0, 3, ROWS)))
    )
    info = NODE_INFO.pack(1.0, 2.0, 3.0, 1000.0, 1.0, 2.0, *[0.0] * 8, 1, 0)
    payload = container.encode(container.KIND_NODE, ROWS, columns, info)
    (directory / f"{name}.bin.gz").write_bytes(container.gzip_payload(payload))


def _floats(values: np.ndarray):
    import pyarrow as pa

    return pa.array(values.astype(np.float32))


@pytest.fixture
def stars(tmp_path, monkeypatch):
    for seed, name in enumerate(("r", "r0", "r1")):
        _write_node(tmp_path, name, seed)
    monkeypatch.setattr(tree, "NODE_DIR", tmp_path)
    monkeypatch.setattr(tree.read_node, "__defaults__", (tmp_path,))
    monkeypatch.setattr(tree.node_names, "__defaults__", (tmp_path,))
    return tmp_path


def _pass(workers: int, skip=None) -> deposit.Deposit:
    sky = np.full((25, 256, 256), 0.3, np.float32)
    sky[0] = 0.0
    return deposit.deposit([GRID], np.array(form.EDGES), sky, np.eye(3), workers, skip)


class TestDeposit:
    def test_the_grid_holds_all_the_light_of_the_stars(self, stars):
        result = _pass(2)
        assert result.totals.rows == 3 * ROWS
        assert result.cubes[0].sum(axis=(0, 1, 2, 3)) == pytest.approx(
            result.totals.light
        )

    def test_the_curve_holds_the_same_light(self, stars):
        result = _pass(2)
        assert result.curve.sum(axis=0) == pytest.approx(result.totals.light)

    def test_the_sums_do_not_depend_on_the_workers(self, stars):
        assert np.array_equal(_pass(1).cubes[0], _pass(3).cubes[0])

    def test_a_row_on_the_list_is_left_out(self, stars):
        result = _pass(2, {"r0": np.array([0, 5])})
        assert result.totals.rows == 3 * ROWS - 2

    def test_a_bright_star_stays_in_the_sample_at_weight_one(self, stars):
        sample = _pass(2).sample
        bright = sample[:, 3] - 0.825 * sample[:, 5] < deposit.SAMPLE_BRIGHT
        assert (sample[bright, 6] == 1).all()

    def test_the_pass_lets_go_of_what_the_workers_read(self, stars, monkeypatch):
        def broken(*_args):
            raise OSError("worker died")
            yield

        _pass(1)
        assert deposit._sky is None and deposit._grids == []
        monkeypatch.setattr(deposit, "forked_stream", broken)
        with pytest.raises(OSError):
            _pass(1)
        assert deposit._sky is None and deposit._skip == {}


class TestDuplicates:
    def _vectors(self, offset_arcsec: float) -> tuple[np.ndarray, np.ndarray]:
        a = np.array([[1.0, 0.0, 0.0]])
        angle = np.radians(offset_arcsec / 3600)
        return a, np.array([[np.cos(angle), np.sin(angle), 0.0]])

    def test_a_row_on_a_gaia_row_of_the_same_magnitude_repeats_it(self):
        a, b = self._vectors(0.5)
        assert duplicates.repeated_rows(a, np.array([6.0]), b, np.array([6.3]))[0]

    def test_a_close_pair_of_other_magnitudes_is_two_stars(self):
        a, b = self._vectors(0.5)
        assert not duplicates.repeated_rows(a, np.array([6.0]), b, np.array([9.0]))[0]

    def test_a_star_further_off_is_another_star(self):
        a, b = self._vectors(5.0)
        assert not duplicates.repeated_rows(a, np.array([6.0]), b, np.array([6.0]))[0]

    def test_the_rows_without_gaia_astrometry_come_from_the_registry_it_holds(
        self, monkeypatch
    ):
        asked = []

        class Held:
            def read_table(self, slug, region, columns):
                asked.append((slug, region, columns))
                return pa.table(
                    {
                        "id": [1, 2, 3],
                        "astrometry_source": [*GAIA_ASTROMETRY, "hipparcos"],
                    }
                )

        monkeypatch.setattr(duplicates, "_registry", Held())
        assert duplicates._other_ids(7).tolist() == [3]
        assert asked == [("point-source", 7, ["id", "astrometry_source"])]


class TestGates:
    def test_a_weighted_quantile_follows_the_weights(self):
        values = np.array([1.0, 2.0, 3.0])
        assert gates.weighted_quantile(values, np.array([1.0, 1.0, 100.0]), 0.5) == 3.0

    def test_each_pixel_has_a_ray(self):
        rays, lat = dust_gates.rays(2)
        assert len(rays) == 192 == len(lat)
        assert np.linalg.norm(rays, axis=1) == pytest.approx(np.ones(192))


def _small_build(directory, token_shift: int = 0) -> None:
    grids = {
        "high": SkyGrid(8, 6, 20.0, 400_000.0),
        "low": SkyGrid(4, 6, 20.0, 400_000.0),
    }
    histogram = np.zeros((len(form.curve_points()) - 1, 3))
    histogram[form.curve_bin(np.array([0.5, 2.0]))] = 1.0
    np.save(directory / build.CURVE, histogram)
    (directory / build.TOTALS).write_text(
        json.dumps(
            {
                "rows": 2,
                "light": [1.0, 1.0, 1.0],
                "observed": [1.0, 1.0, 1.0],
                "capped_rows": 0,
                "capped_light": [0.0, 0.0, 0.0],
                "no_colour_rows": 0,
                "tree": "tree",
                "nest": "nest",
            }
        )
    )
    for tier, grid in grids.items():
        values = np.full((*grid.shape, form.VALUES), 1.0 + token_shift, np.float32)
        np.save(directory / build.values_name(tier), values)


def _root(path, tree_token: str = "tree", nest_token: str = "nest"):
    """An export root with the metadata of a served tree and nest."""
    (path / "v1" / "x").mkdir(parents=True)
    (path / "v1" / "dust").mkdir(parents=True)
    (path / "v1" / "x" / "metadata.json").write_text(
        json.dumps(
            {
                "credits": [{"name": "stars"}],
                "registry": {"ingest": 4},
                "trees": {
                    "mw": {"distribution": "non-commercial", "token": tree_token}
                },
            }
        )
    )
    (path / "v1" / "dust" / "metadata.json").write_text(
        json.dumps(
            {
                "credits": [{"name": "dust"}],
                "distribution": "non-commercial",
                "token": nest_token,
            }
        )
    )
    return path


@pytest.fixture
def small(tmp_path, monkeypatch):
    grids = {
        "high": SkyGrid(8, 6, 20.0, 400_000.0),
        "low": SkyGrid(4, 6, 20.0, 400_000.0),
    }
    monkeypatch.setattr(build, "GRIDS", grids)
    # No model build: the grid goes alone, and the real model build stays unread.
    monkeypatch.setattr(
        glow_export.export_glow,
        "__defaults__",
        (build.BUILD_DIR, tmp_path / "no-model"),
    )
    directory = tmp_path / "build"
    directory.mkdir()
    _small_build(directory)
    build.build_encoded(directory)
    return directory


def _hashes(root) -> dict[str, str]:
    live = root / "v1" / "glow"
    return {
        str(path.relative_to(live)): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted(live.rglob("*"))
        if path.is_file()
    }


class TestExport:
    def test_a_file_has_the_kind_and_the_token_of_the_export(self, small, tmp_path):
        root = _root(tmp_path / "out")
        metadata = glow_export.export_glow(root, small)
        file = root / "v1" / "glow" / metadata["tiers"]["high"]["files"]["a"]["path"]
        read = container.read(file)
        assert read.kind == container.KIND_VOLUME
        assert read.token == metadata["token"]

    def test_a_texture_comes_back_in_upload_order(self, small, tmp_path):
        root = _root(tmp_path / "out")
        metadata = glow_export.export_glow(root, small)
        file = root / "v1" / "glow" / metadata["tiers"]["high"]["files"]["b"]["path"]
        read = container.read(file)
        width, height, shells, texture, tier = container.VOLUME_INFO.unpack(read.info)
        assert (width, height, shells, texture, tier) == (8, 8, 6, 1, 0)
        bits = read.numpy("texels").reshape(shells, height, width, 4)
        stored = np.load(small / build.bits_name("high"))
        assert np.array_equal(bits, stored[..., 4:8])

    def test_a_rerun_writes_the_same_bytes(self, small, tmp_path):
        glow_export.export_glow(_root(tmp_path / "one"), small)
        glow_export.export_glow(_root(tmp_path / "two"), small)
        assert _hashes(tmp_path / "one") == _hashes(tmp_path / "two")

    def test_the_tier_comes_from_the_tree_and_the_nest(self, small, tmp_path):
        metadata = glow_export.export_glow(_root(tmp_path / "out"), small)
        assert metadata["distribution"] == "non-commercial"
        # Their credits stay in their own metadata.
        assert metadata["credits"] == []

    def test_an_undecided_tier_is_refused_at_the_served_root(
        self, small, tmp_path, monkeypatch
    ):
        root = _root(tmp_path / "out")
        tree = root / "v1" / "x" / "metadata.json"
        metadata = json.loads(tree.read_text())
        # Off the ladder, so undecided.
        metadata["trees"]["mw"]["distribution"] = "unknown"
        tree.write_text(json.dumps(metadata))
        monkeypatch.setattr(glow_export, "EXTRASOLAR_DIR", root)
        with pytest.raises(swap.ExportRefused, match="undecided"):
            glow_export.export_glow(root, small)
        assert sorted(p.name for p in (root / "v1").iterdir()) == ["dust", "x"]
        monkeypatch.setattr(glow_export, "EXTRASOLAR_DIR", tmp_path / "served")
        assert glow_export.export_glow(root, small)["distribution"] == "undecided"

    def test_sizes_come_from_the_encoding_and_not_the_grids(
        self, small, tmp_path, monkeypatch
    ):
        monkeypatch.setattr(build, "GRIDS", {"high": SkyGrid(16, 3, 1.0, 10.0)})
        metadata = glow_export.export_glow(_root(tmp_path / "out"), small)
        high = metadata["tiers"]["high"]
        assert (high["size"], high["shells"], high["scale_pc"]) == (8, 6, 20.0)
        assert high["mebibytes"] == 8 * 8 * 6 * 16 / 2**20
        assert set(metadata["tiers"]) == {"high", "low"}

    def test_the_law_of_the_dust_is_in_the_metadata(self, small, tmp_path):
        metadata = glow_export.export_glow(_root(tmp_path / "out"), small)
        assert metadata["extinction"]["brightest_m0"] == -10.0
        assert metadata["extinction"]["k_g"] == 0.825

    def test_a_stopped_swap_is_put_back(self, small, tmp_path):
        root = _root(tmp_path / "out")
        glow_export.export_glow(root, small)
        live = root / "v1" / "glow"
        live.rename(root / "v1" / ".glow-old")
        glow_export.export_glow(root, small)
        assert live.exists() and not (root / "v1" / ".glow-old").exists()

    def test_an_export_refuses_while_another_holds_the_tree(self, small, tmp_path):
        root = _root(tmp_path / "out")
        with swap.locked(root), pytest.raises(swap.ExportRefused):
            glow_export.export_glow(root, small)

    def test_it_refuses_textures_the_encoding_does_not_list(self, small, tmp_path):
        np.save(small / build.bits_name("high"), np.zeros(3))
        with pytest.raises(build.StaleBuild):
            glow_export.export_glow(_root(tmp_path / "out"), small)

    def test_it_refuses_a_grid_of_another_tree_below_its_own_root(
        self, small, tmp_path
    ):
        # Only the root it is given counts, not the served export.
        glow_export.export_glow(_root(tmp_path / "same"), small)
        with pytest.raises(build.StaleBuild, match="tree"):
            glow_export.export_glow(
                _root(tmp_path / "other", tree_token="another"), small
            )

    def test_it_refuses_a_grid_of_another_nest(self, small, tmp_path):
        with pytest.raises(build.StaleBuild, match="nest"):
            glow_export.export_glow(
                _root(tmp_path / "out", nest_token="another"), small
            )

    def test_the_tokens_are_read_without_the_volumes_of_the_nest(
        self, small, tmp_path, monkeypatch
    ):
        def refuse(*_args, **_kwargs):
            raise AssertionError("read the volumes of the nest")

        monkeypatch.setattr(sky_map, "load_nest", refuse)
        glow_export.export_glow(_root(tmp_path / "out"), small)


class _Held:
    """A stand-in for `served` that logs when the export is held and let go."""

    def __init__(self, events: list[str]) -> None:
        self.events = events

    @contextmanager
    def __call__(self, _root):
        self.events.append("held")
        try:
            yield
        finally:
            self.events.append("let go")


class TestBuildSteps:
    def test_a_deposit_holds_the_export_and_takes_the_token_first(
        self, tmp_path, monkeypatch
    ):
        events: list[str] = []
        monkeypatch.setattr(build, "served", _Held(events))

        def token():
            events.append("token")
            return "tree"

        class Stop(Exception):
            pass

        def stop(*_args):
            events.append("pass")
            raise Stop

        monkeypatch.setattr(build, "tree_token", token)
        monkeypatch.setattr(
            sky_map,
            "nest_metadata",
            lambda: {
                "token": "nest",
                "frame": {"rotation_to_icrs": np.eye(3).tolist()},
            },
        )
        monkeypatch.setattr(build, "read_skip", lambda _build, _token: {})
        monkeypatch.setattr(deposit, "deposit", stop)
        (tmp_path / "sun_map.json").write_text(json.dumps({"nest": "nest"}))
        np.save(tmp_path / build.SUN_MAP, np.zeros(1))
        with pytest.raises(Stop):
            build.build_deposit(tmp_path, 1)
        assert events == ["held", "token", "pass", "let go"]

    def test_a_deposit_refuses_a_sun_map_of_another_nest(self, tmp_path, monkeypatch):
        monkeypatch.setattr(build, "served", _Held([]))
        monkeypatch.setattr(build, "tree_token", lambda: "tree")
        monkeypatch.setattr(sky_map, "nest_metadata", lambda: {"token": "new"})
        (tmp_path / "sun_map.json").write_text(json.dumps({"nest": "old"}))
        with pytest.raises(build.StaleBuild, match="sun-map"):
            build.build_deposit(tmp_path, 1)

    def test_a_list_of_duplicates_of_another_tree_is_refused(self, tmp_path):
        np.savez(tmp_path / build.DUPLICATES, node=np.array(["r"]), row=np.array([3]))
        (tmp_path / "duplicates.json").write_text(json.dumps({"tree": "old"}))
        with pytest.raises(build.StaleBuild, match="duplicates"):
            build.read_skip(tmp_path, "new")
        assert build.read_skip(tmp_path, "old")["r"].tolist() == [3]

    def _registry(self, monkeypatch, tree_ingest: int, registry_ingest: int):
        class Reader:
            last_ingest = registry_ingest

        class FakeRegistry:
            @contextmanager
            def reader(self):
                yield Reader()

        found = []
        monkeypatch.setattr(build, "served", _Held([]))
        monkeypatch.setattr(build, "Registry", FakeRegistry)
        monkeypatch.setattr(
            build,
            "tree_metadata",
            lambda: {
                "registry": {"ingest": tree_ingest},
                "trees": {"mw": {"token": "tree"}},
            },
        )
        monkeypatch.setattr(
            duplicates,
            "find_duplicates",
            lambda registry, workers: (
                found.append(registry.last_ingest)
                or (np.array(["r"]), np.array([1]), {"repeated": 1})
            ),
        )
        return found

    def test_duplicates_refuse_a_registry_of_another_ingest(
        self, tmp_path, monkeypatch
    ):
        found = self._registry(monkeypatch, tree_ingest=4, registry_ingest=5)
        with pytest.raises(build.StaleBuild, match="ingest"):
            build.build_duplicates(tmp_path, 1)
        assert found == []

    def test_duplicates_are_found_in_the_registry_the_tree_came_from(
        self, tmp_path, monkeypatch
    ):
        found = self._registry(monkeypatch, tree_ingest=4, registry_ingest=4)
        build.build_duplicates(tmp_path, 1)
        assert found == [4]
        report = json.loads((tmp_path / "duplicates.json").read_text())
        assert (report["tree"], report["ingest"]) == ("tree", 4)


def _model_build(directory, glow_dir) -> None:
    """A model build of tiny boxes that belongs to the grid in `glow_dir`."""
    from space_map_data.dust.encode import file_digest
    from space_map_data.extrasolar.store import write_json
    from space_map_data.galaxy import build as model_build

    directory.mkdir()
    digests, shapes = {}, {}
    rng = np.random.default_rng(5)
    for box in model_build.BOXES:
        for tier in model_build.CAT_TIERS:
            bits = rng.integers(0, 30000, (4, 3, 2)).astype(np.uint16)
            path = directory / model_build.bits_name(box, tier)
            np.save(path, bits)
            digests[path.name] = file_digest(path)
            shapes[path.name] = list(bits.shape)
    write_json(directory / model_build.TABLE_FILE, {"rgb": [[1 / 3] * 3]})
    write_json(
        directory / "calibration.json",
        {"flux": {"bulge": 1.0}, "bp_rp": {"bulge": 1.1}, "fit": {"lian_scale": 0.75}},
    )
    write_json(
        directory / model_build.ENCODING_FILE,
        {
            "scale": 1024.0,
            "digests": digests,
            "shapes": shapes,
            "centre_pc": [8277.0, 0.0, -20.8],
            "boxes": {
                "inner": {"half_extent_pc": [400.0, 300.0, 200.0], "z_scale_pc": 50.0},
                "outer": {"half_extent_pc": [900.0, 900.0, 900.0], "z_scale_pc": 0.0},
            },
            "glow": model_build.glow_inputs(glow_dir),
            "far_side": 1.0,
            "catalogue_fade_pc": [2000.0, 4000.0],
            "table": file_digest(directory / model_build.TABLE_FILE),
            "calibration": file_digest(directory / "calibration.json"),
        },
    )


class TestExportWithModel:
    def test_the_model_goes_with_the_grid_under_one_token(self, small, tmp_path):
        model = tmp_path / "model"
        _model_build(model, small)
        root = _root(tmp_path / "out")
        metadata = glow_export.export_glow(root, small, model)
        entry = metadata["model"]["tiers"]["high"]["inner"]
        payload = container.read(root / "v1" / "glow" / entry["path"])
        assert payload.kind == container.KIND_VOLUME
        assert payload.token == metadata["token"]
        bits = np.load(model / "bits.inner.high.npy")
        assert np.array_equal(
            payload.numpy("texels"), bits.transpose(2, 1, 0).reshape(-1)
        )
        assert metadata["model"]["catalogue_fade_pc"] == [2000.0, 4000.0]
        assert [c["key"] for c in metadata["credits"]] == list(PAPERS)

    def test_the_boxes_and_sizes_are_those_the_model_encoded(self, small, tmp_path):
        model = tmp_path / "model"
        _model_build(model, small)
        metadata = glow_export.export_glow(_root(tmp_path / "out"), small, model)
        block = metadata["model"]
        assert block["tiers"]["low"]["outer"]["size"] == [4, 3, 2]
        assert block["centre_pc"] == [8277.0, 0.0, -20.8]
        assert block["boxes"]["inner"] == {
            "half_extent_pc": [400.0, 300.0, 200.0],
            "z_map": "asinh",
            "z_scale_pc": 50.0,
        }
        assert block["boxes"]["outer"]["z_map"] == "linear"

    def test_a_model_on_a_changed_calibration_is_refused(self, small, tmp_path):
        model = tmp_path / "model"
        _model_build(model, small)
        (model / "calibration.json").write_text("{}")
        with pytest.raises(swap.ExportRefused, match="calibration"):
            glow_export.export_glow(_root(tmp_path / "out"), small, model)

    def test_a_model_of_another_grid_is_refused(self, small, tmp_path):
        model = tmp_path / "model"
        _model_build(model, small)
        raw = json.loads((model / "encoding.json").read_text())
        raw["glow"]["tree"] = "another"
        (model / "encoding.json").write_text(json.dumps(raw))
        with pytest.raises(swap.ExportRefused):
            glow_export.export_glow(_root(tmp_path / "out"), small, model)


class TestExportCommand:
    """`space-map-export --only glow` reads the builds it is given, and ends on a
    stale input with the refusal's message."""

    def run(self, monkeypatch, build_dir, root, *flags: str) -> None:
        from space_map_data.export import __main__ as export_main

        monkeypatch.setattr(export_main, "limit_arenas", lambda count: None)
        monkeypatch.setattr(logging.config, "dictConfig", lambda config: None)
        argv = ["space-map-export", "--only", "glow", "--extrasolar-root", str(root)]
        flags = ("--glow-build", str(build_dir), *flags)
        monkeypatch.setattr("sys.argv", [*argv, *flags])
        export_main.cli()

    def test_the_grid_comes_from_the_named_build(self, small, tmp_path, monkeypatch):
        self.run(
            monkeypatch,
            small,
            _root(tmp_path / "out"),
            "--model-build",
            str(tmp_path / "no-model"),
        )
        assert (tmp_path / "out" / "v1" / "glow" / "metadata.json").exists()

    def test_a_stale_grid_is_refused(self, small, tmp_path, monkeypatch):
        np.save(small / build.bits_name("high"), np.zeros(3))
        model = str(tmp_path / "no-model")
        with pytest.raises(SystemExit, match="export refused: .*is not the file of"):
            self.run(
                monkeypatch, small, _root(tmp_path / "out"), "--model-build", model
            )
        assert not (tmp_path / "out" / "v1" / "glow").exists()

    def test_a_stale_model_is_refused(self, small, tmp_path, monkeypatch):
        model = tmp_path / "model"
        _model_build(model, small)
        (model / "calibration.json").write_text("{}")
        with pytest.raises(SystemExit, match="export refused: .*calibration"):
            self.run(
                monkeypatch, small, _root(tmp_path / "out"), "--model-build", str(model)
            )
        assert not (tmp_path / "out" / "v1" / "glow").exists()
