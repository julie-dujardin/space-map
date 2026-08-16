"""Shared SATCAT predicates for the Earth-sat export."""

from space_map_data.constants.earth_sats.satcat import OrbitCenter, OrbitType
from space_map_data.models.object import Object


def is_docked(obj: Object) -> bool:
    """True if ``obj``'s SATCAT row marks it docked to another object.

    Docked craft have no independent orbit, so they're dropped from position
    chunks (but kept in bundles/search/groups) to avoid a marker on the host.
    """
    sat = obj.satcat
    return sat is not None and (
        sat.orbit_center == OrbitCenter.DOCKED or sat.orbit_type == OrbitType.DOCKED
    )
