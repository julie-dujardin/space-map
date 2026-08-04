"""Interior facts: table invariants, and the rules that pick which table row
answers for a reported taxonomic class."""

import pytest

from space_map_data.constants.interior.bodies import INTERIOR_FACTS
from space_map_data.constants.interior.references import INTERIOR_SOURCES
from space_map_data.constants.interior.schema import (
    LAYER_ROLES,
    MATERIALS,
    NOTES,
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
        for layer in body.layers:
            keys.add(layer.source)
            if layer.state_source:
                keys.add(layer.state_source)
            keys |= {c.source for c in layer.composition}
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
        """A body whose layers do not sum to its mass would silently distort
        the roll-up, which is the one number the panel shows. A body whose
        source gives geometry but no masses is allowed to carry none at all —
        but not some, which would under-count without ever looking wrong."""
        fractions = [layer.mass_fraction for layer in INTERIOR_FACTS[object_id].layers]
        if all(f is None for f in fractions):
            return
        assert None not in fractions
        assert sum(fractions) == pytest.approx(1.0, abs=0.002)

    @pytest.mark.parametrize("object_id", BODY_IDS)
    def test_an_ocean_note_comes_with_an_ocean_layer(self, object_id: str):
        """Ganymede shipped for a while as a body labelled "has a subsurface
        ocean" whose cross-section was solid ice from the surface to the rock.
        The note and the layer are the same claim and have to travel together,
        in both directions."""
        body = INTERIOR_FACTS[object_id]
        has_layer = any(layer.role == "ocean" for layer in body.layers)
        assert has_layer == (body.note == "subsurface_ocean")

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
    def test_vocabularies_are_closed(self, object_id: str):
        body = INTERIOR_FACTS[object_id]
        assert body.structure in STRUCTURES
        assert body.note is None or body.note in NOTES
        for layer in body.layers:
            assert layer.role in LAYER_ROLES
            assert layer.note is None or layer.note in NOTES
            assert layer.state is None or layer.state in STATES
            assert sum(c.fraction for c in layer.composition) == pytest.approx(1.0)
            assert all(c.material in MATERIALS for c in layer.composition)

    @pytest.mark.parametrize("object_id", BODY_IDS)
    def test_published_widths_bracket_the_shipped_value(self, object_id: str):
        """The point value is what the roll-up uses and the range is what the
        panel draws around it, so a range that does not contain its own value
        would put the marker outside its own error bar."""
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


class TestTaxonomy:
    """Class-to-analogue table."""

    @pytest.mark.parametrize("taxonomic_class", CLASSES)
    def test_composition_is_whole(self, taxonomic_class: str):
        entry = TAXONOMY_COMPOSITION[taxonomic_class]
        assert sum(c.fraction for c in entry.composition) == pytest.approx(1.0)
        assert all(c.material in MATERIALS for c in entry.composition)

    def test_metal_types_are_not_pure_iron(self):
        """M-types read as solid iron to the eye but are not: the population's
        best analogue carries silicate inclusions, and saying otherwise would
        overstate what a spectrum can tell us."""
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
        """D and P have no settled meteorite analogue — the Tagish Lake link
        that once carried D is no longer thought representative. This test
        exists so adding one is a deliberate act, not a drive-by."""
        assert resolve_class(reported, reported, 0.05) is None
