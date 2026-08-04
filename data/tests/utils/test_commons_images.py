"""Tests for space_map_data.utils.commons_images."""

from pathlib import Path

import orjson
import pytest

from space_map_data.utils import commons_images as ci


_FIXTURES = Path(__file__).parent.parent / "export" / "fixtures" / "image_metadata"


def _em_from_fixture(name: str) -> dict:
    data = orjson.loads((_FIXTURES / f"{name}.json").read_bytes())
    return (data.get("imageinfo") or {}).get("extmetadata") or {}


class TestLicenseTagAcceptable:
    """_license_tag_is_acceptable"""

    @pytest.mark.parametrize(
        "tag",
        [
            "Public domain",
            "CC BY 4.0",
            "CC BY 2.5",
            "CC BY-SA 3.0",
            "CC BY-SA 4.0",
            "CC0",
            "GFDL",
            "OGL",
            "Attribution",
        ],
    )
    def test_free_licenses_accepted(self, tag):
        assert ci._license_tag_is_acceptable(tag)

    @pytest.mark.parametrize(
        "tag",
        [
            "Fair use",
            "Non-free media",
            "All rights reserved",
            "CC BY-NC 4.0",
            "CC BY-NC-SA 4.0",
            "CC-BY-NC 2.0",
            "CC BY-ND 3.0",
            "cc by-nd 4.0",
        ],
    )
    def test_restricted_licenses_rejected(self, tag):
        assert not ci._license_tag_is_acceptable(tag)


class TestLicenseIsServableRealData:
    """license_is_servable against real Commons metadata fixtures."""

    @pytest.mark.parametrize(
        "fixture_stem",
        ["pd_asteroid", "cc_by_sa_3", "cc_by_4", "cc_by_sa_4"],
    )
    def test_real_fixtures_pass(self, fixture_stem):
        servable, reason = ci.license_is_servable(_em_from_fixture(fixture_stem))
        assert servable, reason


class TestLicenseIsServableEdgeCases:
    """license_is_servable against fabricated extmetadata."""

    def _em(self, value: str | None) -> dict:
        if value is None:
            return {}
        return {"LicenseShortName": {"value": value}}

    def test_missing_key_drops(self):
        assert ci.license_is_servable({})[0] is False

    def test_empty_string_drops(self):
        assert ci.license_is_servable(self._em(""))[0] is False

    def test_whitespace_only_drops(self):
        assert ci.license_is_servable(self._em("   "))[0] is False

    @pytest.mark.parametrize(
        "license_value",
        [
            "CC BY-NC 4.0",
            "CC BY-NC-SA 4.0",
            "CC BY-ND 3.0",
            "Fair use",
            "Non-free",
            "All rights reserved",
        ],
    )
    def test_restricted_license_drops(self, license_value):
        assert ci.license_is_servable(self._em(license_value))[0] is False

    def test_gfdl_only_drops(self):
        assert ci.license_is_servable(self._em("GFDL"))[0] is False

    def test_gfdl_with_cc_passes(self):
        assert ci.license_is_servable(self._em("CC BY-SA 3.0 or GFDL"))[0] is True
        assert ci.license_is_servable(self._em("GFDL or CC BY-SA 3.0"))[0] is True

    def test_multi_license_with_free_tag_passes(self):
        assert (
            ci.license_is_servable(self._em("CC BY-SA 4.0 or CC BY-SA 3.0 or GFDL"))[0]
            is True
        )

    def test_nc_in_multi_passes_when_free_sibling_present(self):
        assert ci.license_is_servable(self._em("CC BY-NC 4.0 or CC BY 4.0"))[0] is True


