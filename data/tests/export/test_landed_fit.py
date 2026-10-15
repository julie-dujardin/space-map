"""The landed record that the SPICE kernel of a craft gives."""

import math

import pytest

from space_map_data.export.position.probes import landed

MARS_A_KM = 3396.19
MARS_C_KM = 3376.20


def test_the_latitude_is_planetocentric(monkeypatch: pytest.MonkeyPatch):
    """Perseverance's site. A geodetic latitude is 0.2 degrees north of it."""
    lat, lon = math.radians(18.4447), math.radians(77.4508)
    r = 1 / math.hypot(math.cos(lat) / MARS_A_KM, math.sin(lat) / MARS_C_KM)
    point = [
        r * math.cos(lat) * math.cos(lon),
        r * math.cos(lat) * math.sin(lon),
        r * math.sin(lat),
    ]
    monkeypatch.setattr(
        landed.spiceypy, "bodvrd", lambda *_: (3, [MARS_A_KM, MARS_A_KM, MARS_C_KM])
    )
    monkeypatch.setattr(landed.spiceypy, "spkpos", lambda *_: (point, 0.0))
    monkeypatch.setattr(landed, "_daily_midnight_ets", lambda *_: [])

    fit = landed.fit_landed_chunk(-168, 499, 0.0, 0.0, 3600.0)

    assert fit is not None
    assert fit.lat_ref_deg == pytest.approx(18.4447, abs=1e-9)
    assert fit.lng_ref_deg == pytest.approx(77.4508, abs=1e-9)
    assert fit.alt_ref_m == pytest.approx(0.0, abs=1e-3)
