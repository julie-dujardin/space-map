"""The interior block: what the roll-up does to a layer model, and which of
the three routes answers for a body."""

import pytest

from space_map_data.constants.interior.bodies import INTERIOR_FACTS
from space_map_data.constants.interior.references import INTERIOR_SOURCES
from space_map_data.constants.interior.schema import BodyInterior, Component, Layer
from space_map_data.export.objects.interior import (
    interior_block,
    interior_from_mapping,
)

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


class TestLayers:
    """The stack the Structure tab's cross-section draws."""

    @pytest.mark.parametrize("object_id", sorted(INTERIOR_FACTS))
    def test_radii_descend(self, object_id: str):
        """Layers ship outermost first and the disc is drawn by walking them
        inwards; one out of order would nest a core outside its mantle."""
        radii = [
            layer["outer_radius_km"]
            for layer in block(object_id)["layers"]
            if "outer_radius_km" in layer
        ]
        assert radii == sorted(radii, reverse=True)

    @pytest.mark.parametrize("object_id", sorted(INTERIOR_FACTS))
    def test_every_layer_can_be_drawn(self, object_id: str):
        """A layer with no outer radius has no band to occupy, and the ones
        below it would silently slide outwards to fill the gap."""
        for layer in block(object_id)["layers"]:
            assert "outer_radius_km" in layer, layer["role"]

    def test_a_layer_carries_its_own_composition(self):
        """Europa's ocean is water where the body is mostly rock; the per-layer
        bars are what make that visible."""
        layers = {layer["role"]: layer for layer in block("naif-502")["layers"]}
        assert [c["material"] for c in layers["ocean"]["composition"]] == ["water"]
        assert [c["material"] for c in layers["core"]["composition"]] == ["metal"]

    def test_published_widths_ride_along(self):
        """Europa's core is anywhere from 6.8% to 11.9% of the moon, and a
        single number would read as a measurement."""
        core = next(
            layer for layer in block("naif-502")["layers"] if layer["role"] == "core"
        )
        assert core["mass_fraction_range"] == [0.0681, 0.1185]
        assert core["note"] == "core_size_disputed"

    def test_a_diffuse_layer_says_so(self):
        """Jupiter's core is heavy elements smeared through the envelope, so
        its radius is where it fades out rather than where it ends."""
        core = next(
            layer for layer in block("naif-599")["layers"] if layer["role"] == "core"
        )
        assert core["diffuse"] is True
        assert core["outer_radius_km"] == 35746.0

    def test_chemistry_ships_where_there_is_any(self):
        """Mars's crust has an oxide table behind it; most layers have only the
        coarse material split."""
        crust = next(
            layer for layer in block("naif-499")["layers"] if layer["role"] == "crust"
        )
        assert crust["detail"]["unit"] == "oxide_weight"
        species = [e["species"] for e in crust["detail"]["entries"]]
        assert species[0] == "SiO2"

    def test_a_rock_name_ships_where_the_literature_agrees(self):
        """Earth's two crusts are the case the field exists for: both are
        "solid silicate" and neither is the other's rock."""
        layers = {layer["role"]: layer for layer in block("naif-399")["layers"]}
        assert layers["crust"]["rock"] == "andesite"
        assert layers["oceanic_crust"]["rock"] == "basalt"

    def test_a_contested_layer_ships_none(self):
        """Mercury's crust reads as three different rocks in three papers, and
        an absent name is the honest one."""
        crust = next(
            layer for layer in block("naif-199")["layers"] if layer["role"] == "crust"
        )
        assert "rock" not in crust

    def test_a_rock_from_another_paper_is_credited(self):
        """Mars's crust is 47 km thick because InSight timed a quake and basalt
        because a gamma-ray spectrometer read its chemistry; the panel names
        the rock, so it has to name McSween too."""
        urls = {source["url"] for source in block("naif-499")["sources"]}
        assert "https://doi.org/10.1126/science.1165871" in urls

    def test_a_massless_body_still_has_a_stack(self):
        """The Sun has zone radii but no zone masses, and the cross-section is
        the one thing it can still draw."""
        layers = block("naif-10")["layers"]
        assert [layer["role"] for layer in layers] == [
            "convective_zone",
            "radiative_zone",
            "core",
        ]
        assert all("mass_fraction" not in layer for layer in layers)

    def test_the_estimate_route_has_no_layers(self):
        """A spectrum says nothing about how a body is arranged, and 150,000
        asteroids take this route."""
        assert "layers" not in block(EROS, EROS_TAXONOMY)


