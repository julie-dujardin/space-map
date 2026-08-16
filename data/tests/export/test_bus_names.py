"""Satellite bus refs must name the bus, never leak its slug.

Most bus entities carry their designation under Wikidata's ``mul`` (same in
every language) rather than ``en``, and a third have no entity at all, so both
the label lookup and the curated fallback are exercised here.
"""

from typing import cast

import pytest

from space_map_data.constants.providers import LANGUAGES
from space_map_data.constants.earth_sats.satellite_models import SATELLITE_BUSES
from space_map_data.export.objects.celestrak import _bus_group_ref
from space_map_data.export.wikidata import (
    WikidataEntity,
    WikidataEntityCache,
    entity_label,
)


def _entity(labels: dict[str, str]) -> WikidataEntity:
    return WikidataEntity(
        labels=labels, descriptions={}, aliases={}, claims={}, sitelinks={}
    )


class _EmptyCache:
    """WikidataEntityCache that knows no entity — the curated-name path."""

    def get_referenced(self, qid: str | None) -> WikidataEntity | None:
        return None


EMPTY_CACHE = cast(WikidataEntityCache, _EmptyCache())


@pytest.mark.parametrize(
    ("labels", "lang", "expected"),
    [
        ({"en": "Boeing 376", "mul": "BSS-376"}, "en", "Boeing 376"),
        ({"en": "Boeing 376", "mul": "BSS-376"}, "fr", "BSS-376"),
        ({"mul": "LM-700"}, "en", "LM-700"),
        ({"mul": "LM-700"}, "ja", "LM-700"),
        ({"en": "Spacebus"}, "fr", "Spacebus"),
        ({}, "en", None),
    ],
)
def test_entity_label_prefers_lang_then_mul(labels, lang, expected):
    assert entity_label(_entity(labels), lang) == expected


def test_bus_ref_falls_back_to_curated_name():
    """A bus whose entity is missing still names itself, not its slug."""
    ref = _bus_group_ref("lm-700", "fr", EMPTY_CACHE)
    assert ref is not None
    assert ref.name == "LM-700"
    assert ref.primary_id == "bus-lm-700"


@pytest.mark.parametrize("bus", SATELLITE_BUSES, ids=lambda b: b.slug)
def test_every_bus_has_a_name_in_every_language(bus):
    """No entity available is the worst case; the curated name must cover it."""
    for lang in LANGUAGES:
        ref = _bus_group_ref(bus.slug, lang, EMPTY_CACHE)
        assert ref is not None
        assert ref.name != bus.slug, f"{bus.slug} has no usable also_known_as"
