"""Tests for the files of the dust nest: encodings, copies, workers and the export."""

import json
import logging.config
import os
import signal
from concurrent.futures.process import BrokenProcessPool

import numpy as np
import pytest
from astropy.io import fits

from space_map_data.dust import encode, far, gates, sources
from space_map_data.dust.encode import (
    Encoding,
    FarRecord,
    Recorded,
    StaleCodes,
    read_encodings,
    read_recorded,
)
from space_map_data.dust.nest import Level
from space_map_data.dust.parallel import forked_map, forked_stream
from space_map_data.dust.rest import FIELD_FILE
from space_map_data.export import dust as dust_export
from space_map_data.export import swap
from space_map_data.export.extrasolar import build, container
from space_map_data.galaxy.volumes import Box

SMALL = Level(0, (10.0, 10.0, 5.0), (4, 4, 2))
SMALL_FAR = {"high": Box((24000.0, 24000.0, 3000.0), (4, 4, 2), 150.0)}
SMALL_FAR["low"] = SMALL_FAR["high"].halved()


def _field(base: float) -> np.ndarray:
    """A rest field with one base, no near factor and a window of 1 kpc."""
    n = 12 * 4**7
    return np.stack(
        (np.full(n, base), np.ones(n), np.zeros(n), np.full(n, 1000.0))
    ).astype("f4")


def _square(x: int) -> int:
    return x * x


def _die(_x: int) -> None:
    os.kill(os.getpid(), signal.SIGKILL)


class TestForkedWorkers:
    def test_results_come_in_job_order(self):
        assert forked_map(_square, range(10), 3) == [x * x for x in range(10)]

    def test_a_stream_gives_the_same_results_one_at_a_time(self):
        stream = forked_stream(_square, range(10), 3)
        assert next(stream) == 0
        assert list(stream) == [x * x for x in range(1, 10)]

    def test_a_killed_worker_raises_and_does_not_hang(self):
        with pytest.raises(BrokenProcessPool):
            forked_map(_die, range(4), 2)

    def test_workers_inherit_the_globals_of_the_parent(self, monkeypatch):
        monkeypatch.setattr(
            gates, "_shared", (lambda shared, chunk, start: shared, 7, np.zeros(3))
        )
        assert forked_map(gates._chunk, [0, 0], 2) == [7, 7]


class TestRayJitter:
    def test_each_chunk_has_its_own_jitter_and_a_tier_pair_shares_it(self, monkeypatch):
        seen = []

        def spy(stack, origin, directions, growth, first, per_step, jitter):
            seen.append(jitter)
            return np.zeros(len(directions))

        monkeypatch.setattr(gates, "march", spy)
        directions = np.zeros((5, 3))
        shared = (None, np.zeros(3), 0.1, 10.0, None, 3)
        gates._marched(shared, directions, 0)
        gates._marched(shared, directions, gates.RAY_CHUNK)
        gates._marched(shared, directions, 0)
        assert not np.array_equal(seen[0], seen[1])
        assert np.array_equal(seen[0], seen[2])

    def test_no_seed_means_no_jitter(self, monkeypatch):
        seen = []
        monkeypatch.setattr(
            gates, "march", lambda *args: seen.append(args[-1]) or np.zeros(2)
        )
        gates._marched((None, np.zeros(3), 0.1, 10.0, None, None), np.zeros((2, 3)), 0)
        assert seen == [None]