class TestBoundaryTemperatures:
    """The temperature at a boundary, where anyone has published one."""

    def test_a_boundary_ships_its_reading(self):
        """Earth's inner-core boundary is the one place in any planet where a
        phase change fixes the temperature, and it ships as value plus width."""
        inner = next(
            layer
            for layer in block("naif-399")["layers"]
            if layer["role"] == "inner_core"
        )
        assert inner["outer_temperature_k"] == 5500.0
        assert inner["outer_temperature_range_k"] == [5000.0, 6000.0]

    def test_a_width_can_be_the_whole_claim(self):
        """Venus's core-mantle boundary is 4000 to 5000 K with nothing between
        preferred, so no point value ships to imply one."""
        core = next(
            layer for layer in block("naif-299")["layers"] if layer["role"] == "core"
        )
        assert core["outer_temperature_range_k"] == [4000.0, 5000.0]
        assert "outer_temperature_k" not in core

    def test_the_centre_rides_on_the_body(self):
        """A dilute core has no radius to hang a boundary on, so Jupiter's only
        temperature is its middle."""
        assert block("naif-599")["centre_temperature_range_k"] == [15000.0, 36000.0]

    def test_a_body_without_one_ships_nothing(self):
        """Most of the thirty-one layer models have no published geotherm, and
        an absent field is how the panel knows to draw no temperature."""
        io = block("naif-501")
        assert "centre_temperature_k" not in io
        assert all("outer_temperature_k" not in layer for layer in io["layers"])

    def test_the_temperature_source_is_credited(self):
        """Gravity sized Mercury's core and Hauck heated it; both are works the
        panel has to name."""
        urls = {source["url"] for source in block("naif-199")["sources"]}
        assert "https://doi.org/10.1002/jgre.20091" in urls


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

    def test_the_class_is_credited_by_id(self):
        """Full citations for 171,000 asteroids would be megabytes of bundle
        for two names that never vary; the frontend resolves these itself."""
        assert block(EROS, EROS_TAXONOMY)["taxonomy_sources"] == ["ssodnet"]

    def test_mahlkes_scheme_is_credited(self):
        assert block(EROS, {EROS: ("S", "S", "Mahlke", 0.25)})["taxonomy_sources"] == [
            "ssodnet",
            "mahlke",
        ]

    def test_the_albedo_split_credits_mahlke_under_any_scheme(self):
        """An X we resolved ourselves is Mahlke's cut whoever reported the
        letter."""
        assert block(EROS, {EROS: ("X", "X", "Bus-DeMeo", 0.25)})[
            "taxonomy_sources"
        ] == ["ssodnet", "mahlke"]

    def test_a_layer_model_credits_no_taxonomy(self):
        """Ganymede's interior is a gravity field; no spectrum went near it."""
        assert "taxonomy_sources" not in block("naif-503")

    def test_a_dropped_material_drops_its_citation(self, monkeypatch):
        """Credit follows the bar. No real body relies on this — every sliver
        we cut is cited elsewhere on the same body — but the panel must not
        credit a work for a segment it never drew."""
        monkeypatch.setitem(
            INTERIOR_FACTS,
            "test-1",
            BodyInterior(
                structure="differentiated",
                structure_source="park_2016",
                layers=(
                    Layer(
                        role="mantle",
                        mass_fraction=1.0,
                        source="park_2016",
                        composition=(
                            Component("silicate", 0.999, "krot_2014"),
                            Component("organic", 0.001, "wasson_1988"),
                        ),
                    ),
                ),
            ),
        )
        result = block("test-1")
        assert [c["material"] for c in result["composition"]] == ["silicate"]
        urls = {s["url"] for s in result["sources"]}
        assert INTERIOR_SOURCES["krot_2014"].url in urls
        assert INTERIOR_SOURCES["wasson_1988"].url not in urls


MAPPED: dict = {
    "structure": "differentiated",
    "sources": {"a": {"title": "A work", "url": "https://example.invalid/a"}},
    "layers": [
        {
            "role": "crust",
            "outer_radius_km": 10.0,
            "mass_fraction": 0.25,
            "state": "solid",
            "source": "a",
            "composition": [{"material": "silicate", "fraction": 1.0, "source": "a"}],
        },
        {
            "role": "core",
            "outer_radius_km": 5.0,
            "mass_fraction": 0.75,
            "source": "a",
            "composition": [{"material": "metal", "fraction": 1.0, "source": "a"}],
        },
    ],
}


def mapped(**overrides) -> dict | None:
    return interior_from_mapping("test-mapped", MAPPED | overrides)


class TestFromMapping:
    """A layer model that arrives as data rather than as a constant, for the
    objects that have no database row to key one off."""

    def test_it_reaches_the_same_shape(self):
        result = mapped()
        assert result is not None
        assert result["structure"] == "differentiated"
        assert result["composition"] == [
            {"material": "metal", "share": 0.75},
            {"material": "silicate", "share": 0.25},
        ]
        assert [layer["role"] for layer in result["layers"]] == ["crust", "core"]
        assert result["layers"][0]["state"] == "solid"

    def test_a_layer_can_carry_a_finer_chemistry(self):
        """Ordered pairs rather than an object, so the drawn order is the
        file's order and not the JSON parser's."""
        result = interior_from_mapping(
            "test-mapped",
            MAPPED
            | {
                "layers": [
                    MAPPED["layers"][0]
                    | {
                        "detail": {
                            "unit": "oxide_weight",
                            "entries": [["SiO2", 0.6], ["Al2O3", 0.4]],
                            "source": "a",
                        }
                    },
                    MAPPED["layers"][1],
                ]
            },
        )
        assert result is not None
        assert result["layers"][0]["detail"]["entries"] == [
            {"species": "SiO2", "fraction": 0.6},
            {"species": "Al2O3", "fraction": 0.4},
        ]

    def test_it_carries_its_own_citations(self):
        """These bodies are not in `references.py`, so the mapping is the only
        place a citation can live."""
        result = mapped()
        assert result is not None
        assert result["sources"] == [
            {"title": "A work", "url": "https://example.invalid/a"}
        ]

    @pytest.mark.parametrize(
        "broken",
        [
            {"structure": "melted"},
            {"layers": [{"role": "crust", "mass_fractionn": 1.0, "source": "a"}]},
            {"centre_temperature_k": 300.0},
            {"sources": {}},
        ],
        ids=["bad-enum", "typo-field", "uncited-temperature", "unknown-source"],
    )
    def test_a_broken_one_costs_only_its_own_panel(self, broken, caplog):
        """The file is hand-edited and outside the repo; a typo there must not
        take the export down with it."""
        assert mapped(**broken) is None
        assert "test-mapped" in caplog.text
