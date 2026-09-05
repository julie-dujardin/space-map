"""Tests for space_map_data.export.position.frames."""

import math

import pytest

from space_map_data.export.position.frames import (
    _OBLIQUITY_RAD,
    equatorial_to_ecliptic,
    is_equatorial,
    moon_orbit,
)
from space_map_data.models.object import (
    AsterSatMoon,
    Object,
    ObjectType,
    OrbitalSource,
    SBDBMoon,
)
from space_map_data.probes.propagation import AU_KM


def _ecliptic_to_equatorial(i_deg, om_deg, w_deg=None):
    """The inverse rotation, written out, for round-tripping.

    Spelled independently rather than by flipping the module's own obliquity:
    a test that reaches in to reconfigure its subject stops checking it.
    """
    i, om = math.radians(i_deg), math.radians(om_deg)
    w = math.radians(w_deg if w_deg is not None else 0.0)
    peri = (
        math.cos(om) * math.cos(w) - math.sin(om) * math.sin(w) * math.cos(i),
        math.sin(om) * math.cos(w) + math.cos(om) * math.sin(w) * math.cos(i),
        math.sin(w) * math.sin(i),
    )
    normal = (math.sin(om) * math.sin(i), -math.cos(om) * math.sin(i), math.cos(i))
    cos_e, sin_e = math.cos(-_OBLIQUITY_RAD), math.sin(-_OBLIQUITY_RAD)
    peri, normal = (
        (v[0], v[1] * cos_e + v[2] * sin_e, -v[1] * sin_e + v[2] * cos_e)
        for v in (peri, normal)
    )
    i_out = math.acos(max(-1.0, min(1.0, normal[2])))
    om_out = math.atan2(normal[0], -normal[1])
    w_out = math.atan2(
        peri[2] / math.sin(i_out),
        peri[0] * math.cos(om_out) + peri[1] * math.sin(om_out),
    )
    return (
        math.degrees(i_out) % 360.0,
        math.degrees(om_out) % 360.0,
        math.degrees(w_out) % 360.0 if w_deg is not None else None,
    )


def _moon_object(moon, source):
    """An Object carrying one moon row, as the export sees it."""
    obj = Object(id=moon.object_id, object_type=ObjectType.moon, orbital_source=source)
    setattr(
        obj, "astersat_moon" if isinstance(moon, AsterSatMoon) else "sbdb_moon", moon
    )
    return obj


class TestIsEquatorial:
    """Frame labels differ per source; only the equatorial ones need rotating."""

    @pytest.mark.parametrize(
        "frame,expected",
        [
            ("EQ", True),
            ("geoequat J2000", True),
            ("EC", False),
            (None, False),
            ("", False),
        ],
    )
    def test_labels(self, frame, expected):
        assert is_equatorial(frame) is expected


class TestEquatorialToEcliptic:
    """The rotation preserves the orbit and only re-expresses its orientation."""

    @pytest.mark.parametrize(
        "angles",
        [
            (93.4, 286.2, 45.0),
            (8.293, 92.6, 61.06),
            (0.5, 10.0, 20.0),
            (179.0, 200.0, 300.0),
        ],
    )
    def test_round_trip(self, angles):
        i, om, w = equatorial_to_ecliptic(*angles)
        back = _ecliptic_to_equatorial(i, om, w)
        assert back == pytest.approx(angles, abs=1e-9)

    def test_ecliptic_plane_comes_out_flat(self):
        """An orbit lying in the ecliptic reads as i=0 once rotated."""
        i, om, w = equatorial_to_ecliptic(math.degrees(_OBLIQUITY_RAD), 0.0, 0.0)
        assert i == pytest.approx(0.0, abs=1e-9)

    def test_equatorial_plane_tilts_by_the_obliquity(self):
        i, om, _ = equatorial_to_ecliptic(0.0, 0.0, 0.0)
        assert i == pytest.approx(math.degrees(_OBLIQUITY_RAD))
        # The equator's ascending node on the ecliptic is the autumn equinox.
        assert om == pytest.approx(180.0)

    def test_apse_line_is_optional(self):
        """Most SBDB satellite orbits give the plane but not the periapsis."""
        i, om, w = equatorial_to_ecliptic(93.4, 286.2)
        assert w is None
        assert (i, om) == pytest.approx(equatorial_to_ecliptic(93.4, 286.2, 0.0)[:2])


