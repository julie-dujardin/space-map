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

    def test_no_layer_has_a_mass(self, key):
        """The layer masses are all or none, and no paper gives all."""
        assert all(layer.mass_fraction is None for layer in STAR_INTERIORS[key].layers)

    def test_a_composition_is_whole_or_absent(self, key):
        for layer in STAR_INTERIORS[key].layers:
            if layer.composition:
                total = sum(c.fraction for c in layer.composition)
                assert total == pytest.approx(1.0), layer.role
                assert all(c.fraction >= 0 for c in layer.composition)

    def test_temperatures_rise_inwards(self, key):
        facts = STAR_INTERIORS[key]
        known = [
            layer.outer_temperature_k
            for layer in facts.layers
            if layer.outer_temperature_k is not None
        ]
        assert facts.layers[0].outer_temperature_k is None
        assert known == sorted(known)
        if known and facts.centre_temperature_k is not None:
            assert facts.centre_temperature_k > known[-1]

    def test_every_layer_says_how_it_was_found(self, key):
        assert all(layer.evidence for layer in STAR_INTERIORS[key].layers)


def test_alpha_cen_a_core_carries_both_sides():
    (core,) = (
        layer
        for layer in STAR_INTERIORS[ALPHA_CEN_A].layers
        if layer.role == "convective_core"
    )
    assert core.standing == "disputed"
    assert set(core.standing_sources) == {"demeulenaer_2010", "nsamba_2018"}


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
