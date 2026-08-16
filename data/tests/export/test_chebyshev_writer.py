"""Tests for space_map_data.export.position.chebyshev.writer."""

from space_map_data.export.position.chebyshev.writer import should_export
from space_map_data.models.object import ObjectType
from space_map_data.utils.naif import CHEBYSHEV_ASTEROID_WHITELIST
from tests.conftest import make_object


class TestShouldExport:
    """`should_export` guards against stale `.npz` files the download cleanup
    missed — e.g. after tightening the whitelist without re-running downloads."""

    def test_whitelisted_asteroid_passes(self):
        # 2000004 = Vesta, in CHEBYSHEV_ASTEROID_WHITELIST
        obj = make_object(
            id="spkid-20000004",
            object_type=ObjectType.asteroid_main_belt,
        )
        assert should_export(obj, 2000004) is True

    def test_non_whitelisted_asteroid_filtered(self):
        # Sampled once from sb441-n373.bsp, but not whitelisted — must not ship.
        assert 2000200 not in CHEBYSHEV_ASTEROID_WHITELIST
        obj = make_object(
            id="spkid-20000200", object_type=ObjectType.asteroid_main_belt
        )
        assert should_export(obj, 2000200) is False

    def test_non_asteroid_always_passes(self):
        # Non-asteroid types skip the whitelist gate; the download step filters
        # them, if at all.
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
        # Zone routing groups every asteroid_* subtype together, so the
        # whitelist check must cover the whole family or a stray TNO would leak.
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
