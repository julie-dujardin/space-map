"""One cited work, in the shape the object panel's credit line reads.

The atmosphere, interior and temperature registries are separate tuples that
agree on their first four fields, so a body's credit line looks the same
whichever of them a number came from. `contribution` stays behind: it is the
credits page's full sentence, where a footer under a panel has room for the
two or three words in `note`.
"""

from space_map_data.constants.atmosphere.references import AtmosphereReference
from space_map_data.constants.interior.references import InteriorReference
from space_map_data.constants.temperature.references import TemperatureReference

Reference = AtmosphereReference | InteriorReference | TemperatureReference


def source_row(ref: Reference) -> dict:
    """A note is optional — hand-authored overlays ship citations without one."""
    return {"title": ref.title, "url": ref.url} | (
        {"note": ref.note} if ref.note else {}
    )
