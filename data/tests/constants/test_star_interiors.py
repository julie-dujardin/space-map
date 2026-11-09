"""Interiors of other stars from papers: table invariants and the export's
own validation of a layer model."""

import numpy as np
import pyarrow.compute as pc
import pytest

from space_map_data.constants.interior.schema import LAYER_ROLES
from space_map_data.constants.interior.stars import STAR_INTERIORS
from space_map_data.export.objects.interior import from_layers
from space_map_data.extrasolar.ids import CELL_MASK
from space_map_data.extrasolar.registry import NoRegistry, Registry, RegistryBusy
from space_map_data.extrasolar.sky import region_of
from space_map_data.extrasolar.tables import METADATA
from space_map_data.utils.paths import REGISTRY_ROOT

KEYS = sorted(STAR_INTERIORS)
ALPHA_CEN_A = ("hip", "2007", "71683")
# The HD number of the star that the comment of each entry names.
HD_NUMBERS = {
    "71683": "128620",
    "71681": "128621",
    "37279": "61421",
    "32349": "48915",
    "86796": "160691",
    "21444": "29248",
    "30324": "44743",
}


def test_the_convective_core_is_not_the_suns_core():
    """A star's mixed core and the Sun's burning region are two sizes, so they
    must stay two roles."""
    assert {"convective_core", "core"} <= LAYER_ROLES


@pytest.mark.parametrize("key", KEYS, ids="/".join)
class TestStarInteriors:
    """Each entry of `constants/interior/stars.py`."""

    def test_the_key_is_a_hip_number(self, key):
        catalogue, release, number = key
        assert (catalogue, release) == ("hip", "2007")
        assert number.isdigit()

    def test_passes_the_exports_validation(self, key):
        block = from_layers("/".join(key), STAR_INTERIORS[key])
        assert block["structure"] == "fluid"
        assert block["sources"]
        assert "composition" not in block

    def test_layers_run_outermost_first(self, key):
        layers = STAR_INTERIORS[key].layers
        assert layers[0].outer_radius_km is not None
        radii = [layer.outer_radius_km for layer in layers if layer.outer_radius_km]
        assert radii == sorted(radii, reverse=True)

    def test_a_layer_mass_is_a_share_of_the_star(self, key):
        """No paper gives every layer a mass, so a star has no roll-up."""
        layers = STAR_INTERIORS[key].layers
        assert any(layer.mass_fraction is None for layer in layers)
        for layer in layers:
            if layer.mass_fraction is not None:
                assert 0.0 < layer.mass_fraction < 1.0, layer.role
            if layer.mass_fraction_range is not None:
                low, high = layer.mass_fraction_range
                assert layer.mass_fraction is not None
                assert low <= layer.mass_fraction <= high, layer.role

    def test_a_composition_is_whole_or_absent(self, key):
        for layer in STAR_INTERIORS[key].layers:
            if layer.composition:
                total = sum(c.fraction for c in layer.composition)
                assert total == pytest.approx(1.0), layer.role
                assert all(c.fraction >= 0 for c in layer.composition)

    def test_the_centre_composition_is_what_the_paper_gives(self, key):
        """X, Y and the rest by difference, or the one fraction alone."""
        centre = STAR_INTERIORS[key].centre_composition
        assert len(centre) in (0, 1, 3)
        total = sum(c.fraction for c in centre)
        if len(centre) == 3:
            assert total == pytest.approx(1.0)
        else:
            assert total < 1.0

    def test_the_centre_is_not_also_on_a_core(self, key):
        """A mixed core holds the centre's abundances. They ship once, at the
        centre."""
        for layer in STAR_INTERIORS[key].layers:
            if layer.role == "convective_core":
                assert not layer.composition

    def test_temperatures_rise_inwards(self, key):
        facts = STAR_INTERIORS[key]
        known = [
            layer.outer_temperature_k
            for layer in facts.layers
            if layer.outer_temperature_k is not None
        ]
        assert known == sorted(known)
        if known and facts.centre_temperature_k is not None:
            assert facts.centre_temperature_k > known[-1]

    def test_the_surface_is_the_papers_teff(self, key):
        """No other table holds the surface temperature of these stars."""
        facts = STAR_INTERIORS[key]
        top = facts.layers[0]
        assert top.outer_temperature_k is not None
        assert top.temperature_sources == (facts.structure_source,)
        if top.outer_temperature_range_k is not None:
            low, high = top.outer_temperature_range_k
            assert low < top.outer_temperature_k < high

    def test_every_layer_says_how_it_was_found(self, key):
        assert all(layer.evidence for layer in STAR_INTERIORS[key].layers)


def test_alpha_cen_a_centre_is_thevenins():
    block = from_layers("/".join(ALPHA_CEN_A), STAR_INTERIORS[ALPHA_CEN_A])
    assert block["centre_density_g_cm3"] == 177.1
    assert [(c["material"], c["share"]) for c in block["centre_composition"]] == [
        ("hydrogen", 0.182),
        ("helium", 0.785),
        ("heavy_elements", 0.033),
    ]


def test_alpha_cen_a_surface_is_the_observed_teff():
    """Thévenin gives no model Teff, so the block has the one that the
    calibration fits."""
    block = from_layers("/".join(ALPHA_CEN_A), STAR_INTERIORS[ALPHA_CEN_A])
    top = block["layers"][0]
    assert top["outer_temperature_k"] == 5790
    assert top["outer_temperature_range_k"] == [5760, 5820]


def test_a_core_mass_ships_without_a_roll_up():
    """Procyon's core mass is Guenther's; the other layers have none."""
    procyon = ("hip", "2007", "37279")
    block = from_layers("/".join(procyon), STAR_INTERIORS[procyon])
    core = block["layers"][-1]
    assert core["mass_fraction"] == 0.123
    assert core["mass_fraction_range"] == [0.115, 0.131]
    assert "composition" not in block


def test_alpha_cen_a_core_carries_both_sides():
    (core,) = (
        layer
        for layer in STAR_INTERIORS[ALPHA_CEN_A].layers
        if layer.role == "convective_core"
    )
    assert core.standing == "disputed"
    assert set(core.standing_sources) == {"demeulenaer_2010", "nsamba_2018"}


@pytest.mark.data
def test_each_key_is_the_star_that_its_comment_names():
    """In the registry, the star of each HIP number has the HD number of its
    comment among its cross-ids."""
    assert sorted(HD_NUMBERS) == sorted(number for _, _, number in KEYS)
    try:
        with Registry(REGISTRY_ROOT).reader() as registry:
            ids = registry.lookup("hip", "2007", list(HD_NUMBERS))
            found = {}
            for hip, id_ in zip(HD_NUMBERS, ids.tolist(), strict=True):
                assert id_, f"HIP {hip} has no live star"
                region = int(region_of(np.array([id_]) & CELL_MASK)[0])
                rows = registry.read_table(METADATA.slug, region, ["id", "cross_ids"])
                assert rows is not None
                (row,) = rows.filter(pc.equal(rows["id"], id_)).to_pylist()
                found[hip] = {
                    cross["catalogue_id"]
                    for cross in row["cross_ids"]
                    if cross["catalogue"] == "hd"
                }
    except (NoRegistry, RegistryBusy) as why:
        pytest.skip(f"no registry to read: {why}")
    assert {hip: HD_NUMBERS[hip] in hd for hip, hd in found.items()} == dict.fromkeys(
        HD_NUMBERS, True
    )
