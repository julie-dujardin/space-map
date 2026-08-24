"""Display zones for probe trajectories.

A zone bundles one planetary system (or `interplanetary`, everything outside
every system) and sets three things:

  * `r_zone_km` — membership radius from the barycenter. 2x Hill radius per
    planet: larger than any confirmed moon, and covers Sun-Earth L1/L2
    (JWST/Gaia halo orbits sit ~1.5 M km out, inside Earth's 3 M km zone).
  * `chunk_days` — the frontend's streaming unit, tuned to the zone's
    playback rate (slow interplanetary needs long chunks; fast Earth-Moon
    tolerates short ones). Must be an integer multiple of
    `kepler_subchunk_days`, enforced at construction.
  * `accuracy_threshold_km` — per-chunk auto-promote rule: a Kepler fit
    exceeding this escalates the chunk to Chebyshev.

A probe can be in multiple zones at once (a flyby inside a planet's Hill
radius is also `interplanetary`); the frontend loads one zone at a time so
the duplication is disk-only.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class Zone:
    key: str
    barycenter_naif_id: int
    fit_center_naif_id: int
    r_zone_km: float | None  # None = unbounded (interplanetary)
    chunk_days: float
    """Streaming chunk duration (days) — the unit the frontend swaps from disk."""

    accuracy_threshold_km: float
    """Per Kepler sub-chunk error threshold (km); exceeding it promotes
    that sub-chunk to Chebyshev."""

    kepler_subchunk_days: float
    """Width of one Kepler element snapshot — short enough that
    perturbations (other-planet pull, J2 drift) stay below the accuracy
    threshold. Multiple sub-chunks pack into one streaming chunk."""

    float64_coeffs: bool = False
    """Store coefficients as float64 (1.9x bigger) instead of float32.
    Needed only for interplanetary, where deep heliocentric distances hit
    float32's ~600 km quantization floor; planet-centric zones never
    approach it."""

    short_orbit_threshold_km: float = 500.0
    """Looser threshold for orbiters with period < `short_orbit_period_s`
    (MAVEN, MEX, MRO), keeping them on cheap Kepler-with-drift at the cost
    of ~50-100 km phase-shift — tolerable at planet-system zoom since the
    orbit shape itself still fits accurately."""

    short_orbit_period_s: float = 12 * 3600  # 12 hours

    kepler_max_center_dist_km: float | None = None
    """Skip Method-C Kepler when the probe is farther than this from the
    fit center (None = no limit). For the small-bodies zone: against a
    micro-μ body, conic elements at millions of km are numerically
    degenerate — a fit can pass the eval samples yet wander tens of km
    between them — while Chebyshev handles the smooth approach arc."""

    short_orbit_forces_kepler: bool = True
    """Pin short-period orbiters to Kepler even over threshold. Right for
    planet zones (Chebyshev aliases across a 30-day chunk at any affordable
    byte budget), wrong for small-bodies: its 1-day sub-chunks sweep down
    to 259 s segments, which resolve Dawn's 4.3 h LAMO cleanly, while
    forced Kepler shipped ~500 km errors around a 460 km body."""

    reject_subsurface_kepler: bool = False
    """Drop Kepler variants whose periapsis sits inside the fit-center body.
    A hovering probe (Hayabusa station-keeping at Itokawa) fits as a
    degenerate radial ellipse through the body — it passes the eval samples
    yet propagates and draws an orbit inside the asteroid. Chebyshev
    follows the true hover drift instead. Off for planet zones: their
    thresholds already reject anything that degenerate."""

    def __post_init__(self) -> None:
        # Same invariant as `SubChunkGrid`; raised here so it fires at module import.
        ratio = self.chunk_days / self.kepler_subchunk_days
        if abs(ratio - round(ratio)) > 1e-6:
            tail = (ratio - int(ratio)) * self.kepler_subchunk_days
            raise ValueError(
                f"Zone {self.key}: chunk_days ({self.chunk_days}) is not an "
                f"integer multiple of kepler_subchunk_days "
                f"({self.kepler_subchunk_days}). Would leave a "
                f"{tail:.3f}-day uncovered tail per chunk."
            )


# Catch-all zone for trajectories outside every planet's Hill sphere. Fit
# center is the Sun: cruise orbits are heliocentric ellipses (or shallow
# hyperbolae for Voyager-class escape trajectories).
INTERPLANETARY = Zone(
    key="interplanetary",
    barycenter_naif_id=0,
    fit_center_naif_id=10,
    r_zone_km=None,
    chunk_days=364.0,  # 52 × 7-day sub-chunks (~1-y playback unit)
    accuracy_threshold_km=1000.0,
    kepler_subchunk_days=7.0,
    float64_coeffs=True,  # Voyager/Pioneer at 100+ AU need float64 to clear the float32 floor
)

# Per-planet zones at 2x Hill sphere (r_hill = a_planet * (M_planet / (3
# M_sun))^(1/3), rounded up). Doubling covers L1/L2 + halo orbits (~1 Hill
# radius) plus margin for irregular moons that swing outside the formal
# sphere.
PLANETARY_ZONES: tuple[Zone, ...] = (
    # Kepler sub-chunk durations: 0.5-1 day for planetary zones (fast
    # orbiters' J2 drift moves Ω/ω several degrees/week); 7 days for
    # interplanetary (slow, N-body-dominated Sun-relative motion).
    Zone("mercury", 1, 199, 0.44e6, 183.0, 10.0, 1.0),  # ≈ 0.5 y
    Zone("venus", 2, 299, 2.0e6, 183.0, 10.0, 1.0),
    Zone("earth-moon", 3, 399, 3.0e6, 30.0, 10.0, 0.5),  # 60 × 0.5-d subs
    Zone(
        "mars", 4, 499, 2.2e6, 30.0, 10.0, 1.0
    ),  # Viking-era orbiters need short windows
    Zone("jupiter", 5, 599, 102.0e6, 365.0, 10.0, 1.0),  # ≈ 1 y
    Zone("saturn", 6, 699, 130.0e6, 365.0, 10.0, 1.0),
    Zone("uranus", 7, 799, 140.0e6, 1826.0, 10.0, 1.0),  # ≈ 5 y
    Zone("neptune", 8, 899, 232.0e6, 1826.0, 10.0, 1.0),
    Zone("pluto", 9, 999, 12.8e6, 1826.0, 10.0, 1.0),
)

# Rendezvous/flyby encounters with asteroids and comets. Membership is
# per-target (within `SMALL_BODY_ZONE_RADIUS_KM` of any curated small body,
# see `probes/small_bodies.py`), not barycentric — `barycenter_naif_id` and
# `fit_center_naif_id` are placeholders and every record in this zone
# carries a per-probe fit-center override to the matched body; chunks with
# no matchable body are dropped, never fit against the Sun (a Sun-relative
# f32 payload would quantize at ~10 km). Tight threshold because "accurate"
# here means metres next to a body hundreds of metres across.
SMALL_BODIES = Zone(
    key="small-bodies",
    barycenter_naif_id=0,
    fit_center_naif_id=10,
    r_zone_km=None,
    chunk_days=28.0,
    accuracy_threshold_km=0.5,
    kepler_subchunk_days=1.0,
    short_orbit_threshold_km=0.5,
    kepler_max_center_dist_km=1.0e5,
    short_orbit_forces_kepler=False,
    reject_subsurface_kepler=True,
)

ALL_ZONES: tuple[Zone, ...] = (INTERPLANETARY, *PLANETARY_ZONES, SMALL_BODIES)
ZONES_BY_KEY: dict[str, Zone] = {z.key: z for z in ALL_ZONES}


# NAIF IDs overriding the zone default with tighter `PRIORITY_THRESHOLD_KM`
# — flagship missions, manned spaceflight, EDLs, one-shot rendezvous where
# antenna-pointing-grade positioning is the point. Empty for now.
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