class TestEncodingDigests:
    @pytest.fixture
    def built(self, tmp_path, monkeypatch):
        merged, encoded = tmp_path / "merged", tmp_path / "encoded"
        merged.mkdir()
        encoded.mkdir()
        monkeypatch.setattr(encode, "LEVELS", (SMALL, Level(1, SMALL.half, (4, 4, 2))))
        monkeypatch.setattr(encode, "merged_dir", lambda _variant: merged)
        monkeypatch.setattr(far, "merged_dir", lambda _variant: merged)
        monkeypatch.setattr(far, "FAR_TIERS", SMALL_FAR)
        np.save(merged / FIELD_FILE, _field(1e-3))
        far.build_far("open", 1)
        monkeypatch.setattr(encode, "encoded_dir", lambda _variant: encoded)
        monkeypatch.setattr(encode, "CALIBRATION_FILE", tmp_path / "calibration.json")
        encode.CALIBRATION_FILE.write_text(json.dumps({"gains": {"bayestar": 3.0}}))
        (merged / "rest_share.json").write_text(json.dumps({"0": 0.5}))
        (merged / "rest.json").write_text(json.dumps({"unplaced_share": 0.25}))
        rng = np.random.default_rng(1)
        for index in (0, 1):
            density = (1e-3 * rng.random(SMALL.shape)).astype("f4")
            np.save(merged / f"l{index}.density.npy", density)
        floors = {0: 1e-6, 1: 1e-6}
        encode.build_encoded("open", floors, 1)
        return merged, encoded, floors

    def test_a_finished_build_reads_back(self, built):
        _, encoded, _ = built
        encodings = read_encodings("open")
        assert set(encodings) == {0, 1}
        assert (encoded / "l0.high.npy").exists()

    def test_the_far_volume_is_encoded_and_recorded(self, built):
        merged, encoded, _ = built
        record = read_recorded("open").far
        density = np.load(merged / far.DENSITY_FILE)
        assert record.encoding == Encoding(far.FLOOR, float(density.max()))
        assert record.half == (24000.0, 24000.0, 3000.0)
        assert record.z_scale == 150.0
        assert read_recorded("open").shapes["far.low.npy"] == (2, 2, 1)
        assert np.load(encoded / "far.high.npy").dtype == np.uint8

    def test_a_far_volume_of_another_rest_field_is_refused(self, built):
        merged, _, floors = built
        np.save(merged / FIELD_FILE, _field(2e-3))
        with pytest.raises(far.StaleFar):
            encode.build_encoded("open", floors, 1)

    def test_the_figures_of_the_build_are_recorded(self, built):
        recorded = read_recorded("open")
        assert recorded.gains == {"bayestar": 3.0}
        assert recorded.rest_share == {"0": 0.5}
        assert recorded.unplaced_share == 0.25

    def test_the_extents_and_shapes_are_those_encoded(self, built):
        recorded = read_recorded("open")
        assert recorded.half_extents == {0: SMALL.half, 1: SMALL.half}
        assert recorded.shapes["l1.high.npy"] == (4, 4, 2)
        assert recorded.shapes["l1.low.npy"] == (2, 2, 1)

    def test_a_later_change_of_those_files_does_not_reach_the_record(self, built):
        merged, _, _ = built
        (merged / "rest.json").write_text(json.dumps({"unplaced_share": 0.9}))
        assert read_recorded("open").unplaced_share == 0.25

    def test_codes_from_another_run_are_refused(self, built):
        merged, _, _ = built
        stale = Encoding(1e-6, 99.0)
        # A run that stopped after the first codes file: new codes, old digests.
        np.save(merged / "l0.density.npy", np.full(SMALL.shape, 1e-2, "f4"))
        encode._encode_job(("open", 0, "high", stale))
        with pytest.raises(StaleCodes, match="run encode again") as refused:
            read_encodings("open")
        # The export ends on it as on any refusal.
        assert isinstance(refused.value, swap.ExportRefused)

    def test_a_run_that_finishes_is_read_again(self, built):
        merged, _, floors = built
        np.save(merged / "l0.density.npy", np.full(SMALL.shape, 1e-2, "f4"))
        encode.build_encoded("open", floors, 1)
        assert read_encodings("open")[0].top == pytest.approx(1e-2)

    def test_encoding_json_is_never_half_written(self, built, monkeypatch):
        _, encoded, floors = built
        before = (encoded / "encoding.json").read_bytes()

        def broken(path, data):
            raise OSError("disk full")

        monkeypatch.setattr(encode, "write_json", broken)
        with pytest.raises(OSError):
            encode.build_encoded("open", floors, 1)
        assert (encoded / "encoding.json").read_bytes() == before


