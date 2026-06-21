"""Shared SATCAT filters for the Earth-sat export queries."""

from sqlalchemy import or_
from sqlalchemy.sql.elements import ColumnElement

from space_map_data.constants.earth_sats.satcat import OrbitCenter, OrbitType
from space_map_data.models.object import Object
from space_map_data.models.object.satcat import Satcat


def not_docked() -> ColumnElement[bool]:
    """Exclude spacecraft docked to another object.

    Docked craft (SATCAT ``ORBIT_CENTER`` = a NORAD id → ``OrbitCenter.DOCKED``,
    or ``ORBIT_TYPE`` = ``DOC`` → ``OrbitType.DOCKED``) have no independent orbit,
    so they're dropped from the position and group exports. Objects with no
    SATCAT row are kept.
    """
    return ~Object.satcat.has(
        or_(
            Satcat.orbit_center == OrbitCenter.DOCKED.value,
            Satcat.orbit_type == OrbitType.DOCKED.value,
        )
    )
