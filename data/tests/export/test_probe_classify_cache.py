"""Probe classify: a cache hit skips the worker, a changed input misses."""

import math
import os
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from space_map_data.export.position.probes import classify, classify_cache
from space_map_data.export.position.probes.plan import ProbeMeta
from space_map_data.probes.probe_id import encode, index_by_source
from space_map_data.utils.time import year_to_jd

_PROBES = (("A", -1), ("A", -2), ("B", -3))


def _result(naif_id: int) -> dict:
    return {
        "status": "ok",
        "inception_et": 1.0e8 - naif_id,
        "intervals": [("interplanetary", 1.0e8, 1.1e8), ("mars", 1.05e8, 1.08e8)],
        "landed_phases": [(499, 1.08e8, 1.09e8)],
    }


class _Env:
    def __init__(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(classify_cache, "CLASSIFY_ROOT", tmp_path / "_classify")
        # Threads stand in for the process pool so the fake worker is seen.
        monkeypatch.setattr(classify, "ProcessPoolExecutor", ThreadPoolExecutor)
        monkeypatch.setattr(classify, "_classify_worker_init", lambda paths: None)
        monkeypatch.setattr(classify, "_classify_worker", self._worker)
        monkeypatch.setattr(classify, "enumerate_probes", lambda: list(self.probes))
        monkeypatch.setattr(classify, "load_traverses", dict)
        monkeypatch.setattr(classify, "flight_windows", dict)
        self.calls: list[tuple[str, int]] = []
        self.failing: set[int] = set()
        self.lsk = tmp_path / "naif.tls"
        self.lsk.write_bytes(b"lsk")
        self.probes: list[tuple[Path, list[Path], int]] = []
        for mission, naif_id in _PROBES:
            kernel = tmp_path / f"{mission}.bsp"
            kernel.write_bytes(mission.encode())
            self.probes.append((tmp_path / mission, [kernel], naif_id))
        self.registry: list[dict] = [
            {
                "probe_id": encode(60000, n),
                "naif_id": naif_id,
                "inception_mjd": 60000,
                "dedupe": n,
                "kernel_sources": [{"mission": mission, "naif_id": naif_id}],
            }
            for n, (mission, naif_id) in enumerate(_PROBES)
        ]
        self.metas = {
            e["probe_id"]: ProbeMeta(
                e["probe_id"], f"probe-{e['naif_id']}", 0, False, 0
            )
            for e in self.registry
        }

    def _worker(self, mission: str, kernel_paths: list[str], naif_id: int) -> dict:
        self.calls.append((mission, naif_id))
        if naif_id in self.failing:
            raise RuntimeError("worker failed")
        return _result(naif_id)

    def run(self) -> list:
        self.calls.clear()
        plans, _ = classify.classify_pass(
            self.registry,
            index_by_source(self.registry),
            self.metas,
            [self.lsk],
            [],
            year_to_jd(1950),
        )
        return plans


@pytest.fixture
def env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> _Env:
    return _Env(tmp_path, monkeypatch)


class TestClassifyPass:
    """Only probes with changed inputs go to the worker."""

    def test_second_run_is_all_hits_with_equal_plans(self, env: _Env) -> None:
        first = env.run()
        assert sorted(env.calls) == sorted(_PROBES)
        second = env.run()
        assert env.calls == []
        assert second == first
        assert len(first) == 3 and first[0].contributions

    def test_mission_kernel_change_misses_its_probes(self, env: _Env) -> None:
        env.run()
        env.probes[0][1][0].write_bytes(b"A, new version")
        env.run()
        assert sorted(env.calls) == [("A", -2), ("A", -1)]

    def test_init_kernel_change_misses_every_probe(self, env: _Env) -> None:
        env.run()
        env.lsk.write_bytes(b"lsk, new version")
        env.run()
        assert sorted(env.calls) == sorted(_PROBES)

    def test_mtime_change_hits(self, env: _Env) -> None:
        env.run()
        os.utime(env.probes[2][1][0], ns=(10**18, 10**18))
        env.run()
        assert env.calls == []

    def test_failed_worker_is_retried(self, env: _Env) -> None:
        env.failing = {-3}
        assert len(env.run()) == 2
        env.failing = set()
        assert len(env.run()) == 3
        assert env.calls == [("B", -3)]

    def test_gone_probe_is_pruned(self, env: _Env) -> None:
        env.run()
        root = classify_cache.CLASSIFY_ROOT
        (root / "notes.txt").write_bytes(b"not an entry")
        env.probes.pop()
        env.run()
        assert sorted(p.relative_to(root).as_posix() for p in root.rglob("*")) == [
            "A",
            "A/-1.json",
            "A/-2.json",
            "notes.txt",
        ]


class TestFlightWindow:
    """The curated end cuts cached and fresh results alike."""

    def test_flying_and_landed_coverage_stop_at_the_end(
        self, env: _Env, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        probe_id = env.registry[0]["probe_id"]
        window = (-math.inf, 1.085e8)
        monkeypatch.setattr(classify, "flight_windows", lambda: {probe_id: window})
        for plans in (env.run(), env.run()):
            plan = next(p for p in plans if p.probe_id == probe_id)
            assert max(c.c_end_et for c in plan.contributions) <= 1.085e8
            assert plan.cut_chunks and set(plan.cut_chunks.values()) == {window}
            assert all(not p.cut_chunks for p in plans if p.probe_id != probe_id)


class TestCacheEntry:
    """An entry gives back the worker's result shape for its own signature."""

    def test_round_trip(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(classify_cache, "CLASSIFY_ROOT", tmp_path)
        sig = {"version": 1, "naif_id": -5}
        classify_cache.save("M", -5, sig, _result(-5))
        assert classify_cache.load("M", -5, sig) == _result(-5)
        assert classify_cache.load("M", -5, {**sig, "version": 2}) is None
        classify_cache.save("M", -6, sig, {"status": "no_coverage"})
        assert classify_cache.load("M", -6, sig) == {"status": "no_coverage"}

    def test_signature_keys_on_naif_and_version(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        kernel = tmp_path / "k.bsp"
        kernel.write_bytes(b"k")
        probes = [(tmp_path, [kernel], -1), (tmp_path, [kernel], -2)]
        a, b = classify_cache.build_signatures(probes, [])
        assert a["kernels"] == b["kernels"] and a != b
        monkeypatch.setattr(classify_cache, "CLASSIFY_VERSION", 99)
        assert classify_cache.build_signatures(probes[:1], [])[0] != a


class TestWorker:
    """A failed furnish leaves no mission kernel loaded in the worker."""

    def test_failed_furnish_unloads(self, monkeypatch: pytest.MonkeyPatch) -> None:
        loaded: set[str] = set()

        def furnsh(path: str) -> None:
            if path == "bad.bsp":
                raise RuntimeError("bad kernel")
            loaded.add(path)

        monkeypatch.setattr(classify.spiceypy, "furnsh", furnsh)
        monkeypatch.setattr(classify.spiceypy, "unload", loaded.discard)
        with pytest.raises(RuntimeError):
            classify._classify_worker("M", ["a.bsp", "bad.bsp", "c.bsp"], -1)
        assert loaded == set()