class TestEdenhoferCopy:
    @pytest.fixture
    def eden(self, tmp_path, monkeypatch):
        source_root = tmp_path / "maps"
        (source_root / "edenhofer-2024").mkdir(parents=True)
        monkeypatch.setattr(sources, "SOURCES_DUST_MAPS_DIR", source_root)
        monkeypatch.setattr(sources, "SOURCE_DIR", tmp_path / "copies")
        return source_root / "edenhofer-2024" / "map.fits"

    @staticmethod
    def _write_map(path, scale=1.0):
        edges = fits.BinTableHDU.from_columns(
            [
                fits.Column(
                    name="radial pixel boundaries",
                    format="D",
                    array=np.array([0.0, 1.0, 2.0]),
                )
            ],
            name="RADIAL PIXEL BOUNDARIES",
        )
        fits.HDUList(
            [
                fits.PrimaryHDU(),
                fits.ImageHDU(np.full((2, 3), scale, "f4"), name="MEAN"),
                edges,
                fits.ImageHDU(np.full(3, scale, "f4"), name="MEAN OF INTEGRATED INNER"),
            ]
        ).writeto(path, overwrite=True)

    def test_a_copy_holds_the_mean_the_edges_and_the_inner_column(self, eden):
        self._write_map(eden)
        sources._edenhofer_copy("map.fits", "e")
        copies = sources.SOURCE_DIR
        assert np.load(copies / "e.mean.npy").tolist() == [[sources.K550] * 3] * 2
        assert np.load(copies / "e.edges.npy").tolist() == [0.0, 1.0, 2.0]
        assert np.allclose(np.load(copies / "e.inner.npy"), sources.K550)

    def test_a_finished_copy_is_not_made_again(self, eden):
        self._write_map(eden)
        sources._edenhofer_copy("map.fits", "e")
        mean = sources.SOURCE_DIR / "e.mean.npy"
        mean.write_bytes(b"marker")
        sources._edenhofer_copy("map.fits", "e")
        assert mean.read_bytes() == b"marker"

    def test_a_mean_without_the_marker_is_made_again(self, eden):
        self._write_map(eden)
        sources._edenhofer_copy("map.fits", "e")
        (sources.SOURCE_DIR / "e.copy.json").unlink()
        (sources.SOURCE_DIR / "e.inner.npy").unlink()
        sources._edenhofer_copy("map.fits", "e")
        assert (sources.SOURCE_DIR / "e.inner.npy").exists()

    def test_a_changed_source_is_copied_again(self, eden):
        self._write_map(eden)
        sources._edenhofer_copy("map.fits", "e")
        self._write_map(eden, scale=2.0)
        sources._edenhofer_copy("map.fits", "e")
        mean = np.load(sources.SOURCE_DIR / "e.mean.npy")
        assert mean[0, 0] == pytest.approx(2.0 * sources.K550)

    def test_a_changed_scale_is_copied_again(self, eden, monkeypatch):
        self._write_map(eden)
        sources._edenhofer_copy("map.fits", "e")
        monkeypatch.setattr(sources, "K550", 2.0)
        sources._edenhofer_copy("map.fits", "e")
        assert np.load(sources.SOURCE_DIR / "e.mean.npy")[0, 0] == pytest.approx(2.0)


class TestSwap:
    def _tree(self, path, text):
        path.mkdir(parents=True)
        (path / "file").write_text(text)

    def test_a_stopped_swap_gives_the_old_tree_back(self, tmp_path):
        self._tree(tmp_path / "old", "served")
        self._tree(tmp_path / "staging", "half")
        swap.recover(tmp_path / "live", tmp_path / "old", (tmp_path / "staging",))
        assert (tmp_path / "live" / "file").read_text() == "served"
        assert not (tmp_path / "old").exists()
        assert not (tmp_path / "staging").exists()

    def test_a_finished_swap_drops_the_old_tree(self, tmp_path):
        self._tree(tmp_path / "live", "new")
        self._tree(tmp_path / "old", "replaced")
        swap.recover(tmp_path / "live", tmp_path / "old")
        assert (tmp_path / "live" / "file").read_text() == "new"
        assert not (tmp_path / "old").exists()

    def test_a_failed_rename_keeps_the_served_tree(self, tmp_path, monkeypatch):
        self._tree(tmp_path / "live", "served")
        self._tree(tmp_path / "staging", "new")
        real = type(tmp_path).rename

        def rename(self, target):
            if self.name == "staging":
                raise OSError("rename failed")
            return real(self, target)

        monkeypatch.setattr(type(tmp_path), "rename", rename)
        with pytest.raises(OSError, match="rename failed"):
            swap.swap(tmp_path / "live", tmp_path / "staging", tmp_path / "old")
        assert (tmp_path / "live" / "file").read_text() == "served"
        assert not (tmp_path / "old").exists()


