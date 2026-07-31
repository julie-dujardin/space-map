"""Temperature constants, equilibrium estimates, and how the two combine."""

import pytest

from space_map_data.constants.atmosphere.bodies import ATMOSPHERE_BODIES
from space_map_data.constants.temperature.bodies import TEMPERATURE_BODIES
from space_map_data.constants.temperature.cores import CORE_TEMPERATURES
from space_map_data.constants.temperature.references import TEMPERATURE_SOURCES
from space_map_data.export.objects.temperature import (
    CONDITIONS,
    PART_ORDER,
    READING_ORDER,
    bond_albedo,
    equilibrium_temperature,
    heliocentric_distance_au,
    temperature_block,
)

# The bodies whose headline reading is the visible deck rather than a surface.
_GIANTS = ("naif-599", "naif-699", "naif-799", "naif-899")


class TestEquilibriumTemperature:
    """Radiative equilibrium against published values."""

    def test_earth_distance_gives_known_constant(self):
        # The 278-279 K at 1 AU that every published asteroid equilibrium
        # temperature is built on.
        assert equilibrium_temperature(1.0) == pytest.approx(278.3, abs=0.5)

    @pytest.mark.parametrize(
        ("distance_au", "albedo", "expected"),
        [
            (543.72, None, 12.0),  # Sedna
            (43.156, None, 44.0),  # Quaoar
            (1.126, 0.044, 259.0),  # Bennu
            (2.647, 0.016, 171.0),  # 66 Maja
        ],
    )
    def test_matches_published_values(self, distance_au, albedo, expected):
        assert equilibrium_temperature(distance_au, albedo) == pytest.approx(
            expected, abs=3.0
        )

    def test_falls_with_distance(self):
        far, near = equilibrium_temperature(30.0), equilibrium_temperature(1.0)
        assert far is not None and near is not None
        assert far < near

    def test_non_positive_distance_is_dropped(self, caplog):
        assert equilibrium_temperature(0.0) is None
        assert "equilibrium temperature" in caplog.text

    def test_bright_body_is_colder_than_dark_one(self):
        bright = equilibrium_temperature(3.0, 0.6)
        dark = equilibrium_temperature(3.0, 0.02)
        assert bright is not None and dark is not None
        assert bright < dark


class TestBondAlbedo:
    """Geometric-to-Bond conversion and its guards."""

    def test_unknown_albedo_reads_as_zero(self):
        assert bond_albedo(None) == 0.0

    def test_scales_by_phase_integral(self):
        assert bond_albedo(1.0) == pytest.approx(0.39)

    def test_out_of_range_is_rejected_loudly(self, caplog):
        assert bond_albedo(1.4) == 0.0
        assert "out-of-range" in caplog.text


class TestHeliocentricDistance:
    """Which distance drives a body's insolation."""

    def test_planet_uses_its_own_orbit(self):
        assert heliocentric_distance_au(5.203, "naif-10") == 5.203

    def test_moon_uses_its_planet_not_itself(self):
        # Europa's own a is ~0.0045 AU; what matters is Jupiter's 5.2.
        assert heliocentric_distance_au(0.0045, "naif-5") == 5.203

    def test_unknown_parent_gives_nothing(self):
        assert heliocentric_distance_au(0.0045, "naif-599") is None

    def test_hyperbolic_orbit_has_no_characteristic_distance(self):
        assert heliocentric_distance_au(-1899.06, "naif-10") is None


