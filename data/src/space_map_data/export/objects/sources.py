"""One cited work, in the shape the object panel's credit line reads.

The per-topic registries are separate tuples that agree on their first four
fields, so a body's credit line looks the same whichever of them a number came
from. `contribution` stays behind: it is the credits page's full sentence, where
a footer under a panel has room for the two or three words in `note`.
"""

from space_map_data.constants.activity.references import ActivityReference
from space_map_data.constants.atmosphere.references import AtmosphereReference
from space_map_data.constants.interior.references import InteriorReference
from space_map_data.constants.radiation.references import RadiationReference
from space_map_data.constants.spacecraft.references import SpacecraftReference
from space_map_data.constants.temperature.references import TemperatureReference

Reference = (
    ActivityReference
    | AtmosphereReference
    | InteriorReference
    | RadiationReference
    | SpacecraftReference
    | TemperatureReference
)


def source_row(ref: Reference) -> dict:
    """A note is optional — hand-authored overlays ship citations without one."""
    return {"title": ref.title, "url": ref.url} | (
        {"note": ref.note} if ref.note else {}
    )
