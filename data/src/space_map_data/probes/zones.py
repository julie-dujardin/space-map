"""Display zones for probe trajectories.

A zone bundles one planetary system (or `interplanetary` for everything
outside every system) and dictates:

  * Membership radius around the system barycenter (`r_zone_km`). A probe is
    "in" the zone whenever its distance from the barycenter is below this.
    Sized at 2× Hill radius for every planet — strictly larger than the
    outermost confirmed moon in every system, and large enough to cover
    Sun-Earth L1/L2 (the JWST / Gaia halo orbits sit at ~1.5 M km from
    Earth, well inside Earth's 3 M km zone).

  * Time-chunk duration (`chunk_years`). The unit the frontend loads from
    disk. Tuned to match the expected playback rate per zone — slow zoom
    levels (interplanetary at 1 y/s) need long chunks to avoid thrashing,
    fast zoom levels (Earth-Moon at maybe a day/s) tolerate shorter ones.

  * Accuracy threshold (`accuracy_threshold_km`). Per-chunk auto-promote
    rule: if a Method-C Kepler fit exceeds this, the chunk is escalated to
    Chebyshev. Tighter thresholds for planetary detail than interplanetary.

A probe can appear in multiple zones at once (e.g., a flyby probe inside
a planet's Hill radius is also still inside `interplanetary`). Frontend
loads one zone's chunks at a time so the duplication is on-disk only.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class Zone:
    key: str
    barycenter_naif_id: int
    fit_center_naif_id: int
    r_zone_km: float | None  # None = unbounded (interplanetary)
    chunk_years: float
    """Streaming chunk duration — the unit the frontend swaps from disk."""

    accuracy_threshold_km: float
    """Per *Kepler sub-chunk* error threshold. If a sub-chunk's Kepler fit
    exceeds this, the chunk-builder emits Chebyshev for that sub-chunk
    instead.
    """

    kepler_subchunk_days: float
    """Width of one Kepler element snapshot. Short enough that perturbations
    (other-planet pull on the central body, J2 evolution for orbiters)
    stay below the accuracy threshold over the sub-chunk. Multiple sub-
    chunks pack into one streaming chunk so the frontend can scrub through
    them cheaply.
    """

    float64_coeffs: bool = False
    """Store Chebyshev coefficients (and Kepler elements) as float64 instead
    of float32 (1.9× bigger). Required for zones where the spacecraft can
    sit at deep heliocentric distances where float32 hits its ~600 km
    quantization floor (interplanetary). Planet-centric zones never see
    positions > a few R_planet, so float32 is plenty.
    """

    short_orbit_threshold_km: float = 500.0
    """Looser accuracy threshold for spacecraft whose orbital period is less
    than `short_orbit_period_s`. Lets short-period planetary orbiters
    (MAVEN, MEX, MRO) stay on the cheap Kepler-with-drift representation
    at the cost of ~50-100 km position phase-shift — visible but tolerable
    at planet-system zoom, and the orbit shape still renders correctly
    because Ω/ω/n are fitted accurately.
    """

    short_orbit_period_s: float = 12 * 3600  # 12 hours


# Catch-all zone for trajectories outside every planet's Hill sphere. Fit
# center is the Sun: cruise orbits are heliocentric ellipses (or shallow
# hyperbolae for Voyager-class escape trajectories).
INTERPLANETARY = Zone(
    key="interplanetary",
    barycenter_naif_id=0,
    fit_center_naif_id=10,
    r_zone_km=None,
    chunk_years=1.0,  # 1-y chunks at 1y/s playback = 1s per chunk swap
    accuracy_threshold_km=1000.0,
    kepler_subchunk_days=7.0,
    float64_coeffs=True,  # Voyager/Pioneer at 100+ AU need float64 to clear the float32 floor
)

# Per-planet zones at 2× Hill sphere. Hill radius numbers from
#   r_hill = a_planet * (M_planet / (3 M_sun))^(1/3)
# rounded slightly up; doubling guarantees coverage of L1/L2 + halo orbits
# (which sit at ~1 Hill radius) plus a safety margin for distant irregular
# moons that swing outside their formal Hill sphere occasionally.
PLANETARY_ZONES: tuple[Zone, ...] = (
    # Kepler sub-chunk durations: 0.5–1 day for planetary zones (fast
    # orbiters' J2 drift moves Ω/ω several degrees per week, so we want
    # frequent re-snapshots), 7 days for interplanetary (slow Sun-relative
    # motion + N-body wobbles dominated by other planets).
    Zone("mercury", 1, 199, 0.44e6, 0.5, 10.0, 1.0),
    Zone("venus", 2, 299, 2.0e6, 0.5, 10.0, 1.0),
    Zone("earth-moon", 3, 399, 3.0e6, 1 / 12, 10.0, 0.5),  # ~1-month chunks
    Zone(
        "mars", 4, 499, 2.2e6, 1 / 12, 10.0, 1.0
    ),  # ~1-month chunks; Viking-era orbiters need short windows
    Zone("jupiter", 5, 599, 102.0e6, 1.0, 10.0, 1.0),
    Zone("saturn", 6, 699, 130.0e6, 1.0, 10.0, 1.0),  # 1y chunks (was 5y)
    Zone("uranus", 7, 799, 140.0e6, 5.0, 10.0, 1.0),
    Zone("neptune", 8, 899, 232.0e6, 5.0, 10.0, 1.0),
    Zone("pluto", 9, 999, 12.8e6, 5.0, 10.0, 1.0),
)

ALL_ZONES: tuple[Zone, ...] = (INTERPLANETARY, *PLANETARY_ZONES)
ZONES_BY_KEY: dict[str, Zone] = {z.key: z for z in ALL_ZONES}


# NAIF IDs that override the per-zone accuracy threshold with the tighter
# `PRIORITY_THRESHOLD_KM` — flagship missions, manned spaceflight, EDLs,
# and one-shot rendezvous events where antenna-pointing-grade positioning
# is what the user came to see. Empty list means we rely entirely on the
# per-zone defaults; add IDs as we encounter missions worth the upgrade.
PRIORITY_NAIF_IDS: frozenset[int] = frozenset(
    {
        # Apollo manned lunar program. Add Apollo {7..17} command modules
        # once we ingest the PDS-archived APOLLO SPKs.
        # Artemis program once available.
        # Voyager Grand Tour: -31, -32 — covered by default-threshold
        #   Chebyshev anyway (fast intlen during flybys).
        # Huygens descent: -150 — already on Chebyshev (cruise->Titan).
        # MSL / Mars 2020 EDL: -76, -168 — descent windows are short, OK
        #   to upgrade just those time slices once we slice phases.
        # JWST L2 insertion: -170 — single critical 6-month window.
    }
)
PRIORITY_THRESHOLD_KM: float = 0.1


def threshold_for(zone: Zone, naif_id: int) -> float:
    """Effective accuracy threshold for `naif_id` in `zone` (km)."""
    if naif_id in PRIORITY_NAIF_IDS:
        return PRIORITY_THRESHOLD_KM
    return zone.accuracy_threshold_km
