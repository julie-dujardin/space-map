"""Kernels built from the Space-Track element-set archive.

Covers what the synthesiser decides — which probes it will speak for, and
where it cuts a run of element sets — plus that a written kernel evaluates.
"""

import numpy as np
import pytest
import spiceypy

from space_map_data.download.providers.spice.probes import tle_synth
from space_map_data.download.providers.spice.probes.synthetic_index import write_type10
from space_map_data.download.providers.spice.probes.tle_synth import (
    MAX_GAP_DAYS,
    _candidates,
    _is_followed,
    split_runs,
)
from space_map_data.utils.paths import SOURCES_POSITION_DIR

_S_PER_DAY = 86400.0

# Two Cluster II Rumba sets two days apart, from the 2018 archive: a 54-hour,
# e=0.47 orbit, which is the deep-space regime SDP4 covers and the near-Earth
# model does not.
RUMBA_PAIRS = [
    (
        "1 26463U 00045A   18003.68813416 -.00000175  00000-0  00000+0 0  9995",
        "2 26463 133.5552 334.5777 4689074 251.3081  27.4249  0.44186000 96660",
    ),
    (
        "1 26463U 00045A   18005.68813416 -.00000175  00000-0  00000+0 0  9995",
        "2 26463 133.5552 334.5777 4689074 251.3081  27.4249  0.44186000 96661",
    ),
]


@pytest.fixture
def lsk():
    """Furnish the leapseconds kernel `getelm` needs to resolve a TLE epoch."""
    kernels = sorted((SOURCES_POSITION_DIR / "spice-kernels" / "lsk").glob("*.tls"))
    if not kernels:
        pytest.skip("no leapseconds kernel downloaded")
    spiceypy.furnsh(str(kernels[0]))
    yield
    spiceypy.kclear()


def _entry(naif, norad, name="Cluster II Rumba", sources=("EVENTS-DB",)):
    return {
        "probe_id": 83365888,
        "name": name,
        "naif_id": naif,
        "inception_mjd": 51000,
        "dedupe": 0,
        "cospar_id": "2000-045A",
        "norad_cat_id": norad,
        "kernel_sources": [{"mission": m, "naif_id": naif} for m in sources],
    }


def _sets(count, start=0.0, step_days=1.0):
    """`count` element sets `step_days` apart; contents don't affect the cut."""
    return {start + i * step_days * _S_PER_DAY: [0.0] * 10 for i in range(count)}


class TestSplitRuns:
    """Where a run of element sets ends."""

    def test_a_steady_cadence_is_one_run(self):
        runs = split_runs(_sets(30))
        assert len(runs) == 1
        assert len(runs[0][0]) == 30

    def test_a_gap_ends_the_run(self):
        late = _sets(10, start=(MAX_GAP_DAYS + 40) * _S_PER_DAY)
        runs = split_runs(_sets(10) | late)
        assert [len(epochs) for epochs, _ in runs] == [10, 10]

    def test_a_gap_inside_the_tolerance_does_not(self):
        late = _sets(10, start=(MAX_GAP_DAYS - 1 + 9) * _S_PER_DAY)
        assert len(split_runs(_sets(10) | late)) == 1

    def test_a_lone_element_set_is_dropped(self):
        # A stray corrupt epoch — Spektr-R carries one dated 1970 — lands in a
        # run of its own and states nothing.
        runs = split_runs(_sets(10) | {-1.0e9: [0.0] * 10})
        assert len(runs) == 1
        assert len(runs[0][0]) == 10

    def test_epochs_come_back_in_order(self):
        shuffled = {5.0: [0.0] * 10, 1.0: [1.0] * 10, 3.0: [2.0] * 10}
        ((epochs, _),) = split_runs(shuffled)
        assert epochs == [1.0, 3.0, 5.0]


