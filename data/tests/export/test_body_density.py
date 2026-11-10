"""Tests for space_map_data.export.objects.body_density."""

import math

import pytest

from space_map_data.export.objects.body_density import (
    BodyDensity,
    bundle_fields,
    density_of,
    mean_density,
)
from space_map_data.export.objects.body_mass import BodyMass, BodyMasses, Satellite
from space_map_data.export.objects.body_radius import BodyRadii, BodyRadius
from space_map_data.models.object import Object, ObjectType

# A 10 km sphere of this many kg is 1 g/cm³.
_ONE_G_CM3_KG = 4 / 3 * math.pi * 1e6 * 1e9 * 1e3 / 1e3


def _sphere(radius_km: float, nominal: bool = False) -> BodyRadius:
    return BodyRadius(radius_km, radius_km, radius_km, "pck", nominal=nominal)


class TestMeanDensity:
    """The shown mass over the volume of the shown ellipsoid."""

    def test_one_gram_per_cubic_centimetre(self):
        density = mean_density(BodyMass(_ONE_G_CM3_KG, "sbdb"), _sphere(10.0))
        assert density == BodyDensity(1.0, False)

    def test_the_volume_is_that_of_the_shown_ellipsoid(self):
        """Eros: 17 x 5.5 x 5.5 km, not a sphere of the 9.33 km mean."""
        eros = BodyRadius(17.0, 5.5, 5.5, "pck")
        density = mean_density(BodyMass(_ONE_G_CM3_KG, "sbdb"), eros)
        assert density is not None
        assert density.g_cm3 == pytest.approx(1000 / (17.0 * 5.5 * 5.5), rel=1e-3)

    def test_a_shape_model_volume_replaces_the_ellipsoid(self):
        """Eros: 2503 km³, where the 17 x 5.5 x 5.5 km ellipsoid holds 2154."""
        reference = {"title": "A shape paper", "url": "https://doi.org/10.1/x"}
        eros = BodyRadius(
            17.0, 5.5, 5.5, "pck", volume_km3=2503.0, volume_reference=reference
        )
        density = mean_density(BodyMass(6.687e15, "pck"), eros)
        assert density == BodyDensity(2.672, False, (reference,))

    def test_a_shape_model_volume_is_measured_under_a_nominal_size(self):
        size = BodyRadius(10.0, 10.0, 10.0, "pck", nominal=True, volume_km3=4188.79)
        density = mean_density(BodyMass(_ONE_G_CM3_KG, "pck"), size)
        assert density == BodyDensity(1.0, False)

    def test_a_satellite_adds_its_shape_model_volume(self):
        mass = BodyMass(2 * _ONE_G_CM3_KG, "johnston", system=True)
        moon = BodyRadius(1.0, 1.0, 1.0, "pck", volume_km3=4 / 3 * math.pi * 1000)
        assert mean_density(mass, _sphere(10.0), [moon]) == BodyDensity(1.0, False)

    def test_the_papers_of_every_volume_are_cited_once(self):
        """Didymos and Dimorphos: a system mass over the volumes of two papers."""
        barnouin = {"title": "Barnouin", "url": "https://doi.org/10.1/b"}
        daly = {"title": "Daly", "url": "https://doi.org/10.1/d"}
        didymos = _sphere(10.0)._replace(volume_km3=1.0, volume_reference=barnouin)
        dimorphos = _sphere(1.0)._replace(volume_km3=1.0, volume_reference=daly)
        mass = BodyMass(1e15, "pck", system=True)
        density = mean_density(mass, didymos, [dimorphos, dimorphos])
        assert density is not None
        assert density.volume_references == (barnouin, daly)

    def test_four_significant_digits(self):
        density = mean_density(
            BodyMass(_ONE_G_CM3_KG * 1.234567, "sbdb"), _sphere(10.0)
        )
        assert density is not None and density.g_cm3 == 1.235

    @pytest.mark.parametrize(
        ("mass_nominal", "radius_nominal"), [(True, False), (False, True), (True, True)]
    )
    def test_nominal_from_either_input(self, mass_nominal, radius_nominal):
        density = mean_density(
            BodyMass(_ONE_G_CM3_KG, "pck", mass_nominal), _sphere(10.0, radius_nominal)
        )
        assert density is not None and density.nominal

    def test_an_extreme_density_is_kept(self):
        """No range check: a 1 km placeholder sphere for a 1e17 kg body."""
        density = mean_density(BodyMass(1e17, "wikidata"), _sphere(1.0, nominal=True))
        assert density is not None and density.g_cm3 > 1000

    @pytest.mark.parametrize(
        ("mass", "size"),
        [
            (None, _sphere(10.0)),
            (BodyMass(1.0, "sbdb"), None),
            (BodyMass(1.0, "sbdb"), _sphere(0.0)),
        ],
    )
    def test_no_density_without_both(self, mass, size):
        assert mean_density(mass, size) is None