class TestCollectQidCommonsFilenames:
    """collect_qid_commons_filenames"""

    @pytest.fixture
    def dirs(self, tmp_path):
        wd = tmp_path / "wikidata"
        wp = tmp_path / "wikipedia"
        wd.mkdir()
        wp.mkdir()
        return wd, wp

    def _write_wd(self, wd_dir: Path, qid: str, p18=(), p154=()) -> None:
        claims: dict[str, list] = {}
        for pid, vals in (("P18", p18), ("P154", p154)):
            if not vals:
                continue
            claims[pid] = [
                {
                    "rank": "normal",
                    "mainsnak": {"datavalue": {"value": v}},
                }
                for v in vals
            ]
        (wd_dir / f"{qid}.json").write_bytes(orjson.dumps({"claims": claims}))

    def _write_wp(self, wp_dir: Path, lang: str, qid: str, source_url: str) -> None:
        lang_dir = wp_dir / lang
        lang_dir.mkdir(exist_ok=True)
        (lang_dir / f"{qid}.json").write_bytes(
            orjson.dumps({"original": {"source": source_url}})
        )

    def test_wikidata_p18_becomes_photo(self, dirs):
        wd, wp = dirs
        self._write_wd(wd, "Q1", p18=["Ceres.jpg"])
        result = ci.collect_qid_commons_filenames("Q1", wikidata_dir=wd, wiki_dir=wp)
        assert result == [{"filename": "Ceres.jpg", "kind": "photo"}]

    def test_wikidata_p154_becomes_logo(self, dirs):
        wd, wp = dirs
        self._write_wd(wd, "Q1", p154=["ESA_logo.png"])
        result = ci.collect_qid_commons_filenames("Q1", wikidata_dir=wd, wiki_dir=wp)
        assert result == [{"filename": "ESA_logo.png", "kind": "logo"}]

    def test_deprecated_claim_dropped(self, dirs):
        wd, wp = dirs
        (wd / "Q1.json").write_bytes(
            orjson.dumps(
                {
                    "claims": {
                        "P18": [
                            {
                                "rank": "deprecated",
                                "mainsnak": {"datavalue": {"value": "Dep.jpg"}},
                            },
                            {
                                "rank": "normal",
                                "mainsnak": {"datavalue": {"value": "Good.jpg"}},
                            },
                        ]
                    }
                }
            )
        )
        result = ci.collect_qid_commons_filenames("Q1", wikidata_dir=wd, wiki_dir=wp)
        assert result == [{"filename": "Good.jpg", "kind": "photo"}]

    def test_wikipedia_commons_pageimage_merged(self, dirs):
        wd, wp = dirs
        self._write_wd(wd, "Q1", p18=["A.jpg"])
        self._write_wp(
            wp,
            "en",
            "Q1",
            "https://upload.wikimedia.org/wikipedia/commons/0/00/B.jpg",
        )
        result = ci.collect_qid_commons_filenames("Q1", wikidata_dir=wd, wiki_dir=wp)
        assert [e["filename"] for e in result] == ["A.jpg", "B.jpg"]
        assert all(e["kind"] == "photo" for e in result)

    def test_wikipedia_non_commons_filtered(self, dirs):
        wd, wp = dirs
        self._write_wd(wd, "Q1")
        self._write_wp(
            wp,
            "ru",
            "Q1",
            "https://upload.wikimedia.org/wikipedia/ru/0/00/local.jpg",
        )
        assert (
            ci.collect_qid_commons_filenames("Q1", wikidata_dir=wd, wiki_dir=wp) == []
        )

    def test_space_form_canonicalized(self, dirs):
        wd, wp = dirs
        self._write_wd(wd, "Q1", p18=["Foo bar.jpg"])
        result = ci.collect_qid_commons_filenames("Q1", wikidata_dir=wd, wiki_dir=wp)
        assert result == [{"filename": "Foo_bar.jpg", "kind": "photo"}]

    def test_dedupes_across_sources_keeping_first_kind(self, dirs):
        wd, wp = dirs
        # P18 lists it as a photo; P154 also claims it — the photo kind wins
        # because P18 is visited first and dedup is by canonical filename.
        self._write_wd(wd, "Q1", p18=["Shared.png"], p154=["Shared.png"])
        result = ci.collect_qid_commons_filenames("Q1", wikidata_dir=wd, wiki_dir=wp)
        assert result == [{"filename": "Shared.png", "kind": "photo"}]

    def test_excluded_prefix_filtered(self, dirs):
        wd, wp = dirs
        self._write_wd(wd, "Q1", p18=["Орбита_астероида_1234.png", "Good.jpg"])
        result = ci.collect_qid_commons_filenames("Q1", wikidata_dir=wd, wiki_dir=wp)
        assert result == [{"filename": "Good.jpg", "kind": "photo"}]

    def test_missing_qid_file_returns_empty(self, dirs):
        wd, wp = dirs
        assert (
            ci.collect_qid_commons_filenames("Q999", wikidata_dir=wd, wiki_dir=wp) == []
        )