class TestFollowedGate:
    """Telling a craft the catalogue followed from one it logged on its way out."""

    def test_a_year_of_daily_sets_is_followed(self):
        assert _is_followed(split_runs(_sets(300)))

    def test_a_launch_day_pair_is_not(self):
        # Queqiao's whole archive presence: two sets, both on launch day.
        assert not _is_followed(split_runs(_sets(2, step_days=0.01)))

    def test_a_long_span_of_too_few_sets_is_not(self):
        assert not _is_followed(split_runs(_sets(5, step_days=20.0)))

    def test_many_sets_inside_a_month_is_not(self):
        assert not _is_followed(split_runs(_sets(40, step_days=0.5)))


class TestCandidates:
    """Which registry probes the synthesiser will speak for."""

    def test_a_probe_with_no_trajectory_qualifies(self, monkeypatch):
        monkeypatch.setattr(
            tle_synth, "load_registry", lambda: [_entry(-90000270, 26463)]
        )
        assert list(_candidates()) == [-90000270]

    def test_a_probe_an_archive_covers_is_left_alone(self, monkeypatch):
        monkeypatch.setattr(
            tle_synth,
            "load_registry",
            lambda: [_entry(-82, 25008, sources=("CASSINI",))],
        )
        assert _candidates() == {}

    def test_a_probe_another_synthesiser_claims_is_left_alone(self, monkeypatch):
        monkeypatch.setattr(
            tle_synth,
            "load_registry",
            lambda: [_entry(-90000123, 27, sources=("EVENTS-DB", "GCAT-DEEP"))],
        )
        assert _candidates() == {}

    def test_a_norad_several_probes_claim_is_dropped(self, monkeypatch):
        # Chang'e 5's lander, orbiter and returner are all 47097; the catalogue
        # followed one of them and does not say which.
        monkeypatch.setattr(
            tle_synth,
            "load_registry",
            lambda: [
                _entry(-90000069, 47097, name="Chang'e 5 Lander"),
                _entry(-90000169, 47097, name="Chang'e 5 Orbiter"),
            ],
        )
        assert _candidates() == {}

    def test_a_probe_with_no_norad_is_skipped(self, monkeypatch):
        monkeypatch.setattr(
            tle_synth, "load_registry", lambda: [_entry(-90000270, None)]
        )
        assert _candidates() == {}


class TestWriteType10:
    """A written kernel evaluates, and only over the run it was given."""

    @pytest.fixture
    def kernel(self, tmp_path, lsk):
        epochs, elements = [], []
        for line1, line2 in RUMBA_PAIRS:
            epoch, elems = spiceypy.getelm(1957, [line1, line2])
            epochs.append(epoch)
            elements.append(list(elems))
        path = tmp_path / "-90000270-extrap.bsp"
        write_type10(path, -90000270, "tle26463", [(epochs, elements, "TLE test")])
        spiceypy.furnsh(str(path))
        yield path, epochs
        spiceypy.unload(str(path))

    def test_a_position_comes_back_earth_centred(self, kernel):
        _, epochs = kernel
        state, _ = spiceypy.spkezr("-90000270", epochs[0], "J2000", "NONE", "399")
        radius = float(np.linalg.norm(state[:3]))
        # Perigee sits near 19,000 km and apogee past 120,000 km on this orbit.
        assert 6_400 < radius < 200_000

    def test_outside_the_run_there_is_no_coverage(self, kernel):
        _, epochs = kernel
        with pytest.raises(spiceypy.exceptions.SpiceyError):
            spiceypy.spkezr(
                "-90000270", epochs[-1] + 30 * _S_PER_DAY, "J2000", "NONE", "399"
            )

    def test_the_segment_covers_the_run(self, kernel):
        path, epochs = kernel
        cell = spiceypy.cell_double(200)
        spiceypy.spkcov(str(path), -90000270, cell)
        assert spiceypy.wncard(cell) == 1
        first, last = spiceypy.wnfetd(cell, 0)
        assert first == pytest.approx(epochs[0])
        assert last == pytest.approx(epochs[-1])
