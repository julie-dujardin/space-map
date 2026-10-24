"""Tests for the places where a sky culture names an object."""

from space_map_data.skycultures.refs import (
    ANCHORS,
    CALENDAR,
    FIGURE,
    LINES,
    NAMES,
    Kind,
    Ref,
    bucur_ref,
    collect,
    map_objects,
    stellarium_name,
    stellarium_point,
)


class TestStellariumPoint:
    """A line point is a HIP number, a Gaia source_id or a deep-sky object."""

    def test_integer_is_a_hip_number(self):
        assert stellarium_point(32349) == Ref("32349", Kind.HIP, "32349")

    def test_digit_string_is_a_gaia_source_id(self):
        ref = stellarium_point("5350358584482202880")
        assert (ref.kind, ref.value) == (Kind.GAIA, "5350358584482202880")

    def test_dso_prefix_gives_the_designation(self):
        ref = stellarium_point("DSO:NGC 6530")
        assert (ref.kind, ref.value, ref.text) == (
            Kind.DEEP_SKY,
            "NGC 6530",
            "DSO:NGC 6530",
        )

    def test_other_text_is_unknown(self):
        assert stellarium_point("Polaris").kind == Kind.UNKNOWN


class TestStellariumName:
    """The keys of `common_names` in their published spellings."""

    def test_padded_hip_number(self):
        assert stellarium_name("HIP    746") == Ref("HIP    746", Kind.HIP, "746")

    def test_hip_component_letter(self):
        assert stellarium_name("HIP 72105 B").component == "B"
        assert stellarium_name("HIP 88267A").component == "A"

    def test_gaia_with_trailing_space(self):
        ref = stellarium_name("Gaia DR3 1999551612692096128 ")
        assert (ref.kind, ref.value) == (Kind.GAIA, "1999551612692096128")

    def test_planets_including_commented_ones(self):
        assert stellarium_name("NAME Venus").kind == Kind.SOLAR_SYSTEM
        assert stellarium_name("COMMENTED NAME Uranus").value == "Uranus"

    def test_deep_sky_catalogues(self):
        for key in ("M45", "M  7", "NGC 5139", "PGC17223", "SH2-155", "ACOS373"):
            assert stellarium_name(key).kind == Kind.DEEP_SKY, key

    def test_free_text_is_unknown(self):
        assert stellarium_name("coalsack nebula").kind == Kind.UNKNOWN


class TestBucurRef:
    """Bucur names stars by SIMBAD identifier, planets by NAME."""

    def test_star_keeps_the_identifier_spacing(self):
        assert bucur_ref("*  15 Lyn") == Ref("*  15 Lyn", Kind.SIMBAD, "*  15 Lyn")

    def test_planet_is_solar_system(self):
        assert bucur_ref("NAME Mars").kind == Kind.SOLAR_SYSTEM


CULTURE = {
    "id": "test",
    "region": "Europe",
    "constellations": [
        {
            "id": "CON test A",
            "lines": [[1, 2, [19.4, -23.8]], [2, "DSO:M44"]],
            "lines1": [[3]],
            "hull_extension": [4],
            "image": {"file": "a.png", "anchors": [{"pos": [1, 2], "hip": 1}]},
            "common_name": {"english": "A"},
        }
    ],
    "asterisms": [{"id": "AST test B", "lines": [[5, 6]]}],
    "lunar_system": {"defining_stars": [7], "link": {"star": 8, "offset": 0.0}},
    "zodiac": {"link": {"star": 9}},
    "common_names": {"HIP 1": [{"english": "One"}]},
}


class TestMapObjects:
    """Each object is replaced; every other field stays as published."""

    def test_replaces_objects_and_keeps_positions(self):
        out = map_objects(
            CULTURE,
            stellarium_point,
            stellarium_name,
            lambda ref, place: f"{place}:{ref.value}",
        )
        figure = out["constellations"][0]
        assert figure["lines"] == [
            ["lines:1", "lines:2", [19.4, -23.8]],
            ["lines:2", "lines:M44"],
        ]
        assert figure["lines1"] == [["lines:3"]]
        assert figure["hull_extension"] == ["figure:4"]
        assert figure["image"] == {
            "file": "a.png",
            "anchors": [{"pos": [1, 2], "object": "anchors:1"}],
        }
        assert figure["common_name"] == {"english": "A"}
        assert out["asterisms"][0]["lines"] == [["lines:5", "lines:6"]]
        assert out["lunar_system"] == {
            "defining_stars": ["calendar:7"],
            "link": {"offset": 0.0, "object": "calendar:8"},
        }
        assert out["zodiac"] == {"link": {"object": "calendar:9"}}
        assert out["common_names"] == [
            {"object": "names:1", "names": [{"english": "One"}]}
        ]
        assert out["region"] == "Europe"

    def test_leaves_the_input_unchanged(self):
        before = repr(CULTURE)
        map_objects(CULTURE, stellarium_point, stellarium_name, lambda r, p: 0)
        assert repr(CULTURE) == before

    def test_collect_lists_every_object_with_its_place(self):
        places = [
            place for _, place in collect(CULTURE, stellarium_point, stellarium_name)
        ]
        assert places.count(LINES) == 7
        assert places.count(FIGURE) == 1
        assert places.count(ANCHORS) == 1
        assert places.count(CALENDAR) == 3
        assert places.count(NAMES) == 1
