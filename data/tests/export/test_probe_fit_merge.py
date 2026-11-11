"""Tests for merging a probe's kernel plan with its curated-landing plan."""

import dataclasses
from pathlib import Path
from types import SimpleNamespace

import pytest

from space_map_data.export.position.probes import fit, sidecar
from space_map_data.export.position.probes.plan import ChunkContribution, ProbePlan
from space_map_data.probes.zones import ZONES_BY_KEY
from space_map_data.utils.time import S_PER_DAY, jd_to_et

_PROBE = 38514688
_START_JD = 2433282.5
_VENUS = ZONES_BY_KEY["venus"]
_CHUNK = 77
_CHUNK_START = jd_to_et(_START_JD) + _CHUNK * _VENUS.chunk_days * S_PER_DAY
_SUB_S = _VENUS.kepler_subchunk_days * S_PER_DAY


def _plans(kernel: Path) -> list[ProbePlan]:
    """The landing plan first, the order `build_fits` sorts a kernel-less plan
    with the canonical NAIF into."""
    landed = ProbePlan(probe_id=_PROBE, naif_id=-1, kernels=[])
    landed.contributions.append(
        ChunkContribution(
            zone_key="venus",
            chunk_idx=_CHUNK,
            c_start_et=_CHUNK_START + 20 * _SUB_S,
            c_end_et=_CHUNK_START + 40 * _SUB_S,
            kind="landed",
            landed_body_id_value=299,
            landed_body_id_type=0,
            site_lat_lng=(-5.0, 351.0),
        )
    )
    flying = ProbePlan(probe_id=_PROBE, naif_id=-1, kernels=[kernel])
    flying.contributions.append(
        ChunkContribution(
            zone_key="venus",
            chunk_idx=_CHUNK,
            c_start_et=_CHUNK_START + 5 * _SUB_S,
            c_end_et=_CHUNK_START + 18 * _SUB_S,
        )
    )
    flying.contributions.append(
        ChunkContribution(
            zone_key="venus",
            chunk_idx=_CHUNK - 1,
            c_start_et=_CHUNK_START - 10 * _SUB_S,
            c_end_et=_CHUNK_START,
        )
    )
    return [landed, flying]


@pytest.fixture
def kernel(tmp_path: Path) -> Path:
    path = tmp_path / "conic.bsp"
    path.write_bytes(b"conic")
    return path


def test_flying_data_sets_the_grid_and_center_of_a_landed_record(
    kernel: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(fit.spiceypy, "furnsh", lambda _path: None)
    monkeypatch.setattr(fit.spiceypy, "unload", lambda _path: None)
    monkeypatch.setattr(fit, "sited_landed_chunk", lambda **_: "site")
    monkeypatch.setattr(
        fit, "detect_fit_center", lambda *_: SimpleNamespace(naif_id=299)
    )
    monkeypatch.setattr(fit, "fit_center_header_fields", lambda _chosen: (299, 0))
    monkeypatch.setattr(
        fit,
        "size_chunk",
        lambda _naif, _zone, start, _end, **_: SimpleNamespace(
            sub_chunks=[SimpleNamespace(t_start_et=start)]
        ),
    )
    by_chunk, _, _ = fit._fit_probe_keys(
        _PROBE, _plans(kernel), {("venus", _CHUNK)}, [], _START_JD, {}
    )
    rec = by_chunk[("venus", _CHUNK)]
    assert rec.landed == "site"
    assert rec.first_offset == 5
    assert (rec.fit_center_id_value, rec.fit_center_id_type) == (299, 0)


def test_a_chunk_only_the_landing_reaches_carries_no_kernel(
    kernel: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A conic re-synthesis leaves the site's fits alone."""
    monkeypatch.setattr(sidecar, "events_files_hash", lambda: "events")
    plans = _plans(kernel)
    plans[0].contributions[0] = dataclasses.replace(
        plans[0].contributions[0], chunk_idx=_CHUNK + 1
    )
    sigs = fit.expected_fit_sigs(plans, kernel.parent, {})
    assert sigs[(_PROBE, "venus", _CHUNK + 1)]["kernels"] == []
    assert [k["path"] for k in sigs[(_PROBE, "venus", _CHUNK)]["kernels"]] == [
        "conic.bsp"
    ]
