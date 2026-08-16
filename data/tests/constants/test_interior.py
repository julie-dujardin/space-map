"""Interior facts: table invariants, and the rules that pick which table row
answers for a reported taxonomic class."""

import pytest

from space_map_data.constants.interior.bodies import INTERIOR_FACTS
from space_map_data.constants.interior.references import INTERIOR_SOURCES
from space_map_data.constants.interior.schema import (
    LAYER_ROLES,
    MATERIALS,
    NOTES,
    PHASES,
    ROCKS,
    SILICATE,
    STATES,
    STRUCTURES,
)
from space_map_data.constants.interior.taxonomy import (
    TAXONOMY_COMPOSITION,
    resolve_class,
)

BODY_IDS = sorted(INTERIOR_FACTS)
CLASSES = sorted(TAXONOMY_COMPOSITION)


def _source_keys() -> set[str]:
    keys: set[str] = set()
    for body in INTERIOR_FACTS.values():
        if body.structure_source:
            keys.add(body.structure_source)
        keys |= set(body.centre_temperature_sources)
        for layer in body.layers:
            keys.add(layer.source)
            if layer.density_source:
                keys.add(layer.density_source)
            if layer.state_source:
                keys.add(layer.state_source)
            if layer.phase_source:
                keys.add(layer.phase_source)
            if layer.rock_source:
                keys.add(layer.rock_source)
            keys |= {c.source for c in layer.composition}
            keys |= set(layer.temperature_sources)
            if layer.detail:
                keys.add(layer.detail.source)
    for entry in TAXONOMY_COMPOSITION.values():
        keys.add(entry.source)
        keys |= {c.source for c in entry.composition}
    return keys