class TestMoonOrbit:
    """Both moon sources come out in the units and frame the zones ship."""

    def test_astersat_is_rotated_and_converted(self):
        moon = AsterSatMoon(
            object_id="spkid-120000022",
            parent_object_id="spkid-20000022",
            astersat_id="AN000022Kalliope",
            system_label="(22) Kalliope",
            satellite_label="Linus",
            frame="geoequat J2000",
            epoch_mjd=52000.0,
            a_km=1078.3,
            e=0.003814004,
            i=94.38318390,
            om=285.358496,
            w=251.182253,
            ma=8.797198,
            n=100.11980010,
            per_d=3.595692,
        )
        source = OrbitalSource.astersat
        out = moon_orbit(_moon_object(moon, source), source)
        assert out["epoch_jd"] == pytest.approx(2452000.5)
        assert out["a"] == pytest.approx(1078.3 / AU_KM)
        # In-plane and temporal elements are the same in either frame.
        assert out["e"] == moon.e
        assert out["ma"] == moon.ma
        assert out["n"] == moon.n
        assert (out["i"], out["om"], out["w"]) != (moon.i, moon.om, moon.w)
        assert _ecliptic_to_equatorial(out["i"], out["om"], out["w"]) == pytest.approx(
            (moon.i, moon.om, moon.w), abs=1e-9
        )

    def test_sbdb_ecliptic_row_is_left_alone(self):
        moon = SBDBMoon(
            object_id="spkid-120000045",
            parent_object_id="spkid-20000045",
            parent_spkid=20000045,
            sat_index=0,
            frame="EC",
            epoch_jd=2452980.0,
            a_km=1164.51,
            e=0.006,
            i=107.6,
            om=202.5,
            w=138.0,
            ma=10.0,
            n=3.5,
        )
        source = OrbitalSource.sbdb_moon
        out = moon_orbit(_moon_object(moon, source), source)
        assert (out["i"], out["om"], out["w"]) == (moon.i, moon.om, moon.w)

    def test_sbdb_derives_mean_motion_from_the_period(self):
        """SBDB satellite orbits ship a period in hours but never a mean motion."""
        moon = SBDBMoon(
            object_id="spkid-120000022",
            parent_object_id="spkid-20000022",
            parent_spkid=20000022,
            sat_index=0,
            frame="EQ",
            per_h=86.296,
        )
        source = OrbitalSource.sbdb_moon
        out = moon_orbit(_moon_object(moon, source), source)
        assert out["n"] == pytest.approx(360.0 * 24.0 / 86.296)

    def test_partial_row_yields_only_what_it_has(self):
        moon = SBDBMoon(
            object_id="spkid-120000022",
            parent_object_id="spkid-20000022",
            parent_spkid=20000022,
            sat_index=0,
            frame="EQ",
            a_km=1063.0,
            i=93.4,
            om=286.2,
        )
        source = OrbitalSource.sbdb_moon
        out = moon_orbit(_moon_object(moon, source), source)
        assert set(out) == {"a", "i", "om"}
        # The plane is still corrected even with no apse line to go with it.
        assert out["i"] != 93.4

    def test_a_body_with_no_moon_row_is_empty(self):
        obj = Object(id="naif-399", object_type=ObjectType.planet)
        assert moon_orbit(obj, OrbitalSource.sbdb_moon) == {}

    def test_a_non_moon_source_is_empty(self):
        """Only the moon providers have a sub-table to read."""
        moon = SBDBMoon(
            object_id="spkid-120000022",
            parent_object_id="spkid-20000022",
            parent_spkid=20000022,
            sat_index=0,
            a_km=1063.0,
        )
        obj = _moon_object(moon, OrbitalSource.sbdb_moon)
        assert moon_orbit(obj, OrbitalSource.spice) == {}
