"""Temperature constants, equilibrium estimates, and how the two combine."""

import pytest

from space_map_data.constants.atmosphere.bodies import ATMOSPHERE_BODIES
from space_map_data.constants.temperature.bodies import TEMPERATURE_BODIES
from space_map_data.constants.temperature.references import TEMPERATURE_SOURCES
from space_map_data.export.atmospheres.conditions import render_conditions
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
        assert [r["part"] for r in block["readings"]] == [
            "photosphere",
            "corona",
            "core",
            "core",
        ]

    def test_conditions_survive_to_the_export(self):
        block = temperature_block("naif-199")
        assert block is not None
        # Keyed by part as well as kind: a body with a modelled core has two
        # readings of kind "min", and one of them is not the cold side of
        # Mercury.
        surface = {r["kind"]: r for r in block["readings"] if r["part"] == "surface"}
        assert surface["min"]["condition"] == "night"
        assert surface["max"]["condition"] == "day"
        assert "condition" not in surface["mean"]


class TestModelledCore:
    """Central temperatures ride in `readings` but are drawn elsewhere."""

    def test_core_is_a_bracket_flagged_as_modelled(self):
        block = temperature_block("naif-599")
        assert block is not None
        core = [r for r in block["readings"] if r["part"] == "core"]
        assert [r["kind"] for r in core] == ["min", "max"]
        assert all(r["condition"] == "modelled" for r in core)
        assert core[0]["k"] < core[1]["k"]

    def test_core_sources_join_the_block(self):
        """Jupiter's core cites two works its cloud deck does not."""
        block = temperature_block("naif-599")
        assert block is not None
        assert len(block["sources"]) > 1

    def test_only_a_core_boundary_answers_for_the_core(self):
        """Titan's innermost published temperature is its ice-ocean interface,
        250 K a thousand kilometres above the rock. Reported as a core
        temperature it would be worse than reporting nothing."""
        block = temperature_block("naif-606")
        assert block is not None
        assert all(r["part"] != "core" for r in block["readings"])

    def test_the_bracket_is_the_deepest_boundary_with_a_number(self):
        """Mercury's is its core-mantle boundary, which is what its models
        constrain — the old constant read as a central temperature and was
        never one."""
        block = temperature_block("naif-199")
        assert block is not None
        core = [r["k"] for r in block["readings"] if r["part"] == "core"]
        assert core == [1750.0, 2100.0]

    def test_a_centre_beats_a_boundary(self):
        """The Sun has both; the centre is the deeper of the two."""
        block = temperature_block("naif-10")
        assert block is not None
        core = [r["k"] for r in block["readings"] if r["part"] == "core"]
        assert core == [15.5e6, 15.7e6]

    def test_core_does_not_claim_the_outside_was_measured(self):
        """An estimated surface stays estimated when a modelled core joins it —
        the origin describes the readings the bar draws, not the core."""
        block = temperature_block("spkid-1", None, 2.77, 0.09)
        assert block is not None
        assert block["origin"] == "estimated"


class TestConstantsIntegrity:
    """Every constant has to be exportable and creditable."""

    @pytest.mark.parametrize("object_id", sorted(TEMPERATURE_BODIES))
    def test_every_body_validates(self, object_id):
        assert temperature_block(object_id) is not None

    def test_every_source_key_resolves(self):
        keys = {
            k for parts in TEMPERATURE_BODIES.values() for p in parts for k in p.sources
        }
        assert keys <= set(TEMPERATURE_SOURCES)

    def test_no_source_goes_uncited(self):
        used = {
            k for parts in TEMPERATURE_BODIES.values() for p in parts for k in p.sources
        }
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


class TestTheShellReadsTheMeasurement:
    """The shell no longer keeps its own copy of a body's temperature, so what
    is left to check is that it resolves to the reading the panel shows and
    that the two overrides are earned.

    Giants and Venus are read at their cloud top, everything else at its
    surface.
    """

    # Overridden because the render needs a different quantity, not a second
    # opinion on the same one:
    #   Mars  — the isothermal temperature reproducing NSSDCA's published
    #           11.1 km scale height, against the sheet's 210 K average.
    #   Pluto — REX's near-surface air, against the surface-ice mean.
    DIFFERENT_QUANTITY = {"naif-499", "naif-999"}

    @pytest.mark.parametrize(
        "object_id", sorted(set(ATMOSPHERE_BODIES) & set(TEMPERATURE_BODIES))
    )
    def test_the_shell_resolves_to_the_headline_reading(self, object_id):
        body = ATMOSPHERE_BODIES[object_id]
        expected = body.temperature_k or _headline(object_id)
        assert render_conditions(object_id, body).temperature_k == expected

    def test_only_the_documented_two_override_it(self):
        """A third override appearing without a reason beside it is the drift
        this table was flattened to prevent."""
        overridden = {o for o, b in ATMOSPHERE_BODIES.items() if b.temperature_k}
        assert overridden == self.DIFFERENT_QUANTITY

    @pytest.mark.parametrize("object_id", sorted(DIFFERENT_QUANTITY))
    def test_an_override_is_a_real_difference(self, object_id):
        """An override equal to the panel's number is just a second copy."""
        assert ATMOSPHERE_BODIES[object_id].temperature_k != _headline(object_id)

    @pytest.mark.parametrize("object_id", _GIANTS)
    def test_a_giant_is_read_at_its_deck(self, object_id):
        """The resolver falls back to a surface reading, and a giant has none;
        losing the cloud-top part would strand it rather than fail loudly."""
        assert any(p.part == "cloud_top" for p in TEMPERATURE_BODIES[object_id])


def _headline(object_id: str) -> float | None:
    """The reading the shell renders against — the visible deck where there is
    one, the surface otherwise."""
    means = {
        p.part: next((r.kelvin for r in p.readings if r.kind == "mean"), None)
        for p in TEMPERATURE_BODIES[object_id]
    }
    return means.get("cloud_top") or means.get("surface")
