"""The credits bibliography — one row per work across the four lists."""

from space_map_data.constants.interior.references import INTERIOR_SOURCES
from space_map_data.constants.rings.references import RING_REFERENCES
from space_map_data.constants.temperature.references import TEMPERATURE_SOURCES
from space_map_data.export.credits import (
    _REFERENCE_SECTIONS,
    _atmosphere_references,
    _merge_references,
)


def _sections() -> dict[str, list[dict]]:
    return {
        "atmosphere": _atmosphere_references(),
        "ring": [r._asdict() for r in RING_REFERENCES],
        "interior": [r._asdict() for r in INTERIOR_SOURCES.values()],
        "temperature": [r._asdict() for r in TEMPERATURE_SOURCES.values()],
    }


def _pair(section: str, other: str, contribution: str, other_contribution: str) -> dict:
    empty: dict[str, list[dict]] = {name: [] for name in _REFERENCE_SECTIONS}
    empty[section] = [{"title": "W", "url": "u", "contribution": contribution}]
    empty[other] = [{"title": "W", "url": "u", "contribution": other_contribution}]
    return empty


class TestMergeReferences:
    """A work cited by two constants packages is credited once."""

    def test_every_section_is_merged(self):
        assert set(_REFERENCE_SECTIONS) == set(_sections())

    def test_no_work_ships_twice(self):
        merged = _merge_references(_sections())
        urls = [r["url"] for rows in merged.values() for r in rows]
        assert len(urls) == len(set(urls))

    def test_no_work_is_dropped(self):
        before = {r["url"] for rows in _sections().values() for r in rows}
        merged = _merge_references(_sections())
        assert before == {r["url"] for rows in merged.values() for r in rows}

    def test_the_shorter_list_keeps_the_work(self):
        """The temperature bibliography is twelve entries; without the NSSDCA
        fact sheets it would read as an omission rather than a merge."""
        merged = _merge_references(_sections())
        nssdca = next(
            r for r in merged["temperature"] if r["title"].startswith("NSSDCA")
        )
        assert "reference conditions" in nssdca["contribution"]

    def test_both_contributions_survive(self):
        merged = _merge_references(
            _pair("temperature", "atmosphere", "the temperature", "the pressure")
        )
        assert merged["atmosphere"] == []
        assert (
            merged["temperature"][0]["contribution"] == "the temperature; the pressure"
        )

    def test_a_restated_contribution_is_not_repeated(self):
        merged = _merge_references(
            _pair("temperature", "atmosphere", "the same thing", "the same thing")
        )
        assert merged["temperature"][0]["contribution"] == "the same thing"
