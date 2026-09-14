"""Which spacecraft left each panorama traverse, and which world it is on.

The mission slug on a panorama entry names a traverse, not an object. A probe
page needs the link the other way round, so it lives here, next to the slugs the
pipeline mints — stated as the NAIF spacecraft id, which the probe inventory
already resolves to an object of its own.
"""

from functools import cache

from space_map_data.probes.probe_id import load_registry

# Panorama mission slug -> NAIF spacecraft id. A mission with no entry simply
# has no probe page to link, which is the honest answer for one whose craft the
# probe inventory does not carry.
MISSION_NAIF: dict[str, int] = {
    "curiosity": -76,
    "perseverance": -168,
    "spirit": -254,
    "opportunity": -253,
    "insight": -189,
    "phoenix": -84,
    "pathfinder": -530,
    "zhurong": -90000160,
    "yutu": -90000058,
    "yutu-2": -90000064,
}

# Which world each traverse is on. The export drops a panorama that names no
# body, so a mission missing here is one whose panoramas cannot reach the map.
MISSION_BODIES: dict[str, str] = {
    "curiosity": "naif-499",
    "perseverance": "naif-499",
    "spirit": "naif-499",
    "opportunity": "naif-499",
    "insight": "naif-499",
    "phoenix": "naif-499",
    "pathfinder": "naif-499",
    "zhurong": "naif-499",
    "yutu": "naif-301",
    "yutu-2": "naif-301",
}


# A lander never moved, so one published position covers everything it saw.
LANDERS = {
    "insight": {
        "latitude": 4.502384,
        "longitude": 135.623447,
        "elevation_m": -2613.426,
        "elevation_datum": "Mars MOLA areoid",
        "source_url": "https://doi.org/10.1029/2020EA001248",
    },
    "phoenix": {
        "latitude": 68.218830,
        "longitude": 234.250778,
        "elevation_m": None,
        "elevation_datum": None,
        "source_url": "https://an.rsl.wustl.edu/phx2008/help/landing_site.htm",
    },
    "pathfinder": {
        "latitude": 19.17,
        "longitude": 326.79,
        "elevation_m": None,
        "elevation_datum": None,
        "source_url": "https://planetarydata.jpl.nasa.gov/img/data/mpf/imp/mpim_0001/catalog/mission.cat",
    },
}
# Perseverance's raw-image feed is the one archive that dates every sol of the
# mission, including the sols no mosaic was delivered for.
FRAME = {
    "latitude_type": "planetocentric",
    "longitude_direction": "east",
    "longitude_range": [0, 360],
}


def lander_position(mission: str | None) -> dict | None:
    """The one place a lander saw everything from, or None for a rover."""
    if mission not in LANDERS:
        return None
    site = LANDERS[mission]
    return {
        **FRAME,
        "latitude": site["latitude"],
        "longitude": site["longitude"],
        "elevation_m": site["elevation_m"],
        "elevation_datum": site["elevation_datum"],
        "method": "published landing site; the lander never moved",
        "reference_point": "lander",
        "uncertainty_m": None,
        "source_url": site["source_url"],
    }


def body_id(mission: str | None) -> str | None:
    """The body a mission's panoramas stand on."""
    return MISSION_BODIES.get(mission or "")


@cache
def _probes_by_naif() -> dict[int, str]:
    return {
        entry["naif_id"]: f"probe-{entry['probe_id']}"
        for entry in load_registry()
        if entry.get("naif_id") is not None
    }


def probe_id(mission: str | None) -> str | None:
    """The `probe-<id>` whose traverse this mission is, when one is known."""
    naif = MISSION_NAIF.get(mission or "")
    return None if naif is None else _probes_by_naif().get(naif)
