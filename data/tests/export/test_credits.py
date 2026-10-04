"""The credits bibliography — one row per work across the seven lists."""

from space_map_data.constants.activity.references import ACTIVITY_SOURCES
from space_map_data.constants.interior.references import INTERIOR_SOURCES
from space_map_data.constants.radiation.references import RADIATION_SOURCES
from space_map_data.constants.rings.references import RING_REFERENCES
from space_map_data.constants.spacecraft import SPACECRAFT_SOURCES
from space_map_data.constants.temperature.references import TEMPERATURE_SOURCES
from space_map_data.export.credits import (
    _REFERENCE_SECTIONS,
    _atmosphere_references,
    _build_model_contributors,
    _merge_references,
)


def _sections() -> dict[str, list[dict]]:
    return {
        "atmosphere": _atmosphere_references(),
        "spacecraft": [r._asdict() for r in SPACECRAFT_SOURCES.values()],
        "ring": [r._asdict() for r in RING_REFERENCES],
        "activity": [r._asdict() for r in ACTIVITY_SOURCES.values()],
        "interior": [r._asdict() for r in INTERIOR_SOURCES.values()],
        "temperature": [r._asdict() for r in TEMPERATURE_SOURCES.values()],
        "radiation": [r._asdict() for r in RADIATION_SOURCES.values()],
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

    def test_a_work_cited_by_two_packages_shares_a_url(self):
        """The merge is by URL: the Garrett reports must link the same copy or the
        page lists one twice."""
        merged = _merge_references(_sections())
        garrett = [
            r for rows in merged.values() for r in rows if "Garrett" in r["title"]
        ]
        shared = [r for r in garrett if "dipole" in r["contribution"]]
        assert len(shared) == 2
        assert all("belts" in r["contribution"] for r in shared)
        # The Saturn model is radiation's alone, so it has nothing to merge with
        # and must still appear exactly once.
        solo = [r for r in garrett if "Saturn" in r["title"]]
        assert len(solo) == 1
        assert "dipole" not in solo[0]["contribution"]

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


def _bundle(*credits: dict, catalog: str | None = None) -> dict:
    tiers = [
        {"credit": credit} | ({"catalog": catalog} if catalog else {})
        for credit in credits
    ]
    return {"exports": dict(zip(("high", "low"), tiers))}


class TestModelContributors:
    """Models outside the catalogs are credited once per author."""

    def test_a_catalog_model_is_left_to_the_catalog_list(self):
        bundle = _bundle({"name": "NASA", "url": "u"}, catalog="NASA-3D-Resources")
        assert _build_model_contributors({"a": bundle}) == []

    def test_an_author_with_several_models_gets_one_line(self):
        out = _build_model_contributors(
            {
                "a": _bundle({"name": "ann / Sketchfab", "url": "u1", "license": "L1"}),
                "b": _bundle({"name": "ann / Sketchfab", "url": "u2", "license": "L2"}),
            }
        )
        assert out == [{"name": "ann / Sketchfab", "licenses": ["L1", "L2"]}]

    def test_an_author_with_several_models_links_their_own_page(self):
        name = "tashtego / Sketchfab"
        out = _build_model_contributors(
            {
                "a": _bundle({"name": name, "url": "u1"}),
                "b": _bundle({"name": name, "url": "u2"}),
            }
        )
        assert out[0]["url"] == "https://sketchfab.com/tashtego"

    def test_a_single_source_page_is_linked(self):
        credit = {"name": "ann / Sketchfab", "url": "u1", "license": "L1"}
        out = _build_model_contributors({"a": _bundle(credit, credit)})
        assert out == [{"name": "ann / Sketchfab", "url": "u1", "licenses": ["L1"]}]

    def test_the_note_on_what_was_changed_does_not_split_an_author(self):
        out = _build_model_contributors(
            {
                "a": _bundle({"name": "ann / Sketchfab, painted", "url": "u1"}),
                "b": _bundle({"name": "ann / Sketchfab", "url": "u2"}),
            }
        )
        assert [row["name"] for row in out] == ["ann / Sketchfab"]

    def test_a_second_credited_party_is_kept(self):
        """Without a hosting site the comma joins two parties, not a note."""
        credit = {"name": "EOX IT Services, coastline from OpenStreetMap", "url": "u"}
        out = _build_model_contributors({"a": _bundle(credit)})
        assert out[0]["name"] == credit["name"]