class TestSystemMass:
    """A system mass is over the volume of the body and its satellites."""

    def test_the_satellites_add_their_volume(self):
        mass = BodyMass(2 * _ONE_G_CM3_KG, "astersat", system=True)
        density = mean_density(mass, _sphere(10.0), [_sphere(10.0)])
        assert density == BodyDensity(1.0, False)

    def test_a_satellite_without_a_size_is_nominal(self):
        mass = BodyMass(_ONE_G_CM3_KG, "johnston", system=True)
        assert mean_density(mass, _sphere(10.0), [None]) == BodyDensity(1.0, True)

    def test_a_nominal_satellite_size_is_nominal(self):
        mass = BodyMass(2 * _ONE_G_CM3_KG, "johnston", system=True)
        density = mean_density(mass, _sphere(10.0), [_sphere(10.0, nominal=True)])
        assert density == BodyDensity(1.0, True)


def _didymos_density(mass: BodyMass, with_moon: bool = True) -> BodyDensity | None:
    """Didymos and Dimorphos as two 10 km spheres."""
    didymos = Object(id="spkid-20065803", naif_id=2065803, object_type="asteroid")
    moons = {
        "spkid-20065803": (
            Satellite("spkid-120065803", 120065803, None, ObjectType.moon),
        )
    }
    radii = BodyRadii({2065803: _sphere(10.0), 120065803: _sphere(10.0)})
    return density_of(
        didymos,
        mass,
        _sphere(10.0),
        BodyMasses(satellites=moons if with_moon else {}),
        radii,
    )


class TestDensityOf:
    """The satellites count only for a system mass."""

    def test_a_system_mass(self):
        mass = BodyMass(2 * _ONE_G_CM3_KG, "pck", system=True)
        assert _didymos_density(mass) == BodyDensity(1.0, False)

    def test_a_body_mass(self):
        mass = BodyMass(_ONE_G_CM3_KG, "sbdb")
        assert _didymos_density(mass) == BodyDensity(1.0, False)

    def test_a_system_with_no_moon_in_the_export_is_nominal(self):
        """2003 QR91: a Johnston system mass, and no moon object."""
        mass = BodyMass(_ONE_G_CM3_KG, "johnston", system=True)
        assert _didymos_density(mass, with_moon=False) == BodyDensity(1.0, True)


class TestBundleFields:
    def test_a_measured_density(self):
        assert bundle_fields(BodyDensity(2.52, False)) == {"mean_density_g_cm3": 2.52}

    def test_a_nominal_density(self):
        assert bundle_fields(BodyDensity(0.9, True)) == {
            "mean_density_g_cm3": 0.9,
            "mean_density_nominal": True,
        }

    def test_the_paper_of_the_volume(self):
        reference = {"title": "A shape paper", "url": "https://doi.org/10.1/x"}
        assert bundle_fields(BodyDensity(2.67, False, (reference,))) == {
            "mean_density_g_cm3": 2.67,
            "mean_density_volume_references": [reference],
        }

    def test_no_density_writes_nothing(self):
        assert bundle_fields(None) == {}
