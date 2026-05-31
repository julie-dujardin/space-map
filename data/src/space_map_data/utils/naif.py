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
        # Jupiter (regulars + inner ring shepherds)
        "io",
        "europa",
        "ganymede",
        "callisto",
        "amalthea",
        "thebe",
        "adrastea",
        "metis",
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
        "pan",
        "aegaeon",
        "anthe",
        # Uranus (regulars + close-in chaotic inner shepherds + dust-ring family).
        # The dust-ring shepherds (Bianca..Cupid) were added after the alias
        # guard flagged them — sub-day periods and SPK type-2 sub-intervals at
        # the 0.5 d floor make Method C aliasing unrecoverable for them.
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
        "bianca",
        "cressida",
        "desdemona",
        "juliet",
        "rosalind",
        "perdita",
        "mab",
        "cupid",
        # Neptune (Triton + close-in shepherds Despina/Galatea/Larissa/Hippocamp + Naiad/Thalassa)
        "triton",
        "proteus",
        "despina",
        "galatea",
        "larissa",
        "hippocamp",
        "naiad",
        "thalassa",
        # Pluto small moons
        "charon",
        "nix",
        "hydra",
        "kerberos",
        "styx",
    }
)

# Asteroids that get full Chebyshev treatment. Originally the entire content
# of `sb441-n16.bsp` (16 most massive main-belt perturbers from DE441) — when
# we swapped to `sb441-n373.bsp` we kept the export scope here so the shipped
# asteroid list stays curated rather than ballooning to 373 bodies. Ceres is
# classified as `dwarf_planet` and passes through `_CORE_BODY_TYPES`
# independently, so it doesn't need a slot here.
CHEBYSHEV_ASTEROID_WHITELIST: frozenset[int] = frozenset(
    {
        2000002,  # Pallas
        2000003,  # Juno
        2000004,  # Vesta
        2000007,  # Iris
        2000010,  # Hygiea
        2000015,  # Eunomia
        2000016,  # Psyche
        2000031,  # Euphrosyne
        2000052,  # 52 Europa
        2000065,  # Cybele
        2000087,  # Sylvia
        2000088,  # Thisbe
        2000107,  # Camilla
        2000511,  # Davida
        2000704,  # Interamnia
    }
)


# Per-parent Chebyshev chunk cadence (years). Tuned so each chunk lands at
# roughly ~200 KB regardless of how many bodies share the parent's zone:
# Saturn's 24 whitelisted moons are densest and need ~1.5-month chunks; Pluto's
# five moons can comfortably pack into 2-year chunks. Earth has only the Moon
# and inherits the slow-mover (5-year) cadence — there is nothing to chunk
# more finely. Frontend reads this from the manifest's `moons.zones[].chunk_years`
# so each zone can be indexed independently.
CHEBYSHEV_PARENT_CHUNK_YEARS: dict[int, float] = {
    3: 5.0,  # Earth (Moon only)
    4: 0.5,  # Mars (Phobos + Deimos at 0.5d native intlen → ~149 KB/chunk)
    5: 0.5,  # Jupiter (8 bodies, 732 KB/yr → ~366 KB/chunk)
    6: 0.125,  # Saturn (24 bodies, ~1929 KB/yr → ~241 KB/chunk)
    7: 0.125,  # Uranus (18 bodies, ~2034 KB/yr → ~254 KB/chunk — halved cadence to keep chunks bounded after adding 8 dust-ring shepherds)
    8: 0.25,  # Neptune (8 bodies, 1187 KB/yr → ~297 KB/chunk)
    9: 2.0,  # Pluto (5 bodies, 124 KB/yr → ~247 KB/chunk)
}


def spk_id_from_naif(
    naif_id: int, obj_type: ObjectType | str | None = None
) -> int | None:
    """Inverse of `naif_id_from_spk`.

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


def naif_id_from_spk(
    spk_id: int, obj_type: ObjectType | str | None = None
) -> int | None:
    """Compute the Horizons NAIF ID corresponding to an SBDB SPK ID.

    JPL uses different numbering conventions across Horizons and SBDB:
    - Pluto: SBDB spkid 20134340 ↔ Horizons naif 999
    - Numbered asteroids: SBDB 20_000_000+n ↔ Horizons 2_000_000+n (offset 18M)
    - Comets: same scheme in both systems
    """
    if spk_id == 20134340:
        return 999  # Pluto
    if 20_000_000 <= spk_id <= 20_999_999:
        return spk_id - 18_000_000  # numbered asteroids
    if obj_type == ObjectType.comet:
        return spk_id  # comets share the same numbering
    return None


def classify_object(
    naif_id: int, name: str, name_pretty: str, extra: str | None
) -> tuple[ObjectType, int]:
    """Classify a body by its NAIF ID and name.

    Returns (body_type, parent_id) where parent is the NAIF ID of the
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
    parent_id: int
    object_type: ObjectType
    designation: str | None = None
    iau_roman_designation: str | None = None
    naif_id_extended: int | None = None
