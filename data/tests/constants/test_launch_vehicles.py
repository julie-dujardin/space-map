"""Tests for the launchlog lv_type → launch-vehicle slug mapping and the
constellation → lv- group migration."""

from space_map_data.constants.earth_sats.constellations import (
    CONSTELLATION_BY_SLUG,
    SatelliteCategory,
)
from space_map_data.constants.earth_sats.launch_vehicles import (
    LAUNCH_VEHICLE_BY_QID,
    LAUNCH_VEHICLE_BY_SLUG,
    LAUNCH_VEHICLE_VARIANT_QID,
    LAUNCH_VEHICLES,
    launch_vehicle_slug_for_qid,
    match_launch_vehicle_slug,
)
from space_map_data.export.objects.wikidata_claims import (
    EntityRef,
    attach_launch_vehicle_group_link,
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


class TestLaunchVehicleVariantQid:
    """Variant P375 QIDs resolve to a family lv- page for crossref linking."""

    def test_variant_resolves_to_family(self):
        # A specific configuration points at its family page, not its own QID.
        assert launch_vehicle_slug_for_qid("Q20803939") == "atlas"  # Atlas V 401
        assert launch_vehicle_slug_for_qid("Q28450215") == "falcon"  # Falcon 9 Block 5

    def test_family_qid_still_resolves(self):
        assert launch_vehicle_slug_for_qid("Q249091") == "falcon"  # Falcon 9 family

    def test_unknown_qid_returns_none(self):
        assert launch_vehicle_slug_for_qid("Q0") is None

    def test_every_variant_targets_an_exported_page(self):
        for qid, slug in LAUNCH_VEHICLE_VARIANT_QID.items():
            assert slug in LAUNCH_VEHICLE_BY_SLUG, qid
            assert f"lv-{slug}" in GROUP_BY_SLUG, qid

    def test_variants_disjoint_from_family_qids(self):
        assert not set(LAUNCH_VEHICLE_VARIANT_QID) & set(LAUNCH_VEHICLE_BY_QID)

    def test_attach_repoints_variant_keeping_display_name(self):
        # "Atlas V 401" stays the displayed name; the link targets lv-atlas.
        ref = EntityRef(name="Atlas V 401", wikipedia="https://en.wikipedia.org/wiki/x")
        attach_launch_vehicle_group_link(ref, "Q20803939")
        assert ref.name == "Atlas V 401"
        assert ref.primary_type == "group"
        assert ref.primary_id == "lv-atlas"
        # primary_id set → wikipedia dropped on serialization (drawer opens instead).
        assert "wikipedia" not in ref.to_dict()

    def test_attach_noop_for_unknown(self):
        ref = EntityRef(name="Mystery Rocket")
        attach_launch_vehicle_group_link(ref, "Q0")
        assert ref.primary_id is None
