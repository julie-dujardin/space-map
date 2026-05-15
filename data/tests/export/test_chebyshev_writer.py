"""Tests for space_map_data.export.position.chebyshev.writer."""

from space_map_data.export.position.chebyshev.writer import should_export
from space_map_data.models.object import ObjectType
from space_map_data.utils.naif import CHEBYSHEV_ASTEROID_WHITELIST
from tests.conftest import make_object


class TestShouldExport:
    """`should_export` is the writer-side defense against stale `.npz` files
    that the download cleanup didn't catch yet — e.g. after tightening the
    asteroid whitelist without re-running the (slow) download step."""

    def test_whitelisted_asteroid_passes(self):
        # 2000004 = Vesta, in CHEBYSHEV_ASTEROID_WHITELIST
        obj = make_object(
            id="spkid-20000004",
            object_type=ObjectType.asteroid_main_belt,
        )
        assert should_export(obj, 2000004) is True

    def test_non_whitelisted_asteroid_filtered(self):
        # 2000200 is not in the whitelist — was sampled when sb441-n373.bsp
        # was first loaded but should not ship as Chebyshev
        assert 2000200 not in CHEBYSHEV_ASTEROID_WHITELIST
        obj = make_object(
            id="spkid-20000200", object_type=ObjectType.asteroid_main_belt
        )
        assert should_export(obj, 2000200) is False

    def test_non_asteroid_always_passes(self):
        # Planets, moons, dwarfs, barycenters, the Sun all bypass the asteroid
        # whitelist gate — they're filtered (if at all) by the download step.
        for object_type in (
            ObjectType.planet,
            ObjectType.moon,
            ObjectType.dwarf_planet,
            ObjectType.barycenter,
            ObjectType.star,
        ):
            obj = make_object(id="naif-499", object_type=object_type)
            assert should_export(obj, 499) is True, object_type

    def test_asteroid_subtype_also_filtered(self):
        # Chebyshev zone routing groups every ObjectType.asteroid_* together,
        # so the whitelist check has to cover the whole family — a TNO with
        # 2000xxx-shaped naif_id outside the whitelist would otherwise leak.
        for object_type in (
            ObjectType.asteroid,
            ObjectType.asteroid_inner,
            ObjectType.asteroid_main_belt,
            ObjectType.asteroid_trojan,
            ObjectType.asteroid_centaur,
            ObjectType.asteroid_tno,
        ):
            obj = make_object(id="spkid-20999999", object_type=object_type)
            assert should_export(obj, 2999999) is False, object_type