def _recorded() -> Recorded:
    """The record of one small level, a small far volume and one tier."""
    return Recorded(
        {0: Encoding(1e-6, 1.0)},
        {0: SMALL.half},
        {"l0.high.npy": SMALL.shape, "far.high.npy": (4, 4, 2)},
        {},
        {},
        0.0,
        FarRecord(Encoding(1e-6, 1e-3), (8277.0, 0.0, -21.0), (24e3, 24e3, 3e3), 150.0),
    )


class TestDustExport:
    """`export_dust` on one small level and one tier."""

    @pytest.fixture
    def export(self, tmp_path, monkeypatch):
        encoded = tmp_path / "encoded"
        encoded.mkdir()
        np.save(encoded / "l0.high.npy", np.zeros((4, 4, 2), np.uint8))
        np.save(encoded / "far.high.npy", np.zeros((4, 4, 2), np.uint8))
        monkeypatch.setattr(dust_export, "TIERS", ("high",))
        monkeypatch.setattr(dust_export, "encoded_dir", lambda _variant: encoded)
        monkeypatch.setattr(dust_export, "_distribution", lambda _variant: "open")
        monkeypatch.setattr(dust_export, "read_recorded", lambda _variant: _recorded())
        monkeypatch.setattr(
            dust_export,
            "_metadata",
            lambda variant, files, token, recorded, distribution: {
                "token": token,
                "distribution": distribution,
            },
        )
        root = tmp_path / "root"
        return root, encoded

    def _tree(self, root):
        return sorted(p.relative_to(root).as_posix() for p in root.rglob("*"))

    def test_the_metadata_takes_extents_and_sizes_from_the_record(self, monkeypatch):
        monkeypatch.setattr(dust_export, "TIERS", ("high",))
        keys = {key for _, _, used in dust_export.LAYERS["open"] for key in used}
        terms = {key: {"distribution": "open"} for key in keys}
        monkeypatch.setattr(dust_export, "_sources", lambda _variant: ([], terms))
        written = container.Written("high/l0.bin.gz", b"", 32, 10)
        far_written = container.Written("high/far.bin.gz", b"", 32, 7)
        metadata = dust_export._metadata(
            "open",
            {(0, "high"): written, (far.FAR_INDEX, "high"): far_written},
            "token",
            _recorded(),
            "open",
        )
        assert metadata["far"] == {
            "centre_pc": [8277.0, 0.0, -21.0],
            "half_extent_pc": [24e3, 24e3, 3e3],
            "z_map": "asinh",
            "z_scale_pc": 150.0,
            "floor": 1e-6,
            "top": 1e-3,
            "read": "where level 0 does not hold the point",
            "high": {"path": "high/far.bin.gz", "size": [4, 4, 2], "bytes": 7},
        }
        assert metadata["levels"] == [
            {
                "level": 0,
                "half_extent_pc": [10.0, 10.0, 5.0],
                "floor": 1e-6,
                "top": 1.0,
                "high": {"path": "high/l0.bin.gz", "size": [4, 4, 2], "bytes": 10},
            }
        ]

    def test_the_export_replaces_the_served_nest(self, export):
        root, _ = export
        first = dust_export.export_dust("open", root)
        second = dust_export.export_dust("open", root)
        assert first["token"] == second["token"]
        assert self._tree(root) == [
            ".lock",
            "v1",
            "v1/dust",
            "v1/dust/high",
            "v1/dust/high/far.bin.gz",
            "v1/dust/high/l0.bin.gz",
            "v1/dust/metadata.json",
        ]

    def test_a_stopped_swap_does_not_destroy_the_served_nest(self, export, monkeypatch):
        root, _ = export
        dust_export.export_dust("open", root)
        (root / "v1" / "dust").rename(root / "v1" / ".dust-old")
        (root / "v1" / ".dust-staging").mkdir()

        def refuse(_variant):
            raise StaleCodes("stale")

        # The next run fails early. The served nest must come back first.
        monkeypatch.setattr(dust_export, "read_recorded", refuse)
        with pytest.raises(StaleCodes):
            dust_export.export_dust("open", root)
        assert (root / "v1" / "dust" / "metadata.json").exists()
        assert not (root / "v1" / ".dust-old").exists()

    def test_a_failed_swap_keeps_the_served_nest(self, export, monkeypatch):
        root, _ = export
        dust_export.export_dust("open", root)
        served = (root / "v1" / "dust" / "metadata.json").read_text()
        real = type(root).rename

        def rename(self, target):
            if self.name == ".dust-staging":
                raise OSError("rename failed")
            return real(self, target)

        monkeypatch.setattr(type(root), "rename", rename)
        with pytest.raises(OSError, match="rename failed"):
            dust_export.export_dust("open", root)
        assert (root / "v1" / "dust" / "metadata.json").read_text() == served
        assert sorted(p.name for p in (root / "v1").iterdir()) == ["dust"]

    def test_codes_that_do_not_match_their_encoding_write_nothing(
        self, export, monkeypatch
    ):
        root, _ = export

        def refuse(_variant):
            raise StaleCodes("stale")

        monkeypatch.setattr(dust_export, "read_recorded", refuse)
        with pytest.raises(StaleCodes):
            dust_export.export_dust("open", root)
        assert not (root / "v1").exists()