class TestBodies:
    """Per-body layer models."""

    @pytest.mark.parametrize("object_id", BODY_IDS)
    def test_layer_masses_account_for_the_whole_body(self, object_id: str):
        """Layers not summing to 1 would silently distort the roll-up the
        panel shows. All-or-nothing: partial masses would under-count without
        looking wrong."""
        fractions = [layer.mass_fraction for layer in INTERIOR_FACTS[object_id].layers]
        if all(f is None for f in fractions):
            return
        assert None not in fractions
        assert sum(fractions) == pytest.approx(1.0, abs=0.002)

    @pytest.mark.parametrize("object_id", BODY_IDS)
    def test_an_ocean_note_comes_with_an_ocean_layer(self, object_id: str):
        """Ganymede once shipped labelled "has a subsurface ocean" with a
        solid-ice cross-section — note and layer are the same claim and must
        travel together. "Subsurface" means something covers it, which is
        why Earth's ocean carries no note."""
        body = INTERIOR_FACTS[object_id]
        buried = any(layer.role == "ocean" for layer in body.layers[1:])
        assert buried == (body.note == "subsurface_ocean")

    @pytest.mark.parametrize("object_id", BODY_IDS)
    def test_layers_run_outermost_to_innermost(self, object_id: str):
        """The cross-section draws them in order and never sorts. A layer out
        of sequence would render as a shell inside the one that contains it."""
        radii = [
            layer.outer_radius_km
            for layer in INTERIOR_FACTS[object_id].layers
            if layer.outer_radius_km is not None
        ]
        assert radii == sorted(radii, reverse=True)

    @pytest.mark.parametrize("object_id", BODY_IDS)
    def test_a_partial_layer_covers_part_of_the_surface(self, object_id: str):
        """`area_fraction` marks a patch, not a shell; 1.0 is invalid since
        unset already means full coverage."""
        for layer in INTERIOR_FACTS[object_id].layers:
            if layer.area_fraction is not None:
                assert 0.0 < layer.area_fraction < 1.0, layer.role

    @pytest.mark.parametrize("object_id", BODY_IDS)
    def test_a_patch_carries_its_own_floor(self, object_id: str):
        """A patch's floor isn't the next layer's top — Earth's ocean floor is
        the sea floor, not the continental crust after it. Without this the
        cross-section draws a 41 km deep ocean."""
        for layer in INTERIOR_FACTS[object_id].layers:
            if layer.area_fraction is None:
                continue
            assert layer.base_radius_km is not None, layer.role
            assert layer.outer_radius_km is not None
            assert 0 < layer.base_radius_km < layer.outer_radius_km, layer.role

    @pytest.mark.parametrize("object_id", BODY_IDS)
    def test_crusts_tile_the_whole_surface(self, object_id: str):
        """Earth has two crusts and every point of it stands on one of them.
        A body whose crusts left a gap would be missing a third."""
        crusts = [
            layer
            for layer in INTERIOR_FACTS[object_id].layers
            if layer.role.endswith("crust")
        ]
        if len(crusts) < 2:
            return
        assert all(layer.area_fraction is not None for layer in crusts)
        assert sum(layer.area_fraction for layer in crusts) == pytest.approx(
            1.0, abs=0.01
        )

    @pytest.mark.parametrize("object_id", BODY_IDS)
    def test_vocabularies_are_closed(self, object_id: str):
        body = INTERIOR_FACTS[object_id]
        assert body.structure in STRUCTURES
        assert body.note is None or body.note in NOTES
        for layer in body.layers:
            assert layer.role in LAYER_ROLES
            assert layer.note is None or layer.note in NOTES
            assert layer.state is None or layer.state in STATES
            assert layer.phase is None or layer.phase in PHASES
            assert layer.rock is None or layer.rock in ROCKS
            assert sum(c.fraction for c in layer.composition) == pytest.approx(1.0)
            assert all(c.material in MATERIALS for c in layer.composition)

    @pytest.mark.parametrize("object_id", BODY_IDS)
    def test_a_rock_name_sits_on_rock(self, object_id: str):
        """Rock names are igneous petrology, valid only on silicate layers —
        an ice shell named `basalt` would pass every other check here."""
        for layer in INTERIOR_FACTS[object_id].layers:
            if layer.rock is None:
                continue
            assert [c.material for c in layer.composition] == [SILICATE]
            assert layer.state == "solid"

    @pytest.mark.parametrize("object_id", BODY_IDS)
    def test_published_widths_bracket_the_shipped_value(self, object_id: str):
        """The roll-up uses the point value, the panel draws the range around
        it; a range excluding its own value puts the marker outside its error
        bar."""
        for layer in INTERIOR_FACTS[object_id].layers:
            if layer.mass_fraction_range:
                assert layer.mass_fraction is not None
                lo, hi = layer.mass_fraction_range
                assert lo <= layer.mass_fraction <= hi
                assert lo < hi
            for component in layer.composition:
                if component.fraction_range:
                    lo, hi = component.fraction_range
                    assert lo <= component.fraction <= hi
                    assert lo < hi

    @pytest.mark.parametrize("object_id", BODY_IDS)
    def test_layers_run_outermost_first(self, object_id: str):
        """Radii descend, so the frontend can draw them in list order."""
        radii = [
            layer.outer_radius_km
            for layer in INTERIOR_FACTS[object_id].layers
            if layer.outer_radius_km is not None
        ]
        assert radii == sorted(radii, reverse=True)


def _coolest(value: float | None, width: tuple[float, float] | None) -> float | None:
    """The low end of what a boundary might be, for ordering comparisons."""
    if width is not None:
        return width[0]
    return value


