"""Tests for the metallicity sources: GSP-Spec."""

import pyarrow as pa
import pytest

from space_map_data.extrasolar.sources import gaia


class TestGspspec:
    """The calibrations of Recio-Blanco et al. 2023 and where [Fe/H] holds."""

    def test_calibrated_values(self):
        good = "0" * 41
        stars = pa.table(
            {
                "logg_gspspec": pa.array([4.4, 2.0, 5.0, 4.0, None], pa.float32()),
                "mh_gspspec": pa.array([-0.1, -0.5, 0.0, 0.0, None], pa.float32()),
                "fem_gspspec": pa.array([0.05, 0.02, 0.1, 0.1, None], pa.float32()),
                "flags_gspspec": [good, good[:28] + "2" + good[29:], good, None, None],
            }
        )
        out = gaia.calibrate_gspspec(stars)
        mh = out["mh_gspspec_calibrated"].to_pylist()
        feh = out["feh_gspspec_calibrated"].to_pylist()
        assert mh[0] == pytest.approx(
            -0.1 + 0.274 - 0.1373 * 4.4 - 0.0050 * 4.4**2 + 0.0048 * 4.4**3, abs=1e-6
        )
        assert feh[0] == pytest.approx(
            -0.05 + 0.3699 - 0.0680 * 4.4 + 0.0028 * 4.4**2 - 0.0004 * 4.4**3,
            abs=1e-6,
        )
        # A poor [Fe/M], a log g past the range, or no flags: no [Fe/H].
        assert feh[1:] == [None, None, None, None]
        assert mh[4] is None
