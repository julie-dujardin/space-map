"""Natural-body fits stop where the body's own kernels stop.

Synthetic SPKs put a moon on a Kepler orbit over chosen spans, so each test
can say exactly where coverage starts, ends and has a gap.
"""

import math
from pathlib import Path

import numpy as np
import pytest
import spiceypy

from space_map_data.download.providers.objects import chebyshev
from space_map_data.download.providers.objects.chebyshev import extract_chebyshev
from space_map_data.download.providers.spice.bodies import downloader
from space_map_data.download.providers.spice.bodies.elements import (
    fill_osculating_chunks,
    fit_moon_chunked_elements,
)
from space_map_data.export.pipeline.snapshots import moons_snapshots
from space_map_data.models.object import Horizons, Object, ObjectType
from space_map_data.utils.naif import MajorBody
from space_map_data.utils.spk import clip_windows, coverage_windows
from space_map_data.utils.time import S_PER_DAY, et_to_jd, jd_to_et, year_to_jd

_PUCK = MajorBody(name="Puck", naif_id=715, parent_id=799, object_type=ObjectType.moon)
# Semi-major axis.
_RADIUS_KM = 86_000.0
_PERIOD_S = 100 * S_PER_DAY
_MU = 4 * math.pi**2 * _RADIUS_KM**3 / _PERIOD_S**2


def _position(ets: np.ndarray) -> np.ndarray:
    # Eccentric and inclined, so every angle the moon fits is well defined.
    elts = [_RADIUS_KM * 0.95, 0.05, 0.3, 1.0, 2.0, 0.0, 0.0, _MU]
    return np.array([spiceypy.conics(elts, float(et))[:3] for et in ets])


def _year_et(year: int) -> float:
    return jd_to_et(year_to_jd(year))


def _write_spk(path: Path, lo_year: int, hi_year: int, intlen_days: float) -> Path:
    """A Type-2 SPK putting 715 on a Kepler orbit around 799 over the span."""
    degree = 12
    lo, hi = _year_et(lo_year), _year_et(hi_year)
    intlen = intlen_days * S_PER_DAY
    n = math.ceil((hi - lo) / intlen)
    tau = np.cos(np.pi * np.arange(degree + 1) / degree)
    records = []
    for i in range(n):
        mid = lo + (i + 0.5) * intlen
        xyz = _position(mid + 0.5 * intlen * tau)
        records.append(
            np.concatenate(
                [
                    np.polynomial.chebyshev.chebfit(tau, xyz[:, a], degree)
                    for a in range(3)
                ]
            )
        )
    handle = spiceypy.spkopn(str(path), "test", 0)
    spiceypy.spkw02(
        handle,
        715,
        799,
        "ECLIPJ2000",
        lo,
        min(hi, lo + n * intlen),
        "puck",
        intlen,
        n,
        degree,
        np.concatenate(records),
        lo,
    )
    spiceypy.spkcls(handle)
    return path


def _write_spk05(path: Path, lo_year: int, hi_year: int) -> Path:
    """A Type-5 (two-body) SPK for 715 around 799: no Chebyshev segment."""
    lo, hi = _year_et(lo_year), _year_et(hi_year)
    epochs = np.linspace(lo, hi, 50)
    states = [
        spiceypy.conics([_RADIUS_KM * 0.95, 0.05, 0.3, 1.0, 2.0, 0.0, 0.0, _MU], t)
        for t in epochs
    ]
    handle = spiceypy.spkopn(str(path), "test", 0)
    spiceypy.spkw05(
        handle, 715, 799, "ECLIPJ2000", lo, hi, "puck", _MU, 50, states, epochs
    )
    spiceypy.spkcls(handle)
    return path


@pytest.fixture
def spice(tmp_path):
    spiceypy.kclear()
    yield tmp_path
    spiceypy.kclear()


def _furnish(*paths: Path) -> list[Path]:
    for path in paths:
        spiceypy.furnsh(str(path))
    return list(paths)


def _jd(year: int) -> float:
    return et_to_jd(_year_et(year))


class TestClipWindows:
    """Coverage is cut to the configured range, keeping each window apart."""

    def test_cuts_and_drops(self):
        windows = [(0.0, 10.0), (20.0, 30.0), (40.0, 50.0)]
        assert clip_windows(windows, 5.0, 45.0) == [
            (5.0, 10.0),
            (20.0, 30.0),
            (40.0, 45.0),
        ]
        assert clip_windows(windows, 10.0, 20.0) == []


