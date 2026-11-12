"""Tests for space_map_data.export.position.chebyshev.writer."""

import math

import numpy as np

from space_map_data.export.position.chebyshev.writer import (
    _write_chunk_file,
    discovery_gates,
    should_export,
)
from space_map_data.export.position.reader import read_chebyshev_file
from space_map_data.models.object import Object, ObjectType
from space_map_data.utils.naif import CHEBYSHEV_ASTEROID_WHITELIST
from space_map_data.utils.time import J2000_JD, year_to_jd
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

    def test_comet_outside_the_target_list_is_filtered(self):
        # Comets reach chebyshev only as probe targets, and share the
        # small-body whitelist gate with the asteroids.
        obj = make_object(id="spkid-1000999", object_type=ObjectType.comet)
        assert should_export(obj, 1000999) is False

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


def _planet(naif_id: int, year: int | None) -> Object:
    obj = make_object(
        id=f"naif-{naif_id}", naif_id=naif_id, object_type=ObjectType.planet
    )
    obj.discovery_year = year
    return obj


def _barycenter(naif_id: int) -> Object:
    return make_object(
        id=f"naif-{naif_id}", naif_id=naif_id, object_type=ObjectType.barycenter
    )


def _days(year: int) -> float:
    return year_to_jd(year) - J2000_JD


class TestDiscoveryGate:
    def test_every_chunk_carries_the_gate(self, tmp_path):
        """The frontend keeps a body's header from the first chunk it reads, so
        a chunk opening after discovery still gates the dates before it."""
        uranus = _planet(799, 1781)
        rows = [(uranus, 799, 7)]
        segment = (np.zeros(1), np.ones(1), np.zeros((1, 3, 2)))
        gates = []
        for idx, start in enumerate((year_to_jd(1700), year_to_jd(1900))):
            _write_chunk_file(
                tmp_path,
                "major",
                idx,
                start,
                start + 365.25,
                [(*rows[0], *segment, 25559.0, False)],
                float64_coeffs=False,
                gates=discovery_gates(rows),
            )
            path = next(tmp_path.rglob(f"{idx}.bin.gz"))
            gates.append(read_chebyshev_file(path).bodies[0].visible_from_days)
        expected = np.float32(_days(1781))
        assert gates == [expected, expected]

    def test_barycenter_appears_with_its_first_member(self):
        gates = discovery_gates(
            [
                (_barycenter(9), 9, 0),
                (_planet(999, 1930), 999, 9),
                (_planet(901, 1978), 901, 9),
            ]
        )
        assert gates["naif-9"] == _days(1930)

    def test_barycenter_of_an_undated_member_is_always_there(self):
        gates = discovery_gates(
            [
                (_barycenter(4), 4, 0),
                (_planet(499, None), 499, 4),
                (_planet(401, 1877), 401, 4),
            ]
        )
        assert math.isnan(gates["naif-4"])
