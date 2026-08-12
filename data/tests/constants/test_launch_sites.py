"""Tests for the SATCAT launch-site catalog and its bridge to GCAT."""

from space_map_data.constants.earth_sats.gcat_qids import (
    GCAT_PAD_QIDS,
    GCAT_SITE_QIDS,
)
from space_map_data.constants.earth_sats.launch_sites import (
    LAUNCH_SITE_BY_CODE,
    LAUNCH_SITE_BY_SLUG,
    LAUNCH_SITE_SLUG_PREFIX,
    LAUNCH_SITES,
)
from space_map_data.export.groups.registry import GROUP_BY_SLUG, GroupType


class TestCatalogIntegrity:
    """Codes and slugs are primary keys; every site must reach its group page."""

    def test_codes_and_slugs_unique(self):
        assert len(LAUNCH_SITE_BY_CODE) == len(LAUNCH_SITES)
        assert len(LAUNCH_SITE_BY_SLUG) == len(LAUNCH_SITES)

    def test_every_site_has_a_group(self):
        for spec in LAUNCH_SITES:
            slug = f"{LAUNCH_SITE_SLUG_PREFIX}{spec.slug}"
            assert GROUP_BY_SLUG[slug].type is GroupType.LAUNCH_SITE

    def test_qids_are_wikidata_shaped(self):
        for spec in LAUNCH_SITES:
            if spec.wikidata_qid is not None:
                assert spec.wikidata_qid.startswith("Q")
                assert spec.wikidata_qid[1:].isdigit()


class TestGCATBridge:
    """`gcat_sites` is what gives a site a position, so guard its shape.

    The codes themselves are checked against GCAT at export time (an unknown
    one logs and yields no position); these tests only catch edits that break
    the mapping structurally.
    """

    def test_gcat_codes_are_not_reused_across_sites(self):
        # Svobodnyy and Vostochny are the deliberate exception: GCAT files the
        # cosmodrome under the missile base it was built on.
        seen: dict[str, str] = {}
        shared = {"svobodnyy", "vostochny"}
        for spec in LAUNCH_SITES:
            for code in spec.gcat_sites:
                other = seen.setdefault(code, spec.slug)
                if other != spec.slug:
                    assert {other, spec.slug} == shared, (
                        f"GCAT site {code} claimed by both {other} and {spec.slug}"
                    )

    def test_only_mobile_and_airspace_sites_lack_a_mapping(self):
        unmapped = {s.slug for s in LAUNCH_SITES if not s.gcat_sites}
        assert unmapped == {
            "canaries-airspace",
            "eastern-range-airspace",
            "western-range-airspace",
            "unknown-site",
        }

    def test_no_empty_or_duplicated_codes_within_a_site(self):
        for spec in LAUNCH_SITES:
            assert all(spec.gcat_sites), f"{spec.slug} has a blank GCAT code"
            assert len(set(spec.gcat_sites)) == len(spec.gcat_sites), (
                f"{spec.slug} repeats a GCAT code"
            )


class TestGCATWikidataQIDs:
    """The curated GCAT → Wikidata table, which no property can be checked against."""

    def test_qids_are_wikidata_shaped(self):
        pad_qids = [q for pads in GCAT_PAD_QIDS.values() for q in pads.values()]
        for qid in [*GCAT_SITE_QIDS.values(), *pad_qids]:
            assert qid.startswith("Q")
            assert qid[1:].isdigit()

    def test_a_site_qid_names_one_site(self):
        # Pads may share a QID where GCAT is the finer catalogue, but two
        # places holding one entity means one of them is wrong.
        qids = list(GCAT_SITE_QIDS.values())
        assert len(set(qids)) == len(qids)

    def test_no_entity_is_both_a_site_and_a_pad(self):
        # Wikidata files whole cosmodromes and individual pads under the same
        # classes, so this is the way a range can end up holding one of its
        # own pads.
        pad_qids = {q for pads in GCAT_PAD_QIDS.values() for q in pads.values()}
        assert not pad_qids & set(GCAT_SITE_QIDS.values())