class TestExtractChebyshev:
    """Each body is fit over its merged kernel coverage inside the range."""

    def test_fits_only_the_covered_years(self, spice):
        kernels = _furnish(
            _write_spk(spice / "a.bsp", 2000, 2002, 2),
            _write_spk(spice / "b.bsp", 2004, 2010, 2),
        )
        out = spice / "cheb"
        assert extract_chebyshev(out, [_PUCK], kernels, 2001, 2006) == 1
        with np.load(out / "715.npz") as data:
            windows = data["windows"]
            starts, ends, coeffs = data["start_jds"], data["end_jds"], data["coeffs"]
        np.testing.assert_allclose(
            windows, [[_jd(2001), _jd(2002)], [_jd(2004), _jd(2006)]], atol=1e-6
        )
        assert starts[0] == pytest.approx(_jd(2001))
        assert ends[-1] == pytest.approx(_jd(2006))
        # The gap between the kernels stays a gap.
        assert not ((ends > _jd(2002) + 1e-6) & (starts < _jd(2004) - 1e-6)).any()
        # The fit reproduces the orbit inside a segment.
        i = len(starts) // 3
        t = 0.3
        jd = starts[i] + (t + 1) / 2 * (ends[i] - starts[i])
        fitted = [np.polynomial.chebyshev.chebval(t, coeffs[i, a]) for a in range(3)]
        expected = _position(np.array([(jd - 2451545.0) * S_PER_DAY]))[0]
        np.testing.assert_allclose(fitted, expected, atol=1e-3)

    def test_out_of_range_body_gets_no_file(self, spice):
        kernels = _furnish(_write_spk(spice / "a.bsp", 2000, 2002, 2))
        out = spice / "cheb"
        assert extract_chebyshev(out, [_PUCK], kernels, 2003, 2006) == 0
        assert not (out / "715.npz").exists()

    def test_cache_keys_on_the_clipped_coverage(self, spice):
        out = spice / "cheb"
        first = _furnish(_write_spk(spice / "a.bsp", 2000, 2003, 2))
        extract_chebyshev(out, [_PUCK], first, 2001, 2006)
        stamp = (out / "715.npz").stat().st_mtime_ns
        # The range grows past the kernel's end: the clipped coverage stays.
        extract_chebyshev(out, [_PUCK], first, 2001, 2008)
        assert (out / "715.npz").stat().st_mtime_ns == stamp
        # A kernel that extends coverage refits under the same range.
        second = _furnish(_write_spk(spice / "b.bsp", 2003, 2005, 2))
        extract_chebyshev(out, [_PUCK], first + second, 2001, 2008)
        assert (out / "715.npz").stat().st_mtime_ns != stamp
        with np.load(out / "715.npz") as data:
            np.testing.assert_allclose(
                data["windows"], [[_jd(2001), _jd(2005)]], atol=1e-6
            )


class TestNonChebyshevKernel:
    """A body whose kernels hold no Chebyshev segment is still fit."""

    def test_type5_kernel_gets_the_fallback_params(self, spice):
        kernels = _furnish(_write_spk05(spice / "a.bsp", 2000, 2001))
        out = spice / "cheb"
        assert extract_chebyshev(out, [_PUCK], kernels, 1990, 2010) == 1
        with np.load(out / "715.npz") as data:
            assert float(data["params"][0]) == chebyshev._NON_CHEBYSHEV_PARAMS[0]
            assert int(data["meta"][2]) == chebyshev._NON_CHEBYSHEV_PARAMS[1]
            np.testing.assert_allclose(
                data["windows"], [[_jd(2000), _jd(2001)]], atol=1e-6
            )


class TestMoonChunks:
    """A chunk gets elements only when its validity span is inside coverage."""

    def test_chunks_outside_coverage_are_nan(self, spice):
        kernels = _furnish(
            _write_spk(spice / "a.bsp", 2000, 2004, 4),
            _write_spk(spice / "b.bsp", 2006, 2010, 4),
        )
        cell = spiceypy.support_types.SPICEDOUBLE_CELL(1000)
        coverage = coverage_windows(kernels, 715, cell)
        assert len(coverage) == 2
        chunk_days = 0.5 * 365.25
        midpoints = [_jd(2000) + (i + 0.5) * chunk_days for i in range(24)]
        result = fit_moon_chunked_elements(
            715, 799, _MU, midpoints, 0.5 * chunk_days * S_PER_DAY, coverage
        )
        assert result is not None
        _, elements = result
        covered = ~np.isnan(elements[:, 0])
        lo = [_jd(2000), _jd(2006)]
        hi = [_jd(2004), _jd(2010)]
        expected = np.array(
            [
                any(
                    m - chunk_days / 2 >= a - 1e-5 and m + chunk_days / 2 <= b + 1e-5
                    for a, b in zip(lo, hi)
                )
                for m in midpoints
            ]
        )
        np.testing.assert_array_equal(covered, expected)
        # Edge chunks fit on the samples their window has, not on none.
        assert covered[0] and covered[7] and covered[13]
        np.testing.assert_allclose(
            elements[covered, 6], 360.0 / (_PERIOD_S / S_PER_DAY), rtol=1e-3
        )

    def test_no_chunk_inside_coverage_skips_the_moon(self, spice):
        kernels = _furnish(_write_spk(spice / "a.bsp", 2000, 2001, 4))
        cell = spiceypy.support_types.SPICEDOUBLE_CELL(1000)
        chunk_days = 0.5 * 365.25
        midpoints = [_jd(2003) + (i + 0.5) * chunk_days for i in range(4)]
        assert (
            fit_moon_chunked_elements(
                715,
                799,
                _MU,
                midpoints,
                0.5 * chunk_days * S_PER_DAY,
                coverage_windows(kernels, 715, cell),
            )
            is None
        )