class TestBoundaryTemperatures:
    """Temperatures attach to boundaries, not to shells."""

    @pytest.mark.parametrize("object_id", BODY_IDS)
    def test_the_outermost_layer_carries_none(self, object_id: str):
        """Its outer boundary is the surface, which constants/temperature
        measures. Two places holding it would let them drift apart."""
        outermost = INTERIOR_FACTS[object_id].layers[0]
        assert outermost.outer_temperature_k is None
        assert outermost.outer_temperature_range_k is None

    @pytest.mark.parametrize("object_id", BODY_IDS)
    def test_a_temperature_is_cited(self, object_id: str):
        """A number with no work behind it would draw like the rest and credit
        nobody."""
        facts = INTERIOR_FACTS[object_id]
        for layer in facts.layers:
            has = (
                layer.outer_temperature_k is not None
                or layer.outer_temperature_range_k is not None
            )
            assert has == bool(layer.temperature_sources), layer.role
        has_centre = (
            facts.centre_temperature_k is not None
            or facts.centre_temperature_range_k is not None
        )
        assert has_centre == bool(facts.centre_temperature_sources)

    @pytest.mark.parametrize("object_id", BODY_IDS)
    def test_temperatures_descend_outwards(self, object_id: str):
        """Nothing in a planet is cooler than the shell above it, so a stack
        that warms outwards is a boundary attached to the wrong layer."""
        facts = INTERIOR_FACTS[object_id]
        known = [
            low
            for layer in facts.layers
            if (
                low := _coolest(
                    layer.outer_temperature_k, layer.outer_temperature_range_k
                )
            )
            is not None
        ]
        assert known == sorted(known)
        centre = _coolest(facts.centre_temperature_k, facts.centre_temperature_range_k)
        if known and centre is not None:
            assert centre >= known[-1]


class TestTaxonomy:
    """Class-to-analogue table."""

    @pytest.mark.parametrize("taxonomic_class", CLASSES)
    def test_composition_is_whole(self, taxonomic_class: str):
        entry = TAXONOMY_COMPOSITION[taxonomic_class]
        assert sum(c.fraction for c in entry.composition) == pytest.approx(1.0)
        assert all(c.material in MATERIALS for c in entry.composition)

    def test_metal_types_are_not_pure_iron(self):
        """M-types read as solid iron but aren't: the best analogue carries
        silicate inclusions, so claiming pure iron overstates the spectrum."""
        metal = dict(
            (c.material, c.fraction) for c in TAXONOMY_COMPOSITION["M"].composition
        )
        assert metal["silicate"] > 0.1


class TestSources:
    def test_every_cited_key_resolves(self):
        assert not _source_keys() - set(INTERIOR_SOURCES)

    def test_no_unused_references(self):
        """A reference nothing cites is either a dead entry or a value that
        lost its citation in an edit."""
        assert not set(INTERIOR_SOURCES) - _source_keys()


class TestResolveClass:
    """Which row answers for a reported class."""

    def test_direct_hit(self):
        assert resolve_class("S", "S", None) == ("S", False)

    @pytest.mark.parametrize(
        "albedo,expected",
        [(0.05, None), (0.10, "M"), (0.25, "M"), (0.31, "E"), (0.60, "E")],
    )
    def test_x_complex_splits_on_albedo(self, albedo: float, expected: str | None):
        resolved = resolve_class("X", "X", albedo)
        assert (resolved.key if resolved else None) == expected
        # The split is our reading of the albedo, so it owes Mahlke a credit
        # the reported class does not.
        assert resolved is None or resolved.from_albedo_split

    def test_x_without_albedo_is_unanswerable(self):
        """Three different rocks share the X spectrum; without albedo there is
        nothing to choose between them."""
        assert resolve_class("X", "X", None) is None

    @pytest.mark.parametrize(
        "reported,expected", [("Kl", "K"), ("Sq", "S"), ("Cgh", "C")]
    )
    def test_lowercase_suffix_defers_to_its_head(self, reported: str, expected: str):
        assert resolve_class(reported, "U", None) == (expected, False)

    @pytest.mark.parametrize("reported", ["LS", "CX", "DL", "XD"])
    def test_two_capitals_are_declined(self, reported: str):
        """An object sitting between two classes is two rocks at once, and
        picking the first letter would be a coin toss dressed as data."""
        assert resolve_class(reported, "U", None) is None

    @pytest.mark.parametrize("reported", ["D", "P"])
    def test_disputed_analogues_stay_absent(self, reported: str):
        """D and P have no settled meteorite analogue — the once-claimed
        Tagish Lake link for D is no longer thought representative. Guards
        against a drive-by addition."""
        assert resolve_class(reported, reported, 0.05) is None
