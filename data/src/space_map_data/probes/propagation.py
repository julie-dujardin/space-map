"""Identify probes whose trajectory can be extrapolated past end-of-archive.

A candidate has a stale SPK and a dynamically simple end-state: hyperbolic
Sun escape or bound heliocentric clear of every planet's Hill sphere. The
events JSON ``status`` field vetoes (impacted / landed / completed). Caller
owns the SPICE kernel pool; this module never calls ``kclear``.
"""

import datetime
import json
import logging
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import spiceypy

from space_map_data.probes.probe_id import index_by_source, load_registry
from space_map_data.probes.trace import _merged_intervals
from space_map_data.utils.paths import SOURCES_POSITION_DIR

logger = logging.getLogger(__name__)

GM_SUN = 1.32712440018e11  # km³/s²
AU_KM = 149597870.7
S_PER_YEAR = 86400.0 * 365.25

EVENTS_DIR = SOURCES_POSITION_DIR / "probe-events"

# Outer planets use barycenter IDs because de440 doesn't carry planet bodies
# past Mars. Moon and Sun entries from the shared Hill table are excluded
# (Moon's Hill is wrt Earth, Sun's is a PSP-refine trigger not an escape SOI).
_PLANET_SOI_NAIFS: tuple[int, ...] = (199, 299, 399, 4, 5, 6, 7, 8)
PLANET_NAMES: dict[int, str] = {
    199: "Mercury",
    299: "Venus",
    399: "Earth",
    4: "Mars",
    5: "Jupiter",
    6: "Saturn",
    7: "Uranus",
    8: "Neptune",
}

CONFIRMING_STATUSES = frozenset(
    {
        "heliocentric",
        "dormant",
        "lost",
        "contact_lost",
        "interstellar",
    }
)
# Veto when status says deorbited/impacted, even if the last SPK sample looks
# like a clean coast — the kernel may just end before the maneuver.
VETO_STATUSES = frozenset(
    {
        "impacted",
        "landed_inactive",
        "landed_active",
        "crashed",
        "in_orbit_inactive",
        "in_orbit_active",
        "completed",
        "active",
        "in_transit",
        "decayed",
    }
)

PROP_FORCE_ON = "force_on"
PROP_FORCE_OFF = "force_off"


@dataclass(frozen=True)
class PropagationConfig:
    stale_yr: float = 0.5
    hill_mult: float = 5.0
    end_year: int = 2150


@dataclass
class Candidate:
    """Detector output for one (mission, naif). `state_km_kms` is the
    ECLIPJ2000-wrt-Sun 6-vector at end_et; the synthesiser uses it as the
    Type 5 segment's seed state."""

    mission: str
    naif: int
    name: str
    cospar: str | None
    end_et: float
    stale_yr: float
    state_km_kms: tuple[float, float, float, float, float, float]
    r_sun_au: float
    v_kms: float
    energy: float
    nearest_planet: str
    nearest_dist_km: float
    nearest_hill_km: float
    events_status: str | None
    events_override: str | dict | None
    regime: str  # "hyperbolic" | "bound_clear" | "bound_in_soi"
    verdict: (
        str  # "PROPAGATE_HYP" | "PROPAGATE_HELIO" | "PROPAGATE_FORCED_ON" | "SKIP_*"
    )

    @property
    def is_propagate(self) -> bool:
        return self.verdict.startswith("PROPAGATE_")


def load_events_by_cospar() -> dict[str, dict]:
    """Probe entries keyed by COSPAR. NAIF would be ambiguous (reused across
    decades — e.g. -76 was Mariner 10, now MSL)."""
    out: dict[str, dict] = {}
    if not EVENTS_DIR.exists():
        return out
    for path in sorted(EVENTS_DIR.glob("*.json")):
        try:
            data = json.loads(path.read_text())
        except (OSError, json.JSONDecodeError) as exc:
            logger.warning("propagation: failed to read %s: %s", path, exc)
            continue
        for probe in data.get("probes", []):
            cospar = probe.get("cospar_id")
            if cospar:
                out[cospar] = probe
    return out


def classify_state(
    naif: int, et: float, hill_mult: float
) -> tuple[str, np.ndarray, float, int, float, float]:
    """Classify ``naif`` at ``et``: returns (regime, state6, energy,
    nearest_naif, nearest_d_km, nearest_hill_km). Regime is "hyperbolic"
    (E_sun > 0), "bound_clear" (outside every ``hill_mult × Hill``), or
    "bound_in_soi"."""
    # Local: keeps `probes/` free of a static download-provider dep.
    from space_map_data.download.providers.spice.synth.refine import (
        compute_major_body_hill_km,
    )

    state, _ = spiceypy.spkezr(str(naif), et, "ECLIPJ2000", "NONE", "10")
    state6 = np.asarray(state, dtype=float)
    r = float(np.linalg.norm(state6[:3]))
    v = float(np.linalg.norm(state6[3:]))
    energy = 0.5 * v * v - GM_SUN / r

    hill_table = compute_major_body_hill_km()
    nearest_naif = 0
    nearest_d = float("inf")
    nearest_hill = 0.0
    in_soi = False
    for pn in _PLANET_SOI_NAIFS:
        hill = hill_table.get(pn)
        if hill is None:
            continue
        try:
            rel, _ = spiceypy.spkpos(str(naif), et, "ECLIPJ2000", "NONE", str(pn))
        except spiceypy.exceptions.SpiceyError:
            continue
        d = float(np.linalg.norm(rel))
        if d < nearest_d:
            nearest_d = d
            nearest_naif = pn
            nearest_hill = hill
        if d < hill_mult * hill:
            in_soi = True

    if energy > 0:
        regime = "hyperbolic"
    elif in_soi:
        regime = "bound_in_soi"
    else:
        regime = "bound_clear"

    return regime, state6, energy, nearest_naif, nearest_d, nearest_hill