class TestParseUploadUrl:
    def test_commons_path(self):
        assert ci.parse_upload_url(
            "https://upload.wikimedia.org/wikipedia/commons/a/ab/Foo.jpg"
        ) == ("commons", "Foo.jpg")

    def test_lang_wiki_path(self):
        assert ci.parse_upload_url(
            "https://upload.wikimedia.org/wikipedia/ru/a/ab/Loc.png"
        ) == ("ru", "Loc.png")

    def test_percent_decoded(self):
        assert ci.parse_upload_url(
            "https://upload.wikimedia.org/wikipedia/commons/a/ab/Foo%20bar.jpg"
        ) == ("commons", "Foo bar.jpg")

    def test_malformed_returns_none(self):
        assert ci.parse_upload_url("https://example.com/not/wiki/here") is None


def _meta_with_categories(*categories: str) -> dict:
    """Minimal download-metadata shaped dict carrying pipe-joined categories."""
    return {
        "imageinfo": {"extmetadata": {"Categories": {"value": "|".join(categories)}}}
    }


class TestImageExclusionReason:
    """image_exclusion_reason — category- and filename-based noise filtering."""

    @pytest.mark.parametrize(
        "filename, categories",
        [
            ("001653_Yakhontovia_-_orbit-viewer-snapshot.png", ["Orbits of asteroids"]),
            ("Juno_orbit_2018.png", ["Orbits of asteroids"]),
            ("1992_TC_orbital_diagram.jpg", []),  # filename token, no category
            ("Foo.png", ["Orbit of Pluto"]),
            ("Bar.gif", ["Animations of minor planet orbits"]),
            ("Baz.png", ["Trajectory of 1I/ʻOumuamua"]),
        ],
    )
    def test_orbit_diagrams(self, filename, categories):
        assert (
            ci.image_exclusion_reason(filename, _meta_with_categories(*categories))
            == "orbit-diagram"
        )

    @pytest.mark.parametrize(
        "filename, categories",
        [
            ("InnerSolarSystem-fr.png", ["Sun in art"]),  # filename family only
            ("EightTNOs-ru.png", ["Russian-language diagrams"]),  # filename family
            ("Solar_System_True_Color_RU.png", ["Solar System object comparisons"]),
            ("Planets2008-ar.jpg", ["Horizontal diagrams of the Solar System (X)"]),
            ("Euler-brouillon.jpg", ["Euler diagram of solar system bodies"]),
        ],
    )
    def test_comparison_diagrams(self, filename, categories):
        assert (
            ci.image_exclusion_reason(filename, _meta_with_categories(*categories))
            == "comparison-diagram"
        )

    @pytest.mark.parametrize(
        "filename, categories",
        [
            # Category alone, in the language the text is baked in — and in
            # English, which is no different.
            ("Neptunian_rings_scheme_ru.png", ["Russian-language diagrams"]),
            ("Neptunian_rings_scheme_2.svg", ["English-language SVG diagrams"]),
            ("Whatever.png", ["Astronomical diagrams"]),
            # Filename alone: uploaders often file these under nothing but the
            # body they draw.
            ("Uranian_rings_scheme.png", ["Uranus (rings)"]),
            ("Anillos_de_Neptuno_esquema.svg", ["Rings of Neptune"]),
            ("Uranian_system_schematic-en.svg", []),
            # A photograph relabelled in one language; its categories are those
            # of the photograph it was drawn over.
            ("Annotated_Uranian_rings.png", ["Images by NIRCam", "PD NASA"]),
        ],
    )
    def test_subject_diagrams(self, filename, categories):
        meta = _meta_with_categories(*categories)
        assert ci.image_exclusion_reason(filename, meta) is None
        assert (
            ci.image_exclusion_reason(filename, meta, drop_subject_diagrams=True)
            == "subject-diagram"
        )

    @pytest.mark.parametrize(
        "filename, categories",
        [
            ("Astro-H_schema_(es).png", ["Spanish-language diagrams"]),
            ("Skylab_diagram.jpg", ["English-language diagrams"]),
            ("Tianwen-1_schematic.png", ["Chinese-language diagrams"]),
        ],
    )
    def test_spacecraft_schematics_survive_where_the_flag_is_off(
        self, filename, categories
    ):
        # The same signals tag a probe's cutaway, which is often the only
        # illustration of it there is — so the flag is off for built things.
        assert (
            ci.image_exclusion_reason(filename, _meta_with_categories(*categories))
            is None
        )

    @pytest.mark.parametrize(
        "filename, categories",
        [
            # Localized spacecraft schematics must NOT be tagged comparison —
            # the broad "<lang>-language diagrams" category is deliberately unused.
            ("Astro-h_schema.jpg", ["ASTRO-H", "French-language diagrams"]),
            ("Astro-H_schema_(en).png", ["ASTRO-H", "English-language diagrams"]),
            ("1090_Sumida_Light_Curve.png", ["Light curves of asteroids"]),
            ("Venus_map.jpg", ["Maps of Venus", "Magellan radar images of Venus"]),
            ("Beidou-coverage.png", ["Locator maps of Asia (gray scheme)"]),
        ],
    )
    def test_kept(self, filename, categories):
        assert (
            ci.image_exclusion_reason(filename, _meta_with_categories(*categories))
            is None
        )

    def test_locator_maps_only_dropped_for_features(self):
        meta = _meta_with_categories("Maps of Mars", "Locator maps")
        # objects/groups keep locator-categorised images (e.g. coverage maps)
        assert ci.image_exclusion_reason("NiliPatera_locator_map.jpg", meta) is None
        # the nomenclature-feature pass drops them
        assert (
            ci.image_exclusion_reason(
                "NiliPatera_locator_map.jpg", meta, drop_locator_maps=True
            )
            == "locator-map"
        )

    def test_none_metadata_falls_back_to_filename(self):
        assert ci.image_exclusion_reason("x_orbit_diagram.png", None) == "orbit-diagram"
        assert ci.image_exclusion_reason("InnerSolarSystem.png", None) == (
            "comparison-diagram"
        )
        assert ci.image_exclusion_reason("Real_photo.jpg", None) is None


class TestIsRadarRender:
    """is_radar_render — small-body radar/shape-model tagging."""

    @pytest.mark.parametrize(
        "category",
        [
            "Radar images of asteroids",
            "Radar images of Near-Earth Objects",
            "Arecibo Telescope Radar Images",
            "Radar-imaged asteroids",
        ],
    )
    def test_small_body_radar_tagged(self, category):
        assert ci.is_radar_render(_meta_with_categories(category))

    @pytest.mark.parametrize(
        "category",
        [
            "Magellan radar images of Venus",  # planetary surface map — keep as photo
            "Cassini radar images of Titan",
            "Photos of asteroids",
        ],
    )
    def test_planetary_and_photos_not_tagged(self, category):
        assert not ci.is_radar_render(_meta_with_categories(category))

    def test_no_metadata(self):
        assert not ci.is_radar_render(None)
