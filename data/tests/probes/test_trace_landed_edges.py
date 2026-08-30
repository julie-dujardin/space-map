"""A landed phase starts when the craft touches down, not at the next sample."""

import numpy as np
import pytest

from space_map_data.probes import trace

DAY = 86400.0


@pytest.fixture
def surface(monkeypatch: pytest.MonkeyPatch):
    """Stand in for SPICE with a single known transition instant."""

    def _install(
        *, landed_from: float | None = None, landed_until: float | None = None
    ):
        if landed_from is not None:
            monkeypatch.setattr(
                trace, "_is_at_rest_at", lambda naif, et, body: et >= landed_from
            )
        else:
            assert landed_until is not None
            monkeypatch.setattr(
                trace, "_is_at_rest_at", lambda naif, et, body: et <= landed_until
            )

    return _install


def test_edge_lands_on_the_touchdown_instant(surface) -> None:
    surface(landed_from=1000.0)
    edge = trace._refine_landed_edge(-150, 606, 0.0, DAY)
    assert edge == pytest.approx(1000.0, abs=trace._LANDED_EDGE_TOL_S)


def test_a_lift_off_edge_reads_the_other_way(surface) -> None:
    """Landed sample first, flying sample after: the phase ends at lift-off."""
    surface(landed_until=5000.0)
    edge = trace._refine_landed_edge(-150, 606, DAY, 0.0)
    assert edge == pytest.approx(5000.0, abs=trace._LANDED_EDGE_TOL_S)


def test_edge_stays_inside_the_bracket(surface) -> None:
    """The flying sample keeps its place, so a refined phase can never
    overlap the flying range the scan classified."""
    surface(landed_from=1.0)
    assert 0.0 < trace._refine_landed_edge(-150, 606, 0.0, DAY) <= DAY


def test_the_edge_is_dated_on_the_at_rest_gate(monkeypatch: pytest.MonkeyPatch) -> None:
    """A craft under a parachute passes the scan's gate long before it is
    down, so the instant is read against a tighter one."""
    seen: dict[str, float | int | None] = {}

    def _fake(
        naif, ets, ssb, target_ssb_cache=None, targets=None, vbf_max_m_per_s=None
    ):
        seen["vbf"] = vbf_max_m_per_s
        seen["targets"] = len(targets or ())
        return np.zeros(len(ets), dtype=int)

    monkeypatch.setattr(
        trace, "_positions_wrt_ssb", lambda naif, ets: np.zeros((len(ets), 3))
    )
    monkeypatch.setattr(trace, "_per_sample_landed_body", _fake)
    trace._is_at_rest_at(-150, 0.0, 606)
    assert seen["vbf"] == trace._AT_REST_VBF_M_PER_S
    assert trace._AT_REST_VBF_M_PER_S < trace._LANDED_VBF_M_PER_S
    # Only the body the scan already picked, not all six landing targets.
    assert seen["targets"] == 1


def test_phases_take_the_refined_edges(
    monkeypatch: pytest.MonkeyPatch, surface
) -> None:
    """Day-cadence samples put the landing a day late; the phase reports the
    instant instead. The open end keeps the last sample — nothing to bisect."""
    surface(landed_from=1.5 * DAY)
    monkeypatch.setattr(
        trace, "_positions_wrt_ssb", lambda naif, ets: np.zeros((len(ets), 3))
    )
    monkeypatch.setattr(
        trace,
        "_per_sample_landed_body",
        lambda *args, **kwargs: np.array([0, 0, 606, 606, 606]),
    )
    monkeypatch.setattr(trace, "_classify_flying_subrange", lambda *args: None)
    _, phases = trace._classify_contiguous_interval(-150, 0.0, 4 * DAY, 1.0)
    assert len(phases) == 1
    assert phases[0].start_et == pytest.approx(1.5 * DAY, abs=trace._LANDED_EDGE_TOL_S)
    assert phases[0].end_et == 4 * DAY
