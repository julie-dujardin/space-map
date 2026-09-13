"""Which spacecraft left each panorama traverse.

The mission slug on a panorama entry names a traverse, not an object. A probe
page needs the link the other way round, so the index carries the probe id and
the mapping lives here, next to the slugs the pipeline mints.
"""

from space_map_data.constants.spacecraft.craft import SPACECRAFT

# Panorama mission slug -> `Spacecraft.id`. A mission with no entry simply has
# no probe page to link, which is the honest answer for the ones whose
# hardware the spacecraft table does not describe.
MISSION_SPACECRAFT: dict[str, str] = {
    "curiosity": "curiosity",
    "perseverance": "perseverance",
}


def probe_id(mission: str | None) -> str | None:
    """The `probe-<id>` whose traverse this mission is, when one is known."""
    craft_id = MISSION_SPACECRAFT.get(mission or "")
    if not craft_id:
        return None
    for craft in SPACECRAFT:
        if craft.id == craft_id:
            return craft.object_ids[0] if craft.object_ids else None
    return None
