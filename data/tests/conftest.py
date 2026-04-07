"""Shared test factories for constructing model instances without a database."""

from space_map_data.models.object import (
    Object,
    ObjectType,
    ElementsScale,
    OrbitalSource,
)


def make_object(**overrides) -> Object:
    """Create an Object instance with sensible defaults. Override any field via kwargs."""
    defaults = {
        "id": "naif-399",
        "name": "Earth",
        "object_type": ObjectType.planet,
        "scale": ElementsScale.system,
        "epoch_jd": 2451545.0,
        "a": 1.0,
        "e": 0.0167,
        "i": 0.0,
        "om": 0.0,
        "w": 0.0,
        "ma": 0.0,
        "n": 0.9856,
        "parent_naif_id": 0,
        "orbital_source": OrbitalSource.horizons,
    }
    defaults.update(overrides)
    return Object(**defaults)
