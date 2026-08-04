"""Per-body atmosphere stat blocks: payload invariants and agreement with the
render constants where the two describe the same level."""

import pytest

from space_map_data.constants.atmosphere.bodies import ATMOSPHERE_BODIES
from space_map_data.constants.atmosphere.facts import (
    ATMOSPHERE_FACTS,
    VOLUME_FRACTION,
    Pressure,
)
from space_map_data.constants.atmosphere.references import ATMOSPHERE_FACT_SOURCES
from space_map_data.constants.atmosphere.structure import ATMOSPHERE_STRUCTURE
from space_map_data.export.objects.atmosphere import atmosphere_block

BODY_IDS = sorted(ATMOSPHERE_FACTS)

# Too thin to draw to scale against the layers below — Earth's exosphere is
# 100× its mesosphere and holds none of its mass. The cross-section caps these
# to a fixed band and puts the real height in the label; the frontend keeps its
# own copy of this list.
_CAPPED = frozenset({"thermosphere", "exosphere", "corona"})


class TestPayload:
    """Shape of the block the object bundles carry."""

    @pytest.mark.parametrize("object_id", BODY_IDS)
    def test_block_builds(self, object_id: str):
        """Enum and citation validation runs for every body, not just the ones
        a smoke test happens to touch."""
        block = atmosphere_block(object_id)
        assert block is not None
        assert block["sources"], f"{object_id} cites nothing"

    @pytest.mark.parametrize("object_id", BODY_IDS)
    def test_shares_normalized_and_ranked(self, object_id: str):
        composition = _block(object_id).get("composition")
        if composition is None:
            return
        shares = [s["share"] for s in composition["species"]]
        assert shares == sorted(shares, reverse=True)
        assert sum(shares) == pytest.approx(1.0, abs=1e-3)

    def test_absent_for_airless_bodies(self):
        assert atmosphere_block("naif-401") is None  # Phobos

    def test_single_species_ships_no_bar(self):
        """Dione has one published density; a lone species would draw a full
        bar of itself."""
        block = _block("naif-604")
        assert "composition" not in block
        assert block["type"] == "exosphere"


class TestStructure:
    """The vertical stack the Structure tab's cross-section draws."""

    @pytest.mark.parametrize("object_id", sorted(ATMOSPHERE_STRUCTURE))
    def test_structure_ships_where_it_exists(self, object_id: str):
        """Every structured body has flat facts too, so none of these stacks
        can be stranded behind an early return."""
        assert "structure" in _block(object_id)

    @pytest.mark.parametrize("object_id", sorted(ATMOSPHERE_STRUCTURE))
    def test_layers_stack_upwards(self, object_id: str):
        """A layer is drawn from the one below's top to its own, so an
        out-of-order height would draw a stratosphere under its troposphere."""
        structure = _block(object_id)["structure"]
        tops = [layer["top_km"] for layer in structure["layers"] if "top_km" in layer]
        assert tops == sorted(tops)

    def test_the_cross_section_has_a_top_to_draw_to(self):
        """The chart runs to scale up to the highest layer that is not one of
        the tenuous outer ones, which are capped to a fixed band with their
        real height in the label. Without that boundary there is no scale to
        draw the rest against."""
        for object_id, structure in (
            (i, _block(i)["structure"]) for i in sorted(ATMOSPHERE_STRUCTURE)
        ):
            lower = [
                layer for layer in structure["layers"] if layer["role"] not in _CAPPED
            ]
            if not lower:
                # Callisto: an exosphere alone, described by how fast it thins.
                assert "scale_height_km" in structure, object_id
                continue
            assert "top_km" in lower[-1], object_id

    def test_every_drawn_stack_has_a_base_temperature(self):
        """The lowest layer's base is the datum, and without a temperature
        there it reads as sitting at its own top — Venus's troposphere at its
        245 K tropopause, under a 737 K surface."""
        for object_id in sorted(ATMOSPHERE_STRUCTURE):
            structure = _block(object_id)["structure"]
            if not [x for x in structure["layers"] if x["role"] not in _CAPPED]:
                continue  # Callisto draws no bands at all
            assert "datum_temperature_k" in structure, object_id

    def test_the_base_is_the_bodys_own_surface_reading(self):
        """Taken from the temperature constants rather than restated here, so
        the Structure tab and the temperature scale cannot disagree."""
        assert _block("naif-299")["structure"]["datum_temperature_k"] == 737.0
        assert _block("naif-10")["structure"]["datum_temperature_k"] == 5772.0

    def test_giants_state_their_own_1_bar_temperature(self):
        """They have no surface to read, so the datum carries a cited value
        and the work behind it joins the block."""
        assert _block("naif-599")["structure"]["datum_temperature_k"] == 165.0
        urls = {s["url"] for s in _block("naif-599")["sources"]}
        assert ATMOSPHERE_FACT_SOURCES["lindal_1992"].url in urls

    def test_a_layer_composition_is_not_renormalized(self):
        """Titan's stratospheric methane is a mixing ratio against the whole
        atmosphere; as a share of the species listed it would be 100%."""
        layers = {
            layer["role"]: layer for layer in _block("naif-606")["structure"]["layers"]
        }
        assert layers["stratosphere"]["species"] == [
            {"formula": "CH4", "value": 0.0148}
        ]

    def test_structure_sources_join_the_block(self):
        """Neptune's exobase height and the temperature defining it come from
        different works, and both are on screen."""
        urls = {s["url"] for s in _block("naif-899")["sources"]}
        assert ATMOSPHERE_FACT_SOURCES["melin_2020"].url in urls
        assert ATMOSPHERE_FACT_SOURCES["broadfoot_1989"].url in urls

    def test_bodies_without_a_named_stack_ship_none(self):
        """Most of the 24 are one pressure and a species list; only twelve have
        layers anyone has named."""
        assert "structure" not in _block("naif-501")  # Io


