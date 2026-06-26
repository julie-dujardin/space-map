"""Tests for the launchlog lv_type → launch-vehicle slug mapping and the
constellation → lv- group migration."""

from space_map_data.constants.earth_sats.constellations import (
    CONSTELLATION_BY_SLUG,
    SatelliteCategory,
)
from space_map_data.constants.earth_sats.launch_vehicles import (
    LAUNCH_VEHICLE_BY_QID,
    LAUNCH_VEHICLES,
    match_launch_vehicle_slug,
)
from space_map_data.export.groups.registry import GROUP_BY_SLUG, GroupType


class TestMatchLaunchVehicleSlug:
    """Longest-prefix-wins matching of GCAT lv_type strings to vehicle slugs."""

    def test_basic_family(self):
        assert match_launch_vehicle_slug("Falcon 9") == "falcon"
        assert match_launch_vehicle_slug("Atlas V 551") == "atlas"
        assert match_launch_vehicle_slug("Soyuz-2-1B") == "soyuz-rocket"

    def test_thor_delta_beats_thor(self):
        # "Thor Delta" (longer) wins over "Thor " → delta, not thor-rocket.
        assert match_launch_vehicle_slug("Thor Delta E1") == "delta"
        assert match_launch_vehicle_slug("Thor Agena B") == "thor-rocket"
        assert match_launch_vehicle_slug("Thorad SLV-2G Agena D") == "thor-rocket"

    def test_gslv_mk_iii_is_lvm3(self):
        assert match_launch_vehicle_slug("GSLV Mk III") == "lvm3"
        assert match_launch_vehicle_slug("GSLV Mk II") == "gslv"

    def test_kosmos_variants_split(self):
        assert match_launch_vehicle_slug("Kosmos 11K65M") == "kosmos-3m"
        assert match_launch_vehicle_slug("Kosmos 11K63") == "kosmos-2i"

    def test_chinese_commercial_disambiguation(self):
        # KT-1/KT-2 are Kaituozhe, not Kuaizhou; Gushenxing is Ceres-1;
        # Yinli is Gravity-1; Shuang Quxian is Hyperbola-1.
        assert match_launch_vehicle_slug("KT-1") == "kaituozhe"
        assert match_launch_vehicle_slug("Kuaizhou-1A") == "kuaizhou"
        assert match_launch_vehicle_slug("Gushenxing 1") == "ceres-1"
        assert match_launch_vehicle_slug("Yinli-1") == "gravity-1"
        assert match_launch_vehicle_slug("Shuang Quxian 1") == "hyperbola-1"

    def test_minotaur_c_beats_minotaur(self):
        assert match_launch_vehicle_slug("Minotaur-C 3210") == "taurus-minotaur-c"
        assert match_launch_vehicle_slug("Minotaur IV") == "minotaur"

    def test_launch_only_family(self):
        assert match_launch_vehicle_slug("Space Shuttle") == "space-shuttle"
        assert match_launch_vehicle_slug("Voskhod 11A57") == "voskhod"

    def test_no_match(self):
        assert match_launch_vehicle_slug(None) is None
        assert match_launch_vehicle_slug("") is None
        assert match_launch_vehicle_slug("NOTS EV1") is None


class TestLaunchVehicleRegistry:
    """Spec integrity and the const- → lv- migration invariants."""

    def test_constellation_backed_specs_are_rocket(self):
        for lv in LAUNCH_VEHICLES:
            if lv.constellation_slug is None:
                continue
            spec = CONSTELLATION_BY_SLUG[lv.constellation_slug]
            assert SatelliteCategory.ROCKET in spec.category

    def test_qid_resolves_for_crossref_linking(self):
        # Family QID → spec, so a Wikidata P375 crossref can target the lv- page.
        assert LAUNCH_VEHICLE_BY_QID["Q249091"].slug == "falcon"

    def test_rocket_constellations_migrated_to_lv(self):
        # Falcon emits an lv- group, not a const- one; upper stages stay const-.
        assert "lv-falcon" in GROUP_BY_SLUG
        assert "const-falcon" not in GROUP_BY_SLUG
        assert GROUP_BY_SLUG["lv-falcon"].type is GroupType.LAUNCH_VEHICLE
        assert "const-agena" in GROUP_BY_SLUG  # UPPER_STAGE constellation
