"""Tests for the conversion of published disk-resolved fits into the factor on
the lunar weight of McEwen that the renderer takes."""

import math

import pytest

from space_map_data.constants.disk_photometry import (
    DISK_PHOTOMETRY,
    LunarLambertFit,
    MinnaertFit,
)
from space_map_data.constants.measured_shapes import Reference
from space_map_data.export.disk_photometry import (
    lunar_weight_scale,
    mcewen_lunar_weight,
    minnaert_lunar_weight,
    weight_scale,
)

_REF = Reference(title="test", url="https://example.org")


class TestMinnaertLunarWeight:
    """A Minnaert disc becomes the lunar weight of its best lunar-Lambert fit."""

    def test_flat_disc_is_all_lunar(self) -> None:
        # k = 0.5 at phase 0 is a flat disc, which the lunar part alone gives.
        assert minnaert_lunar_weight(0.5, 0) == pytest.approx(1, abs=1e-9)

    def test_lambert_disc_has_no_lunar_part(self) -> None:
        assert minnaert_lunar_weight(1.0, 0) == pytest.approx(0, abs=1e-9)

    def test_goes_down_as_k_goes_up(self) -> None:
        weights = [minnaert_lunar_weight(k, 10) for k in (0.5, 0.6, 0.7, 0.8, 0.9)]
        assert weights == sorted(weights, reverse=True)


class TestWeightScale:
    """The factor fits McEwen's weight to the published one over its phases."""

    def test_enceladus(self) -> None:
        # Minnaert k = 0.78 at 5-17°: a little under 0.4 of the weight of the Moon.
        fit = MinnaertFit(0.78, 0.0, 5, 17, _REF)
        assert weight_scale(fit) == pytest.approx(0.38, abs=0.01)

    def test_the_weight_of_mcewen_gives_1(self) -> None:
        fit = LunarLambertFit(mcewen_lunar_weight(30), 0.0, 30, 30, _REF)
        assert weight_scale(fit) == pytest.approx(1, abs=1e-12)

    def test_half_the_weight_of_mcewen_gives_one_half(self) -> None:
        fit = LunarLambertFit(mcewen_lunar_weight(20) / 2, 0.0, 20, 20, _REF)
        assert weight_scale(fit) == pytest.approx(0.5, abs=1e-12)

    def test_skips_phases_where_mcewen_has_no_lunar_part(self) -> None:
        # Past 104° the weight of McEwen is 0, and a ratio there says nothing.
        fit = LunarLambertFit(0.5, 0.0, 60, 150, _REF)
        assert math.isfinite(weight_scale(fit))


class TestLunarWeightScale:
    def test_none_without_a_record(self) -> None:
        assert lunar_weight_scale("naif-301") is None
        assert lunar_weight_scale("naif-502") is None

    def test_every_record_converts(self) -> None:
        for object_id in DISK_PHOTOMETRY:
            scale = lunar_weight_scale(object_id)
            assert scale is not None
            assert 0.2 < scale < 1.5, object_id

    def test_bright_ice_darkens_toward_the_limb(self) -> None:
        enceladus = lunar_weight_scale("naif-602")
        mimas = lunar_weight_scale("naif-601")
        rhea = lunar_weight_scale("naif-605")
        assert enceladus is not None and mimas is not None and rhea is not None
        assert enceladus < mimas < 1 < rhea
