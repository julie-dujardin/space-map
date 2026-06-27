"""Shared SATCAT predicates for the Earth-sat export."""

from space_map_data.constants.earth_sats.satcat import OrbitCenter, OrbitType
from space_map_data.models.object import Object


def is_docked(obj: Object) -> bool:
    """True if ``obj``'s SATCAT row marks it docked to another object.

    Docked craft (SATCAT ``ORBIT_CENTER`` = a NORAD id → ``OrbitCenter.DOCKED``,
    or ``ORBIT_TYPE`` = ``DOC`` → ``OrbitType.DOCKED``) have no independent orbit.
    They stay in the object bundles / search / groups but are dropped from the
    rendered position chunks, so the scene never draws a marker on top of the
    host they're docked to.
    """
    sat = obj.satcat
    return sat is not None and (
        sat.orbit_center == OrbitCenter.DOCKED or sat.orbit_type == OrbitType.DOCKED
    )
