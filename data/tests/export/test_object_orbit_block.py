"""The `orbit` block an object bundle carries for an Earth satellite.

Earth sats persist no elements of their own: the snapshot overlay hangs the
week's set on the Object as `_daily_kepler`, and the object writer reads it
from there. Without the block the frontend has nothing to decide placement
from, so the whole satellite catalogue reads as position-less.
"""

from space_map_data.export.objects.writer import _ORBIT_FIELDS, _orbit_elements
from space_map_data.models.object import ObjectType, OrbitalSource

from tests.conftest import make_object

_DAILY = {
    "epoch_jd": 2461282.36,
    "a": 6849.47,
    "e": 0.00016,
    "i": 28.4729,
    "om": 296.7524,
    "w": 231.7887,
    "ma": 128.2565,
    "n": 15.315,
}


def _earth_sat(source: OrbitalSource, **overrides):
    return make_object(
        id="norad_satcat-20580",
        norad_cat_id=20580,
        object_type=ObjectType.spacecraft,
        orbital_source=source,
        **overrides,
    )


class TestOrbitElements:
    """Reading the snapshot overlay for each Earth-satellite source."""

    def test_spacetrack_row_carries_its_elements(self):
        obj = _earth_sat(OrbitalSource.spacetrack, daily_kepler=_DAILY)
        assert _orbit_elements(obj, _ORBIT_FIELDS) == _DAILY

    def test_celestrak_row_still_carries_its_elements(self):
        obj = _earth_sat(OrbitalSource.celestrak, daily_kepler=_DAILY)
        assert _orbit_elements(obj, _ORBIT_FIELDS) == _DAILY

    def test_no_overlay_means_no_block(self):
        obj = _earth_sat(OrbitalSource.spacetrack)
        obj._daily_kepler = None
        assert _orbit_elements(obj, _ORBIT_FIELDS) == {}