def decide_verdict(
    regime: str,
    stale_yr: float,
    stale_thresh: float,
    events_status: str | None,
    events_override: str | dict | None,
) -> str:
    """Combine dynamics + curated status + manual override. ``force_on`` /
    ``force_off`` short-circuit the dynamic check; a ``from_state`` dict
    counts as ``force_on`` (the synthesiser handles the seed state)."""
    if events_override == PROP_FORCE_OFF:
        return "SKIP_FORCED_OFF"
    if events_override == PROP_FORCE_ON or isinstance(events_override, dict):
        return "PROPAGATE_FORCED_ON"
    if stale_yr < stale_thresh:
        return "SKIP_FRESH"
    if events_status in VETO_STATUSES:
        return "SKIP_VETOED"
    if regime == "hyperbolic":
        return "PROPAGATE_HYP"
    if regime == "bound_clear":
        return "PROPAGATE_HELIO"
    return "SKIP_IN_SOI"


def evaluate_probe(
    mdir_name: str,
    naif: int,
    kernel_paths: list[str],
    config: PropagationConfig,
    now_et: float,
    registry_by_source: dict[tuple[str, int], dict],
    events_by_cospar: dict[str, dict],
) -> Candidate | None:
    """Detector for one (mission, naif). Caller must have furnshed kernels.
    Returns None on no coverage or end-state lookup failure."""
    merged = _merged_intervals(naif, kernel_paths)
    if not merged:
        return None
    t_last = merged[-1][1]
    try:
        regime, state6, energy, np_naif, np_d, np_hill = classify_state(
            naif, t_last, config.hill_mult
        )
    except spiceypy.exceptions.SpiceyError as exc:
        logger.warning(
            "propagation: %s/%d end-state lookup failed at et=%.3f (%s)",
            mdir_name,
            naif,
            t_last,
            exc,
        )
        return None

    stale_yr = (now_et - t_last) / S_PER_YEAR
    entry = registry_by_source.get((mdir_name, naif))
    cospar = entry.get("cospar_id") if entry else None
    name = entry["name"] if entry else mdir_name
    ev_probe = events_by_cospar.get(cospar) if cospar else None
    ev_status = ev_probe.get("status") if ev_probe else None
    ev_override = ev_probe.get("propagation") if ev_probe else None

    verdict = decide_verdict(regime, stale_yr, config.stale_yr, ev_status, ev_override)
    return Candidate(
        mission=mdir_name,
        naif=naif,
        name=name,
        cospar=cospar,
        end_et=t_last,
        stale_yr=stale_yr,
        state_km_kms=(
            float(state6[0]),
            float(state6[1]),
            float(state6[2]),
            float(state6[3]),
            float(state6[4]),
            float(state6[5]),
        ),
        r_sun_au=float(np.linalg.norm(state6[:3])) / AU_KM,
        v_kms=float(np.linalg.norm(state6[3:])),
        energy=energy,
        nearest_planet=PLANET_NAMES.get(np_naif, "?"),
        nearest_dist_km=np_d,
        nearest_hill_km=np_hill,
        events_status=ev_status,
        events_override=ev_override,
        regime=regime,
        verdict=verdict,
    )


def now_et() -> float:
    """Current UTC as ET. Caller must have an LSK furnshed."""
    return spiceypy.utc2et(
        datetime.datetime.now(datetime.UTC).strftime("%Y-%m-%dT%H:%M:%S")
    )


def furnish_generic_kernels(spice_root: Path) -> None:
    """Furnish LSK + generic SPKs. Caller owns the matching kclear/unload."""
    for lsk in spice_root.glob("lsk/*.tls"):
        spiceypy.furnsh(str(lsk))
    for spk in (spice_root / "spk").rglob("*.bsp"):
        spiceypy.furnsh(str(spk))


def detect_all(config: PropagationConfig) -> list[Candidate]:
    """Run the detector against every mission on disk. Returns all
    Candidates (SKIPs too — callers diagnose with them)."""
    # Local: avoids export → probes import cycle.
    from space_map_data.export.position.probes.kernels import enumerate_probes

    spice_root = SOURCES_POSITION_DIR / "spice-kernels"
    furnish_generic_kernels(spice_root)
    registry = load_registry()
    by_source = index_by_source(registry)
    events_by_cospar = load_events_by_cospar()
    now = now_et()

    out: list[Candidate] = []
    for mdir, kernels, naif in enumerate_probes():
        kpaths = [str(k) for k in kernels]
        # Idempotence: a prior run's extrap segment would make the probe look
        # fresh and the verdict would flip to SKIP_FRESH. Furnish them so
        # spkezr works through real-kernel gaps, but base coverage on upstream.
        upstream_kpaths = [k for k in kpaths if not k.endswith("-extrap.bsp")]
        for k in kpaths:
            spiceypy.furnsh(k)
        try:
            cand = evaluate_probe(
                mdir.name,
                naif,
                upstream_kpaths,
                config,
                now,
                by_source,
                events_by_cospar,
            )
        finally:
            for k in kpaths:
                spiceypy.unload(k)
        if cand is not None:
            out.append(cand)
    return out


def from_state_overrides() -> list[dict]:
    """Events entries with ``"propagation": {"mode": "from_state", ...}`` —
    probes with no SPK at all (Apollo S-IVBs, Mariner 2 with no NAIF, …)."""
    out: list[dict] = []
    for probe in load_events_by_cospar().values():
        prop = probe.get("propagation")
        if isinstance(prop, dict) and prop.get("mode") == "from_state":
            out.append(probe)
    return out
