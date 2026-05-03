"""NAIF ID classification utilities shared by Horizons and SPICE providers."""

from dataclasses import dataclass

from space_map_data.models.object import ObjectType, DWARF_PLANETS


# Moons that get full Chebyshev treatment. Two reasons a moon ends up here:
#
# 1. Surface-feature bodies — visualization zooms into them and the user expects
#    pixel-accurate positions (Io, Europa, Titan, …).
# 2. Method C (sampled mean-element fit) cannot describe their orbit because
#    it's not Keplerian-secular: co-orbital Trojans librate around L4/L5
#    (Helene/Polydeuces around Dione, Telesto/Calypso around Tethys) and the
#    fit residual is hundreds of degrees. They're cheap (~38–50 KB/year) so
#    Chebyshev pays for itself.
#
# Other inadequate cases (Saturn ring shepherds, inner Uranus/Neptune moons,
# Mars/Jupiter/Saturn small inner shepherds) are flagged at extraction time
# but not added here — each costs ~148 KB/year (0.5d floor) and ×29 of them
# would balloon the export. They ship with Method C and accept ~1e5 km error.
#
# Names are matched case-insensitively against Horizons / SPICE labels.
CHEBYSHEV_MOON_WHITELIST: frozenset[str] = frozenset(
    {
        # Earth
        "moon",
        # Mars
        "phobos",
        "deimos",
        # Jupiter
        "io",
        "europa",
        "ganymede",
        "callisto",
        "amalthea",
        "thebe",
        # Saturn (regulars + co-orbital Trojans + ring shepherds + Mimas-resonance)
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
        "helene",
        "telesto",
        "calypso",
        "polydeuces",
        "atlas",
        "prometheus",
        "pandora",
        "methone",
        "pallene",
        "daphnis",
        # Uranus (regulars + close-in chaotic inner shepherds)
        "miranda",
        "ariel",
        "umbriel",
        "titania",
        "oberon",
        "puck",
        "cordelia",
        "ophelia",
        "portia",
        "belinda",
        # Neptune (Triton + close-in shepherds Despina/Galatea/Larissa/Hippocamp)
        "triton",
        "proteus",
        "despina",
        "galatea",
        "larissa",
        "hippocamp",
        # Pluto small moons
        "charon",
        "nix",
        "kerberos",
        "styx",
    }
)

# Per-parent Chebyshev chunk cadence (years). Tuned so each chunk lands at
# roughly ~200 KB regardless of how many bodies share the parent's zone:
# Saturn's 21 whitelisted moons are densest and need ~1.5-month chunks; Pluto's
# four moons can comfortably pack into 2-year chunks. Earth has only the Moon
# and inherits the slow-mover (5-year) cadence — there is nothing to chunk
# more finely. Frontend reads this from the manifest's `moons.zones[].chunk_years`
# so each zone can be indexed independently.
CHEBYSHEV_PARENT_CHUNK_YEARS: dict[int, float] = {
    3: 5.0,  # Earth (Moon only)
    4: 0.5,  # Mars (Phobos + Deimos at 0.5d native intlen → ~149 KB/chunk)
    5: 0.5,  # Jupiter (6 bodies, 444 KB/yr → ~222 KB/chunk)
    6: 0.125,  # Saturn (21 bodies, 1583 KB/yr → ~198 KB/chunk)
    7: 0.25,  # Uranus (10 bodies, 846 KB/yr → ~212 KB/chunk)
    8: 0.25,  # Neptune (6 bodies, 891 KB/yr → ~223 KB/chunk)
    9: 2.0,  # Pluto (4 bodies, 99 KB/yr → ~198 KB/chunk)
}


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
