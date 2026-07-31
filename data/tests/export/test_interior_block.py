"""The interior block: what the roll-up does to a layer model, and which of
the two routes answers for a body."""

import pytest

from space_map_data.constants.interior.bodies import INTERIOR_FACTS
from space_map_data.export.objects.interior import interior_block

# (1) Ceres, C-class, in the spectral table — but Dawn flew there.
CERES = "naif-2000001"
EROS = "spkid-20000433"
EROS_TAXONOMY = {EROS: ("S", "S", "Bus-DeMeo", 0.25)}


def block(object_id: str, taxonomy: dict | None = None) -> dict:
    """`interior_block` for a body that must have one."""
    result = interior_block(object_id, taxonomy or {})
    assert result is not None, object_id
    return result


class TestRollUp:
    """Layer masses summed per material."""

    @pytest.mark.parametrize("object_id", sorted(INTERIOR_FACTS))
    def test_shares_are_whole(self, object_id: str):
        composition = block(object_id).get("composition")
        if composition is None:
            return  # geometry-only body; nothing to normalize
        assert sum(c["share"] for c in composition) == pytest.approx(1.0, abs=0.002)

    @pytest.mark.parametrize("object_id", sorted(INTERIOR_FACTS))
    def test_shares_descend(self, object_id: str):
        """The bar reads most to least abundant, and the frontend trusts the
        order rather than re-sorting."""
        composition = block(object_id).get("composition", [])
        shares = [c["share"] for c in composition]
        assert shares == sorted(shares, reverse=True)

    def test_layers_collapse_onto_one_material(self):
        """The Moon has four layers over two materials; the bar has two bars,
        not four."""
        composition = block("naif-301")["composition"]
        assert [c["material"] for c in composition] == ["silicate", "metal"]

    def test_slivers_are_dropped(self):
        """Tethys is 0.06% rock, which draws as an invisible segment with a
        legend entry of its own."""
        composition = block("naif-603")["composition"]
        assert [c["material"] for c in composition] == ["water"]

    def test_body_without_layer_masses_still_ships(self):
        """The Sun has zone radii and compositions but no masses. It keeps its
        structure and its sources; only the bar goes."""
        result = block("naif-10")
        assert "composition" not in result
        assert result["structure"] == "fluid"
        assert result["sources"]


class TestRoutes:
    def test_layer_model_beats_the_spectrum(self):
        """Ceres is a C-type and would get the carbonaceous-chondrite estimate,
        but Dawn measured it — the measurement has to win."""
        result = block(CERES, {CERES: ("C", "C", "Bus-DeMeo", 0.09)})
        assert "estimated" not in result
        assert result["structure"] == "partially_differentiated"

    def test_spectrum_answers_where_nothing_else_does(self):
        result = block(EROS, EROS_TAXONOMY)
        assert result["estimated"] is True
        assert result["analogue"] == "ordinary_chondrite"
        assert result["taxonomy_class"] == "S"
        # The scheme rides along because a letter means different things under
        # Tholen and Bus-DeMeo.
        assert result["taxonomy_scheme"] == "Bus-DeMeo"

    def test_estimate_never_claims_a_structure(self):
        """A spectrum is a statement about the surface; it says nothing about
        whether the body separated."""
        assert "structure" not in block(EROS, EROS_TAXONOMY)

    def test_unanswerable_class_yields_nothing(self):
        """A dark X-type could be an iron, an enstatite chondrite or a hydrated
        primitive body, and albedo is the only thing that separates them."""
        assert interior_block(EROS, {EROS: ("X", "X", "Tholen", None)}) is None

    def test_body_with_neither_is_absent(self):
        assert interior_block("naif-499999", {}) is None


class TestSources:
    @pytest.mark.parametrize("object_id", sorted(INTERIOR_FACTS))
    def test_every_body_is_credited(self, object_id: str):
        sources = block(object_id)["sources"]
        assert sources
        assert all(s["title"] and s["url"] for s in sources)

    def test_sources_are_deduped(self):
        """Enceladus cites Iess for every layer and every component; the panel
        should list it once."""
        sources = block("naif-602")["sources"]
        assert len(sources) == len({s["url"] for s in sources})
