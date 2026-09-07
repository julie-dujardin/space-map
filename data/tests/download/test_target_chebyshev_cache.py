"""The probe-target Chebyshev fit cache."""

import numpy as np
import pytest

from space_map_data.download.providers.spice.probes.target_chebyshev import (
    _BASE_INTERVAL_S,
    _DEGREE,
    _TOLERANCE_KM,
    FIT_PARENT_NAIF_ID,
    _cached,
    _source_digest,
)
from space_map_data.utils.time import jd_to_et

NAIF_ID = 2101955
START_JD = 2433282.5
END_JD = 2469807.5
START_ET = jd_to_et(START_JD)
END_ET = jd_to_et(END_JD)


@pytest.fixture
def kernel(tmp_path):
    path = tmp_path / "orx.bsp"
    path.write_bytes(b"kernel")
    return path


def _write_npz(path, digest=None):
    """A fit file as `extract_target_chebyshev` writes it; no `digest` is one
    written before the kernels joined the cache key."""
    np.savez(
        path,
        start_jds=np.array([START_JD]),
        end_jds=np.array([END_JD]),
        coeffs=np.zeros((1, 3, _DEGREE + 1), dtype=np.float64),
        meta=np.array([NAIF_ID, FIT_PARENT_NAIF_ID, _DEGREE], dtype=np.int64),
        params=np.array(
            [START_JD, END_JD, _BASE_INTERVAL_S, _TOLERANCE_KM], dtype=np.float64
        ),
        sources=np.array([digest] if digest is not None else []),
    )


class TestFitCache:
    """A fit is only reusable when the kernels behind it are the ones on disk."""

    def test_the_same_kernels_reuse_the_fit(self, tmp_path, kernel):
        out = tmp_path / f"{NAIF_ID}.npz"
        digest = _source_digest([kernel])
        _write_npz(out, digest)
        assert _cached(out, NAIF_ID, START_ET, END_ET, digest) is True

    def test_a_new_kernel_refits(self, tmp_path, kernel):
        """A mission SPK landing later extends a target's coverage without
        moving the requested year range, so nothing else in the cache key
        notices it."""
        out = tmp_path / f"{NAIF_ID}.npz"
        _write_npz(out, _source_digest([kernel]))
        extra = tmp_path / "orx-extended.bsp"
        extra.write_bytes(b"more kernel")
        digest = _source_digest([kernel, extra])
        assert _cached(out, NAIF_ID, START_ET, END_ET, digest) is False

    def test_a_rewritten_kernel_refits(self, tmp_path, kernel):
        out = tmp_path / f"{NAIF_ID}.npz"
        _write_npz(out, _source_digest([kernel]))
        kernel.write_bytes(b"reconstructed")
        assert (
            _cached(out, NAIF_ID, START_ET, END_ET, _source_digest([kernel])) is False
        )

    def test_a_file_fit_before_the_digest_refits(self, tmp_path, kernel):
        out = tmp_path / f"{NAIF_ID}.npz"
        _write_npz(out)
        assert (
            _cached(out, NAIF_ID, START_ET, END_ET, _source_digest([kernel])) is False
        )