class TestExportLock:
    """The dust export and the extrasolar export share one lock on the tree."""

    @pytest.fixture
    def root(self, tmp_path, monkeypatch):
        monkeypatch.setattr(dust_export, "TIERS", ("high",))
        return tmp_path / "root"

    def test_a_dust_export_leaves_the_staging_of_a_running_export_alone(self, root):
        staging = root / "v1" / ".dust-staging"
        staging.mkdir(parents=True)
        (staging / "half").write_text("written by the first run")
        with (
            swap.locked(root),
            pytest.raises(swap.ExportRefused, match="another export"),
        ):
            dust_export.export_dust("open", root)
        assert (staging / "half").read_text() == "written by the first run"

    def test_an_extrasolar_export_refuses_while_a_dust_export_runs(
        self, root, monkeypatch
    ):
        refused = []

        def while_running(_variant):
            # The extrasolar export takes `Layout.lock` through `swap.locked`.
            assert build.Layout(root).lock == root / swap.LOCK_FILE
            with (
                pytest.raises(swap.ExportRefused, match="another export"),
                swap.locked(root),
            ):
                pass
            refused.append(True)
            raise encode.StaleCodes("stop here")

        monkeypatch.setattr(dust_export, "_distribution", lambda _variant: "open")
        monkeypatch.setattr(dust_export, "read_recorded", while_running)
        with pytest.raises(encode.StaleCodes):
            dust_export.export_dust("open", root)
        assert refused == [True]

    def test_the_lock_is_free_again_after_a_run(self, root, monkeypatch):
        def refuse(_variant):
            raise encode.StaleCodes("stale")

        monkeypatch.setattr(dust_export, "_distribution", lambda _variant: "open")
        monkeypatch.setattr(dust_export, "read_recorded", refuse)
        with pytest.raises(encode.StaleCodes):
            dust_export.export_dust("open", root)
        with swap.locked(root):
            pass


class TestExportCommand:
    def test_a_refusal_ends_the_command_with_its_message(self, tmp_path, monkeypatch):
        from space_map_data.export import __main__ as export_main

        root = tmp_path / "root"
        monkeypatch.setattr(dust_export, "_distribution", lambda _variant: "open")
        monkeypatch.setattr(export_main, "limit_arenas", lambda count: None)
        monkeypatch.setattr(logging.config, "dictConfig", lambda config: None)
        argv = ["space-map-export", "--only", "dust", "--extrasolar-root", str(root)]
        monkeypatch.setattr("sys.argv", argv)
        with swap.locked(root), pytest.raises(SystemExit) as stop:
            export_main.cli()
        assert stop.value.code == f"export refused: another export writes to {root}"
