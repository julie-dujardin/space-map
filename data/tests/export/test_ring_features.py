"""Shape of the per-object ring catalogue block."""

import pytest

from space_map_data.constants.rings.catalog import RING_CATALOGS
from space_map_data.constants.rings.wikidata import RING_SYSTEM_PAGES
from space_map_data.export.objects.rings import (
    feature_qids,
    ring_features_block,
    ring_sources_block,
)

MOON_IDS = {"naif-699/Pan": "naif-618", "naif-699/Daphnis": "naif-635"}


@pytest.fixture(scope="module")
def saturn() -> dict[str, dict]:
    block = ring_features_block("naif-699", MOON_IDS)
    assert block is not None
    return block


class TestBlock:
    """What every body's block carries."""

    def test_bodies_without_rings_get_nothing(self):
        assert ring_features_block("naif-399", {}) is None

    @pytest.mark.parametrize("body", sorted(RING_CATALOGS))
    def test_keys_and_their_order_follow_the_catalogue(self, body: str):
        block = ring_features_block(body, {})
        assert block is not None
        assert list(block) == [f.slug for f in RING_CATALOGS[body].features]

    @pytest.mark.parametrize("body", sorted(RING_CATALOGS))
    def test_every_row_can_be_placed_on_the_radial_axis(self, body: str):
        block = ring_features_block(body, {})
        assert block is not None
        for slug, entry in block.items():
            assert entry["mid_radius_km"] > 0, slug
            if "inner_radius_km" in entry:
                assert entry["inner_radius_km"] < entry["outer_radius_km"]

    @pytest.mark.parametrize("body", sorted(RING_CATALOGS))
    def test_parents_resolve_within_the_block(self, body: str):
        # Key order is inner→outer, not parent-before-child (Uranus' ζ
        # extensions sit inside the ζ ring) — a consumer must resolve by `parent`.
        block = ring_features_block(body, {})
        assert block is not None
        for slug, entry in block.items():
            assert entry.get("parent", slug) in block, slug


class TestSystemPages:
    """The "Rings of X" articles feeding the panel blurb and collection-page pictures."""

    def test_pages_name_ringed_bodies(self):
        # Haumea and Quaoar lack a ring article in any language, on purpose.
        assert set(RING_SYSTEM_PAGES) <= set(RING_CATALOGS)

    def test_every_giant_has_one(self):
        giants = {b for b in RING_CATALOGS if b.startswith("naif-")}
        assert giants <= set(RING_SYSTEM_PAGES)


class TestSources:
    """The credit line under the panel."""

    def test_bodies_without_rings_get_nothing(self):
        assert ring_sources_block("naif-399") is None

    @pytest.mark.parametrize("body", sorted(RING_CATALOGS))
    def test_every_catalogue_source_is_credited_with_a_link(self, body: str):
        sources = ring_sources_block(body)
        assert sources is not None
        assert [s["url"] for s in sources] == [
            s.url for s in RING_CATALOGS[body].sources
        ]
        assert all(s["title"] and s["organisation"] for s in sources)


class TestSaturn:
    """The body with every field populated."""

    def test_boundaries_and_derived_width(self, saturn):
        cassini = saturn["cassini-division"]
        assert (cassini["inner_radius_km"], cassini["outer_radius_km"]) == (
            117_500,
            122_050,
        )
        assert cassini["width_km"] == 4_550
        assert cassini["kind"] == "division"

    def test_optical_depth_keeps_the_sources_qualifiers(self, saturn):
        assert saturn["encke-gap"]["optical_depth"] == {"low": 0.0, "approximate": True}
        assert saturn["c-ring"]["optical_depth"] == {"low": 0.05, "high": 0.35}

    def test_radius_only_features_ship_no_span(self, saturn):
        methone = saturn["methone-ring"]
        assert methone["mid_radius_km"] == 194_440
        assert methone["radius_approximate"] is True
        assert "inner_radius_km" not in methone
        assert "width_km" not in methone

    def test_associated_moons_link_when_resolved(self, saturn):
        assert saturn["encke-gap"]["moons"] == [{"name": "Pan", "id": "naif-618"}]
        # Unresolved moons still ship their name, without a link.
        assert saturn["e-ring"]["moons"] == [{"name": "Enceladus"}]

    def test_pds_note_rides_the_global_block(self, saturn):
        assert saturn["keeler-gap"]["note"].startswith("A narrow gap in the outer A")

    def test_wikidata_qid_matches_the_page_table(self, saturn):
        assert (
            saturn["cassini-division"]["wikidata_qid"]
            == feature_qids("naif-699", "cassini-division")[0]
        )
        assert "wikidata_qid" not in saturn["region-b3"]
