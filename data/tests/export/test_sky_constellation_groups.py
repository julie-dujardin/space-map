"""Tests for the IAU constellation group pages."""

from unittest.mock import MagicMock

from space_map_data.constants.stars.constellations import (
    MODERN_IAU_CONSTELLATIONS,
    POLISH_CONSTELLATION_NAMES,
    sky_constellation_pages,
    sky_page_culture,
)
from space_map_data.export.extrasolar.skycultures import (
    iau_slug,
    page_labels,
    sky_constellation_names,
)
from space_map_data.export.groups.bundles import _sky_page_parent
from space_map_data.export.groups.registry import GROUP_BY_SLUG, GROUPS, GroupType
from space_map_data.export.localization import _collect_group_name_labels
from space_map_data.export.objects.stars import _ref
from space_map_data.export.wikidata import WikidataEntityCache

ORION = MODERN_IAU_CONSTELLATIONS["orion"][0]


class _Items(WikidataEntityCache):
    """Orion, with its Polish label an article title."""

    def __init__(self) -> None:
        pass

    def get_referenced(self, qid):
        if qid != ORION:
            return None
        return {
            "labels": {
                "en": "Orion",
                "it": "Orione",
                "pl": "Gwiazdozbiór Oriona",
            },
            "aliases": {},
            "sitelinks": {"en": "Orion (constellation)"},
            "claims": {},
        }


def test_a_page_of_another_culture_says_where_it_sits():
    assert sky_page_culture("sky-horn") == "chinese"
    assert sky_page_culture("sky-orion") is None
    assert _sky_page_parent(GROUP_BY_SLUG["sky-horn"]) == "culture-chinese"
    assert _sky_page_parent(GROUP_BY_SLUG["sky-orion"]) == "culture-modern_iau"
    assert (
        _sky_page_parent(GROUP_BY_SLUG["sky-quadrans-muralis"]) == "culture-modern_iau"
    )


def test_each_iau_constellation_has_a_page():
    pages = [g for g in GROUPS if g.type is GroupType.SKY_CONSTELLATION]
    assert len(pages) == 88 + 60
    assert GROUP_BY_SLUG["sky-orion"].wikidata_qid == ORION


def test_a_page_has_the_name_of_its_label_on_the_map():
    names = sky_constellation_names(_Items(), {})
    assert names["sky-orion"].get("en") == "Orion"
    assert names["sky-orion"].get("it") == "Orione"
    assert names["sky-orion"].get("pl") == POLISH_CONSTELLATION_NAMES["orion"]


class _Unnamed(WikidataEntityCache):
    """Items with no English label: one has `mul`, the others no name."""

    def __init__(self) -> None:
        pass

    def get_referenced(self, qid):
        labels = {"mul": "Hu"} if qid == sky_constellation_pages()["horn"] else {}
        return {"labels": labels, "aliases": {}, "sitelinks": {}, "claims": {}}


def test_a_page_with_no_english_label_reads_mul_or_goes():
    labels = page_labels(_Unnamed())
    assert labels["horn"]["en"] == "Hu"
    assert "cerberus" not in labels


def test_the_slug_of_a_latin_name_is_a_page():
    assert f"sky-{iau_slug('Boötes')}" in GROUP_BY_SLUG
    assert f"sky-{iau_slug('Canes Venatici')}" in GROUP_BY_SLUG


def test_a_page_has_no_generated_message():
    entities = MagicMock()
    entities.get_referenced.return_value = None
    assert not any(
        key.startswith("group_name_sky-")
        for key in _collect_group_name_labels(entities)["en"]
    )


def test_a_star_links_to_its_constellation_under_the_page_name():
    ref = _ref(ORION, "pl", _Items(), {})
    assert ref is not None
    assert ref["primary_type"] == "group"
    assert ref["primary_id"] == "sky-orion"
    assert ref["name"] == POLISH_CONSTELLATION_NAMES["orion"]
    assert "wikipedia" not in ref


def test_any_other_item_keeps_its_wikipedia_link():
    class Other(_Items):
        def get_referenced(self, qid):
            return super().get_referenced(ORION)

    ref = _ref("Q1", "en", Other(), {})
    assert ref is not None
    assert "primary_id" not in ref
    assert ref["wikipedia"]