class TestTemperatureBlock:
    """Source precedence and shape."""

    def test_constants_outrank_wikidata(self):
        block = temperature_block(
            "naif-499", [{"part": "surface", "kind": "mean", "k": 999.0}]
        )
        assert block is not None
        assert block["origin"] == "measured"
        assert all(r["k"] != 999.0 for r in block["readings"])
        assert block["sources"]

    def test_wikidata_used_when_no_constant(self):
        block = temperature_block(
            "naif-502", [{"part": "surface", "kind": "mean", "k": 102.0}]
        )
        assert block == {
            "readings": [{"part": "surface", "kind": "mean", "k": 102.0}],
            "origin": "measured",
        }

    def test_equilibrium_is_the_last_resort_and_says_so(self):
        block = temperature_block("spkid-1", [], 2.7, 0.09)
        assert block is not None
        assert block["origin"] == "estimated"
        assert block["readings"][0]["k"] == pytest.approx(166.0, abs=3.0)

    def test_nothing_at_all_yields_no_block(self):
        assert temperature_block("spkid-1", [], None, None) is None

    def test_sources_are_not_repeated(self):
        # Mercury cites NSSDCA from two separate readings.
        block = temperature_block("naif-199")
        assert block is not None
        urls = [s["url"] for s in block["sources"]]
        assert len(urls) == len(set(urls))

    def test_readings_are_ordered_headline_part_first(self):
        block = temperature_block("naif-10")
        assert block is not None
        assert [r["part"] for r in block["readings"]] == ["photosphere", "corona"]

    def test_conditions_survive_to_the_export(self):
        block = temperature_block("naif-199")
        assert block is not None
        by_kind = {r["kind"]: r for r in block["readings"]}
        assert by_kind["min"]["condition"] == "night"
        assert by_kind["max"]["condition"] == "day"
        assert "condition" not in by_kind["mean"]


class TestConstantsIntegrity:
    """Every constant has to be exportable and creditable."""

    @pytest.mark.parametrize("object_id", sorted(TEMPERATURE_BODIES))
    def test_every_body_validates(self, object_id):
        assert temperature_block(object_id) is not None

    def test_every_source_key_resolves(self):
        keys = {
            k for parts in TEMPERATURE_BODIES.values() for p in parts for k in p.sources
        }
        keys |= {k for c in CORE_TEMPERATURES.values() for k in c.sources}
        assert keys <= set(TEMPERATURE_SOURCES)

    def test_no_source_goes_uncited(self):
        used = {
            k for parts in TEMPERATURE_BODIES.values() for p in parts for k in p.sources
        }
        used |= {k for c in CORE_TEMPERATURES.values() for k in c.sources}
        assert set(TEMPERATURE_SOURCES) == used

    def test_enums_are_closed(self):
        for parts in TEMPERATURE_BODIES.values():
            for part in parts:
                assert part.part in PART_ORDER
                for reading in part.readings:
                    assert reading.kind in READING_ORDER
                    assert reading.condition is None or reading.condition in CONDITIONS

    def test_min_never_exceeds_max(self):
        for object_id, parts in TEMPERATURE_BODIES.items():
            for part in parts:
                by_kind = {r.kind: r.kelvin for r in part.readings}
                if "min" in by_kind and "max" in by_kind:
                    assert by_kind["min"] < by_kind["max"], object_id
                if "mean" in by_kind and "max" in by_kind:
                    assert by_kind["mean"] <= by_kind["max"], object_id

    def test_cores_bracket_the_right_way_round(self):
        for object_id, core in CORE_TEMPERATURES.items():
            assert core.low_k < core.high_k, object_id


class TestGiantsAgreeWithTheAtmosphereShell:
    """The cloud-top reading and the rendered atmosphere must cite one level.

    Two blocks on the same panel quoting different temperatures for the same
    deck is the bug this pins shut.
    """

    @pytest.mark.parametrize("object_id", _GIANTS)
    def test_cloud_top_matches_atmosphere_reference(self, object_id):
        parts = TEMPERATURE_BODIES[object_id]
        cloud_top = next(p for p in parts if p.part == "cloud_top")
        mean = next(r for r in cloud_top.readings if r.kind == "mean")
        assert mean.kelvin == ATMOSPHERE_BODIES[object_id].temperature_k

    def test_venus_cloud_top_matches_too(self):
        parts = TEMPERATURE_BODIES["naif-299"]
        cloud_top = next(p for p in parts if p.part == "cloud_top")
        mean = next(r for r in cloud_top.readings if r.kind == "mean")
        assert mean.kelvin == ATMOSPHERE_BODIES["naif-299"].temperature_k