class TestValues:
    """Spot checks on numbers that were corrected during the source review, so
    a future edit cannot quietly revert them."""

    def test_volume_fractions_sum_near_one(self):
        """A mixing ratio that sums well past 1 means a species was quoted at
        the wrong level or in the wrong unit."""
        for object_id, facts in ATMOSPHERE_FACTS.items():
            if facts.composition_unit != VOLUME_FRACTION or not facts.composition:
                continue
            total = sum(s.value for s in facts.composition)
            assert total <= 1.02, f"{object_id} fractions sum to {total}"

    def test_mercury_sodium_column(self):
        """NSSDCA tabulates columns "in 10^6 per cm2" — the compiled dataset
        this came from read 12,000 as 1.2e11 rather than 1.2e10."""
        sodium = _species("naif-199", "Na")
        assert sodium.value == pytest.approx(1.2e10)

    def test_mercury_helium_is_a_limit(self):
        assert _species("naif-199", "He").upper_limit

    def test_sun_photosphere_pressure(self):
        """125 mb at optical depth 1 — not the 0.868 mb at the photosphere's
        top, which is what the compiled dataset carried."""
        assert _pressure("naif-10").pascals == pytest.approx(1.25e4)

    def test_titan_surface_methane(self):
        """5.65% is the near-surface value that goes with the surface pressure;
        1.48% is the stratosphere."""
        assert _species("naif-606", "CH4").value == pytest.approx(0.0565)

    def test_giants_quote_the_cloud_deck(self):
        for object_id in ("naif-599", "naif-699", "naif-799", "naif-899"):
            pressure = _pressure(object_id)
            assert pressure.level == "cloud_top"
            assert pressure.pascals == pytest.approx(1e4)


class TestAgainstRenderConstants:
    """The two tables state the same atmospheres at different levels; where the
    level is shared they must not disagree, and where they differ it is on
    purpose."""

    # Bodies the two tables deliberately describe differently:
    #   Venus  — rendered from its ~0.1 bar cloud top, quoted at the surface.
    #   Triton — the renderer holds the Voyager epoch, the panel carries the
    #            2009 methane measurement; the atmosphere is seasonal.
    #   Pluto  — the renderer takes NSSDCA's rounded 0.5% CH₄, the panel the
    #            New Horizons UV occultation (Young et al. 2018, ~0.3%).
    NOT_COMPARABLE = {"naif-299", "naif-801", "naif-999"}

    def test_compositions_agree(self):
        for object_id, render in ATMOSPHERE_BODIES.items():
            facts = ATMOSPHERE_FACTS.get(object_id)
            if facts is None or object_id in self.NOT_COMPARABLE:
                continue
            shipped = {s.formula: s.value for s in facts.composition}
            for gas, fraction in render.composition.items():
                assert gas in shipped, f"{object_id} panel is missing {gas}"
                assert shipped[gas] == pytest.approx(fraction, rel=0.02), (
                    f"{object_id} {gas}: panel {shipped[gas]} vs render {fraction}"
                )

    def test_venus_differs_by_level(self):
        """Guards the exemption itself: if these ever converge, the render
        constants stopped describing the cloud top."""
        render = ATMOSPHERE_BODIES["naif-299"]
        assert _pressure("naif-299").pascals > render.pressure_pa * 100


def _block(object_id: str) -> dict:
    block = atmosphere_block(object_id)
    assert block is not None
    return block


def _pressure(object_id: str) -> Pressure:
    pressure = ATMOSPHERE_FACTS[object_id].pressure
    assert pressure is not None
    return pressure


def _species(object_id: str, formula: str):
    return next(
        s for s in ATMOSPHERE_FACTS[object_id].composition if s.formula == formula
    )
