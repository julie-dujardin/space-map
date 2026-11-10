"""The credits bibliography — one row per work across the eight lists."""

import orjson

from space_map_data.constants import body_literature
from space_map_data.constants.activity.references import ACTIVITY_SOURCES
from space_map_data.constants.radiation.references import RADIATION_SOURCES
from space_map_data.constants.rings.references import RING_REFERENCES
from space_map_data.constants.spacecraft import SPACECRAFT_SOURCES
from space_map_data.constants.temperature.references import TEMPERATURE_SOURCES
from space_map_data.constants.traverses.references import TRAVERSE_SOURCES
from space_map_data.export.credits import (
    _REFERENCE_SECTIONS,
    _atmosphere_references,
    _build_model_contributors,
    _interior_references,
    _merge_references,
    _orientation_references,
    _star_references,
    write_credits,
)
from space_map_data.export.names import Names, ObjectNames
from tests.conftest import EntityStub
from tests.export.conftest import layers_of


def _sections() -> dict[str, list[dict]]:
    return {
        "atmosphere": _atmosphere_references(),
        "spacecraft": [r._asdict() for r in SPACECRAFT_SOURCES.values()],
        "ring": [r._asdict() for r in RING_REFERENCES],
        "activity": [r._asdict() for r in ACTIVITY_SOURCES.values()],
        "interior": _interior_references(),
        "temperature": [r._asdict() for r in TEMPERATURE_SOURCES.values()],
        "radiation": [r._asdict() for r in RADIATION_SOURCES.values()],
        "traverse": [r._asdict() for r in TRAVERSE_SOURCES.values()],
        "orientation": _orientation_references(),
        "star": _star_references(),
    }


def _pair(section: str, other: str, contribution: str, other_contribution: str) -> dict:
    empty: dict[str, list[dict]] = {name: [] for name in _REFERENCE_SECTIONS}
    empty[section] = [{"title": "W", "url": "u", "contribution": contribution}]
    empty[other] = [{"title": "W", "url": "u", "contribution": other_contribution}]
    return empty


def _cited(values: dict) -> set[str]:
    return {body_literature.REFERENCES[v.reference].url for v in values.values()}


class TestBodyLiteratureReferences:
    def test_the_papers_of_the_body_sizes_are_listed(self):
        rows = [r for r in _orientation_references() if r["contribution"] == "radii"]
        assert {r["url"] for r in rows} == _cited(body_literature.RADII)
        assert len(rows) == len(_cited(body_literature.RADII))

    def test_the_papers_of_the_body_masses_are_listed(self):
        """Lutetia's Pätzold et al. 2011 to Patroclus' Marchis et al. 2006."""
        rows = [r for r in _interior_references() if r["contribution"] == "mass"]
        gms = {**body_literature.GMS, **body_literature.SYSTEM_GMS}
        assert {r["url"] for r in rows} == _cited(gms)
        marchis = body_literature.REFERENCES["marchis_2006"]
        assert {
            "title": marchis.title,
            "url": marchis.url,
            "contribution": "mass",
        } in rows

    def test_the_papers_of_the_body_volumes_are_listed(self):
        """Phobos' Willner et al. 2014 to Dimorphos' Daly et al. 2024."""
        rows = [r for r in _interior_references() if r["contribution"] == "volume"]
        assert {r["url"] for r in rows} == _cited(body_literature.VOLUMES)


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


class TestExtrasolarBuckets:
    """An exoplanet's maps are credited under its host star, with the flag of
    an artist's impression."""

    @staticmethod
    def _meta(bundle: str, type_: str) -> dict:
        return {
            "id": bundle,
            "source": "https://eyes.nasa.gov/apps/exo/",
            "organisation": "NASA",
            "license": "Public domain",
            "attribution": "Artist's impression by NASA/JPL-Caltech.",
            "type": type_,
            "artist_impression": True,
        }

    def _credits(self, session, tmp_path, layers, pages) -> dict:
        names = ObjectNames(EntityStub(), session)
        write_credits(session, names, tmp_path, layers, pages, {}, None, {})
        return orjson.loads((tmp_path / "credits.json").read_bytes())

    def test_one_bucket_per_host(self, session, tmp_path, caplog):
        """A host with no entry has a page too. A planet that is not served
        is left out."""
        pages = {
            "x-5": Names("Host"),
            "x-5-b-1": Names("Host b", {"ja": "ホスト b"}),
            "x-5-b-2": Names("Host c"),
        }
        layers = layers_of(
            {
                "x-5-b-1": self._meta("x-5-b-1", "cylindrical"),
                "x-5-b-2": self._meta("x-5-b-2", "cylindrical"),
                "x-9-b-1": self._meta("x-9-b-1", "cylindrical"),
            },
            glow={"x-5-b-1": self._meta("x-5-b-1_glow", "cylindrical_glow")},
        )
        payload = self._credits(session, tmp_path, layers, pages)
        (bucket,) = payload["systems"]
        assert (bucket["id"], bucket["name"]) == ("x-5", "Host")
        assert [e["body_id"] for e in bucket["textures"]] == ["x-5-b-1", "x-5-b-2"]
        assert bucket["textures"][0]["artist_impression"] is True
        assert bucket["textures"][0]["name"] == "Host b"
        (glow,) = bucket["glow"]
        assert (glow["body_id"], glow["artist_impression"]) == ("x-5-b-1", True)
        assert payload["names"]["ja"] == {"x-5-b-1": "ホスト b"}
        assert "x-9-b-1 is of no served planet" in caplog.text

    def test_a_page_with_no_name_keeps_its_credit(self, session, tmp_path, caplog):
        """The host takes its planet's name, and a planet its page id."""
        pages = {"x-5": None, "x-5-b-1": Names("Host b"), "x-6-b-1": None}
        layers = layers_of(
            {
                "x-5-b-1": self._meta("x-5-b-1", "cylindrical"),
                "x-6-b-1": self._meta("x-6-b-1", "cylindrical"),
            }
        )
        payload = self._credits(session, tmp_path, layers, pages)
        buckets = [(b["id"], b["name"]) for b in payload["systems"]]
        assert buckets == [("x-5", "Host b"), ("x-6", "x-6-b-1")]
        assert "Host page x-5 has no name" in caplog.text
        assert "Planet page x-6-b-1 has no name" in caplog.text
