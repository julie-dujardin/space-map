"""The spacecraft catalogue: what a route can be flown with.

Three lists — launchers, real spacecraft, and fiction — merged into one
registry keyed by id. They are separate modules because they are sourced
differently, not because anything downstream treats them differently.
"""

from space_map_data.constants.spacecraft.craft import SPACECRAFT
from space_map_data.constants.spacecraft.fiction import FICTIONAL
from space_map_data.constants.spacecraft.launchers import LAUNCHERS
from space_map_data.constants.spacecraft.references import (
    SPACECRAFT_SOURCES,
    SpacecraftReference,
)
from space_map_data.constants.spacecraft.specs import (
    CAPABILITIES,
    COST_KINDS,
    G0_M_S2,
    KINDS,
    POWER,
    PROPULSION,
    STATUSES,
    C3Curve,
    Cost,
    Measured,
    Spacecraft,
    delta_v_kms,
)

CATALOGUE: dict[str, Spacecraft] = {
    craft.id: craft for craft in (*LAUNCHERS, *SPACECRAFT, *FICTIONAL)
}

__all__ = [
    "CAPABILITIES",
    "CATALOGUE",
    "COST_KINDS",
    "C3Curve",
    "Cost",
    "FICTIONAL",
    "G0_M_S2",
    "KINDS",
    "LAUNCHERS",
    "Measured",
    "POWER",
    "PROPULSION",
    "SPACECRAFT",
    "SPACECRAFT_SOURCES",
    "STATUSES",
    "Spacecraft",
    "SpacecraftReference",
    "delta_v_kms",
]
