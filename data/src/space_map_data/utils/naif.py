"""NAIF ID classification utilities shared by Horizons and SPICE providers."""

from dataclasses import dataclass

from space_map_data.models.object import ObjectType, DWARF_PLANETS


# Moons that get full Chebyshev treatment (named bodies with surface features —
# visualization zooms into them and needs accurate positions). All other moons
# fall back to the cheaper mean-elements-plus-J2-rates format.
#
# Names are matched case-insensitively against Horizons / SPICE labels.
CHEBYSHEV_MOON_WHITELIST: frozenset[str] = frozenset(
    {
        "moon",
        "phobos",
        "deimos",
        "io",
        "europa",
        "ganymede",
        "callisto",
        "amalthea",
        "thebe",
        "mimas",
        "enceladus",
        "tethys",
        "dione",
        "rhea",
        "titan",
        "hyperion",
        "iapetus",
        "phoebe",
        "janus",
        "epimetheus",
        "miranda",
        "ariel",
        "umbriel",
        "titania",
        "oberon",
        "puck",
        "triton",
        "proteus",
        "charon",
        "nix",
    }
)

# Fast inner moons (co-orbital shepherds / close-in regulars). Routed to the
# `moons/<parent>/inner` sub-zone — their Chebyshev ships at higher density
# than the main moons and is worth separating so clients can skip it.
CHEBYSHEV_INNER_MOON_NAIF_IDS: frozenset[int] = frozenset(
    {
        401,  # Phobos
        402,  # Deimos
        505,  # Amalthea
        514,  # Thebe
        610,  # Janus
        611,  # Epimetheus
        715,  # Puck
        808,  # Proteus
    }
)


def spk_id_from_naif(
    naif_id: int, obj_type: ObjectType | str | None = None
) -> int | None:
    """Inverse of the SBDB `_compute_naif_id` mapping.

    Returns the SBDB SPK ID corresponding to a Horizons/SPICE NAIF ID, or None
    if there is no SBDB counterpart.
    """
    if naif_id == 999:
        return 20134340  # Pluto
    if 2_000_000 <= naif_id <= 2_999_999:
        return naif_id + 18_000_000  # numbered asteroids
    if 20_000_000 <= naif_id <= 29_999_999:
        return naif_id  # already in SBDB range
    if 900_000_000 <= naif_id <= 999_999_999:
        return naif_id - 900_000_000  # binary asteroid primaries
    if obj_type == ObjectType.comet:
        return naif_id  # comets share the same numbering
    return None


def classify_object(
    naif_id: int, name: str, name_pretty: str, extra: str | None
) -> tuple[ObjectType, int]:
    """Classify a body by its NAIF ID and name.

    Returns (body_type, parent_naif_id) where parent is the NAIF ID of the
    body this object orbits (0 = SSB).

    NAIF ID ranges (https://naif.jpl.nasa.gov/pub/naif/toolkit_docs/C/req/naif_ids.html):
        negative        spacecraft
        0               SSB (excluded)
        1–9             planetary system barycenters
        10              Sun
        100–999         planets (P99) and moons (PNN), parent = barycenter P
        10000–99999     extended moon IDs (PXNNN), parent = barycenter P
        1000000–        comets (1M + periodic number)
        2000000–        asteroids (2M + catalog number)
        20000000–       asteroid system barycenters OR asteroids (20M + catalog number)
        100000000–      satellite in binary system (1 + barycenter ID)
        900000000–      primary in binary system (9 + barycenter ID)
    """
    if naif_id < 0:
        return ObjectType.spacecraft, 0

    if 0 <= naif_id <= 9 or "barycenter" in name.lower():
        # Planetary & asteroid system barycenters
        return ObjectType.barycenter, 0

    if naif_id == 10:
        # The Sun
        return ObjectType.star, 0

    if 100 <= naif_id <= 999:
        # Planets (P99) and moons (PNN), parent = planet barycenter P
        barycenter = naif_id // 100
        if naif_id % 100 == 99:  # Planet
            if naif_id == 999:  # rip pluto
                return ObjectType.dwarf_planet, barycenter
            return ObjectType.planet, barycenter
        return ObjectType.moon, barycenter
    if 10_000 <= naif_id < 100_000:
        # Extended moon IDs: PXNNN (e.g. 65088 = 2004S17)
        return ObjectType.moon, naif_id // 10_000

    if extra and "lagrange" in extra.lower():
        return ObjectType.lagrange_point, 0

    if 1_000_000 <= naif_id < 2_000_000:
        return ObjectType.comet, 0
    if 2_000_000 <= naif_id <= 2_999_999:
        if name_pretty.lower() in DWARF_PLANETS:
            return ObjectType.dwarf_planet, 0
        return ObjectType.asteroid, 0
    if naif_id >= 100_000_000:
        # Binary system members: satellite (1xx) or primary (9xx)
        barycenter_id = naif_id % 100_000_000
        if naif_id >= 900_000_000:
            # Primary body in binary system
            if name_pretty.lower() in DWARF_PLANETS:
                return ObjectType.dwarf_planet, barycenter_id
            return ObjectType.asteroid, barycenter_id
        # Satellite
        return ObjectType.moon, barycenter_id

    if "spacecraft" in name.lower() or 9_000_000 <= naif_id <= 9_999_999:
        return ObjectType.spacecraft, 0
    if 990_000 <= naif_id < 1_000_000:
        # WT1190F
        return ObjectType.debris, 0

    if 20_000_000 <= naif_id < 100_000_000:
        # 20152830...: asteroids
        return ObjectType.asteroid, 0

    raise ValueError(
        f"Could not classify body with NAIF ID {naif_id} and name '{name}'"
    )


@dataclass
class MajorBody:
    name: str | None
    naif_id: int
    parent_naif_id: int
    object_type: ObjectType
    designation: str | None = None
    extra: str | None = None
    iau_roman_designation: str | None = None
    naif_id_extended: int | None = None