class TestOsculatingChunks:
    """Chunks Method C leaves empty get osculating elements inside coverage."""

    def test_fills_only_empty_covered_chunks(self, spice):
        kernels = _furnish(_write_spk(spice / "a.bsp", 2000, 2004, 4))
        cell = spiceypy.support_types.SPICEDOUBLE_CELL(1000)
        chunk_days = 0.5 * 365.25
        midpoints = [_jd(2000) + (i + 0.5) * chunk_days for i in range(12)]
        fitted = np.full((12, 9), np.nan)
        fitted[1] = 7.0
        elements = fill_osculating_chunks(
            fitted,
            715,
            799,
            _MU,
            midpoints,
            0.5 * chunk_days * S_PER_DAY,
            coverage_windows(kernels, 715, cell),
        )
        covered = ~np.isnan(elements[:, 0])
        np.testing.assert_array_equal(covered, [True] * 8 + [False] * 4)
        np.testing.assert_array_equal(elements[1], 7.0)
        filled = covered & (np.arange(12) != 1)
        np.testing.assert_allclose(
            elements[filled, 6], 360.0 / (_PERIOD_S / S_PER_DAY), rtol=1e-6
        )
        np.testing.assert_array_equal(elements[filled, 7:], 0.0)


class TestMoonChunkSidecars:
    """Every moon gets a sidecar bounded by its coverage, fit or not."""

    def test_unfit_moon_is_bounded_by_its_kernel(self, spice, monkeypatch):
        kernels = _furnish(_write_spk(spice / "a.bsp", 2002, 2006, 4))
        monkeypatch.setattr(
            downloader,
            "load_chebyshev_config",
            lambda: {"start_year": 2000, "end_year": 2010},
        )
        spice_dl = object.__new__(downloader.SpiceDownloader)
        spice_dl.moon_chunks_dir = spice / "moon-chunks"
        assert spice_dl._extract_moon_chunks([(715, 799, _MU, False)], kernels) == 20
        with np.load(spice / "moon-chunks" / "715.npz") as data:
            covered = ~np.isnan(data["elements"][:, 0])
            midpoints = data["chunk_midpoints_jd"]
        half = 0.25 * 365.25
        expected = (midpoints - half >= _jd(2002) - 1e-5) & (
            midpoints + half <= _jd(2006) + 1e-5
        )
        assert 6 <= expected.sum() < 20
        np.testing.assert_array_equal(covered, expected)


class TestMoonSnapshots:
    """A moon is left out of the `moons` chunks its sidecar has no row for,
    and out of all of them without a sidecar."""

    def test_nan_rows_drop_the_moon_from_those_chunks(self, tmp_path):
        chunks_dir = tmp_path / "derived" / "position" / "moon-chunks"
        chunks_dir.mkdir(parents=True)
        elements = np.ones((3, 9), dtype=np.float32)
        elements[2] = np.nan
        np.savez(
            chunks_dir / "650.npz",
            chunk_midpoints_jd=np.array([10.0, 20.0, 30.0]),
            elements=elements,
            meta=np.array([650, 6, 3], dtype=np.int64),
        )
        covered = Object(id="naif-650", naif_id=650, horizons=Horizons(naif_id=650))
        bare = Object(id="naif-651", naif_id=651, horizons=Horizons(naif_id=651))
        snaps = list(moons_snapshots([covered, bare], tmp_path).iterate())
        assert [[o.id for o in snap.objects] for snap in snaps] == [
            ["naif-650"],
            ["naif-650"],
            [],
        ]
