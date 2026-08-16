"""The radiation block, and the one distinction it exists to keep straight:
which figures are somebody's measurement, which are a model, and which bodies
get no figure because a model would be six orders of magnitude wrong there."""

import pytest

from space_map_data.constants.radiation.environments import RADIATION_ENVIRONMENTS
from space_map_data.export.objects.radiation import radiation_block

EARTH_AU = 1.0
JUPITER_AU = 5.203


def block(
    object_id: str, parent_id: str | None = "naif-10", au: float | None = EARTH_AU
):
    return radiation_block(object_id, parent_id=parent_id, distance_au=au)


class TestPublishedDoses:
    """Where a source gives a figure, the block ships it and never a model."""

    def test_the_moon_keeps_its_measured_surface_dose(self):
        moon = block("naif-301", "naif-399")
        assert moon is not None
        assert moon["surface_dose"]["sv_per_day"]["value"] == pytest.approx(1.369e-3)
        assert "modelled" not in moon["surface_dose"]["sv_per_day"]
        assert "modelled_surface_dose" not in moon

    def test_a_measured_dose_is_never_replaced_by_a_computed_one(self):
        """Mars would model cleanly — thin atmosphere, no field — and RAD is
        still the better answer."""
        mars = block("naif-499", au=1.524)
        assert mars is not None
        assert "modelled_surface_dose" not in mars

    def test_earth_carries_the_ground_and_the_orbit_apart(self):
        """Seven hundred times between them, and the difference is the whole
        point of the atmosphere."""
        earth = block("naif-399")
        assert earth is not None
        ground = earth["surface_dose"]["sv_per_day"]["value"]
        orbit = earth["orbit_dose"]["sv_per_day"]["value"]
        assert orbit / ground > 100

    def test_shielding_travels_with_the_number(self):
        """A dose without the column it was taken behind makes Venus's surface
        and Europa's look like the same kind of claim."""
        venus = block("naif-299", au=0.723)
        assert venus is not None
        assert venus["surface_dose"]["shielding_g_cm2"] > 1e4


class TestModelledDoses:
    """Everywhere the field is answerable, which is everywhere outside a
    magnetosphere."""

    def test_a_body_with_no_entry_at_all_still_gets_a_figure(self):
        """Ceres is in none of the radiation tables, and the point of the model
        is that it does not need to be."""
        ceres = block("naif-2000001", au=2.77)
        assert ceres is not None
        assert ceres["modelled_surface_dose"]["modelled"] is True
        assert ceres["modelled_surface_dose"]["sv_per_day"] > 0

    def test_mercury_is_modelled_despite_having_a_belt(self):
        """Its belt comes and goes with the solar wind and peaks at 93 keV, so
        `kind` says cosmic and cosmic is what decides the dose."""
        mercury = block("naif-199", au=0.387)
        assert mercury is not None
        assert "modelled_surface_dose" in mercury

    def test_the_range_is_the_solar_cycle_not_an_error_bar(self):
        """A factor of about 2.4 end to end, which dwarfs everything else in
        the model and is the reason this ships as a band."""
        modelled = block("naif-2000001", au=2.77)["modelled_surface_dose"]
        low, high = modelled["range"]
        assert high / low == pytest.approx(2.446, rel=0.01)
        assert low < modelled["sv_per_day"] < high

    def test_further_out_is_worse(self):
        """The radial gradient, which is the only thing separating two
        identical airless rocks."""
        inner = block("naif-2000001", au=2.0)["modelled_surface_dose"]
        outer = block("naif-2000001", au=8.0)["modelled_surface_dose"]
        assert outer["sv_per_day"] > inner["sv_per_day"]

    def test_past_the_fitted_range_it_says_so(self):
        """Pluto rests on a gradient continued four times past the data behind
        it. Shipping that silently would be the dishonest part, not shipping
        it."""
        assert (
            "extrapolated" not in block("naif-2000001", au=5.0)["modelled_surface_dose"]
        )
        assert block("naif-999", au=39.48)["modelled_surface_dose"]["extrapolated"]

    def test_an_unknown_distance_yields_no_figure(self):
        assert block("naif-2000001", au=None) is None


class TestMagnetospheres:
    """The exclusion that keeps the table from inverting."""

    @pytest.mark.parametrize("object_id", ["naif-501", "naif-503", "naif-504"])
    def test_a_galilean_gets_no_cosmic_ray_figure(self, object_id: str):
        """Europa's published dose is a million times what the field returns
        for it, so a field figure on Io would rank it below Callisto."""
        moon = block(object_id, "naif-599", JUPITER_AU)
        assert moon is not None
        assert "modelled_surface_dose" not in moon

    def test_a_moon_of_a_belted_planet_is_excluded_by_its_parent(self):
        """Titan has no entry saying trapped — it is `shielded` — and is still
        excluded, because Saturn is what it orbits."""
        titan = block("naif-606", "naif-699", 9.537)
        assert titan is not None
        assert titan["kind"] == "shielded"
        assert "modelled_surface_dose" not in titan

    def test_every_trapped_body_is_excluded(self):
        for object_id, environment in RADIATION_ENVIRONMENTS.items():
            if environment.kind != "trapped":
                continue
            built = block(object_id, "naif-10", JUPITER_AU)
            assert built is not None
            assert "modelled_surface_dose" not in built, object_id


class TestCitations:
    """A figure with nothing behind it is the failure this whole package is
    arranged to prevent."""

    def test_a_modelled_figure_cites_the_model(self):
        ceres = block("naif-2000001", au=2.77)
        assert ceres["sources"]
        assert all(row["title"] and row["url"] for row in ceres["sources"])

    def test_a_body_with_nothing_to_say_has_no_block(self):
        assert block("naif-9999999", au=None) is None
