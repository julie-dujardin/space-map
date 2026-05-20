"""Per-probe gravitational-primary detection for the probe fit.

The probes export historically fits every spacecraft against its zone's stored
`fit_center_naif_id` — Earth (399) for `earth-moon`, Saturn (699) for `saturn`,
the Sun (10) for `interplanetary`. That breaks for spacecraft whose actual
gravitational primary is a moon or asteroid in that system: a Moon orbiter's
Earth-relative state mixes the Moon's ~28-day Earth orbit with the spacecraft's
~2-hour lunar orbit, which no single Kepler element set can describe — so the
sub-chunk falls through to Chebyshev and the coefficient budget pays for the
Moon's heliocentric motion on top of the spacecraft's local trajectory.

This module picks the real primary per (probe, chunk) by enumerating every
body for which we have a SPICE Chebyshev npz (so the renderer can compose the
primary's world position later) and testing whether the probe sits inside that
body's Hill sphere for ≥80% of the window. Smallest-enclosing-body wins so a
spacecraft inside Titan's Hill sphere routes to Titan even though Saturn's
Hill sphere also contains it.

Generic in two senses:
  * Any body with a chebyshev `.npz` and a PCK-listed `GM` is a candidate —
    moons, dwarf planets, large asteroids (Vesta, Psyche, Ceres-from-DWARF).
  * The candidate's "primary" is derived from the npz's recorded parent
    barycenter, so Moon (barycenter 3) routes to Earth (399), Titan (barycenter
    6) to Saturn (699), Vesta (barycenter 0 = SSB) to the Sun (10).
"""

import hashlib
import logging
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import spiceypy

from space_map_data.constants.providers import ID_TYPES
from space_map_data.export.position.format import (
    ID_TYPE_ORDINAL,
    MISSING_ID_TYPE,
    MISSING_INT32,
)
from space_map_data.probes.zones import Zone
from space_map_data.utils.naif import spk_id_from_naif

logger = logging.getLogger(__name__)

_FIT_CENTER_FRAME = "ECLIPJ2000"
_DEFAULT_THRESHOLD_FRACTION = 0.8
_DEFAULT_SAMPLES_PER_WINDOW = 5


@dataclass(frozen=True)
class FitCenterCandidate:
    """One body the writer may route a probe to.

    `naif_id` is what SPICE uses for spkpos / GM lookups. `id_type` +
    `id_value` are what the binary stores in the per-probe header so the
    frontend can resolve the right Object id (NAIF for moons, SPKID for
    SBDB asteroids — Vesta is `naif-2000004` to SPICE but `spkid-20000004`
    in our Object table).

    `primary_naif_id` is the body whose Hill sphere we're measuring against
    — the actual gravitational parent, not the chebyshev npz's recorded
    barycenter. Moons: planet (399 for Moon, 699 for Titan, …). SSB-orbiting
    asteroids: the Sun (10).
    """

    naif_id: int
    id_type_ordinal: int
    id_value: int
    barycenter_naif_id: int
    primary_naif_id: int
    mu_km3_s2: float
    primary_mu_km3_s2: float


def _primary_for_barycenter(barycenter_naif_id: int) -> int:
    """Map an npz `parent_id` (a barycenter) to the gravitating primary.

    Chebyshev npz files record the body's parent as a barycenter ID —
    EMB = 3 for the Moon, Saturn-barycenter = 6 for Titan, SSB = 0 for
    SBDB asteroids. The Hill sphere we care about is around the dominant
    gravitating body in that system, which for the planetary barycenters
    is the planet itself (the barycenter sits ~thousand km off the planet
    for Earth–Moon; less than that for everything else). SSB → Sun.
    """
    if barycenter_naif_id == 0:
        return 10  # Sun
    if 1 <= barycenter_naif_id <= 9:
        return barycenter_naif_id * 100 + 99  # planet NAIF
    return barycenter_naif_id


def _resolve_id_for_naif(naif_id: int) -> tuple[int, int]:
    """`(id_type_ordinal, id_value)` for a candidate's per-probe-header
    fit_center encoding. Asteroids ingest under SPKID in the Object table
    (Vesta = `spkid-20000004`), so we translate their NAIF via
    `spk_id_from_naif`. Everything else (planets, moons, Sun) stays NAIF."""
    if 2_000_000 <= naif_id <= 2_999_999:
        spkid = spk_id_from_naif(naif_id)
        if spkid is not None:
            return ID_TYPE_ORDINAL[ID_TYPES.SPKID], spkid
    return ID_TYPE_ORDINAL[ID_TYPES.NAIF], naif_id


def load_candidates(chebyshev_dir: Path) -> list[FitCenterCandidate]:
    """Walk `chebyshev_dir/*.npz` and build the candidate list.

    Skips a body when SPICE has no `GM` for it (no Hill sphere computable)
    or when its primary has no `GM` either. Logs at debug for visibility
    without spamming the export run.

    Must be called with SPICE in a state where `bodvrd("GM")` works — i.e.
    PCK + generic SPK kernels are already furnshed.
    """
    out: list[FitCenterCandidate] = []
    if not chebyshev_dir.exists():
        return out
    for npz in sorted(chebyshev_dir.glob("*.npz")):
        try:
            naif_id = int(npz.stem)
        except ValueError:
            logger.debug("fit_centers: skip non-numeric npz %s", npz.name)
            continue
        try:
            meta = np.load(npz)["meta"]
        except (OSError, KeyError):
            logger.debug("fit_centers: failed to read meta from %s", npz.name)
            continue
        barycenter_naif_id = int(meta[1])
        primary_naif_id = _primary_for_barycenter(barycenter_naif_id)
        if primary_naif_id == naif_id:
            # A planet's parent is the planet itself in our scheme (399 ↔ 3
            # → 399). The planet IS the zone fit center and never an
            # alternate primary, so skip it.
            continue
        try:
            mu = float(spiceypy.bodvrd(str(naif_id), "GM", 1)[1][0])
            mu_primary = float(spiceypy.bodvrd(str(primary_naif_id), "GM", 1)[1][0])
        except spiceypy.exceptions.SpiceyError:
            logger.debug(
                "fit_centers: skip %d (primary=%d): missing GM in PCK",
                naif_id,
                primary_naif_id,
            )
            continue
        id_type_ordinal, id_value = _resolve_id_for_naif(naif_id)
        out.append(
            FitCenterCandidate(
                naif_id=naif_id,
                id_type_ordinal=id_type_ordinal,
                id_value=id_value,
                barycenter_naif_id=barycenter_naif_id,
                primary_naif_id=primary_naif_id,
                mu_km3_s2=mu,
                primary_mu_km3_s2=mu_primary,
            )
        )
    return out


def candidates_for_zone(
    candidates: list[FitCenterCandidate], zone: Zone
) -> list[FitCenterCandidate]:
    """Candidates whose gravitating primary is the zone's fit center.

    Earth-Moon zone (fit_center=399 Earth): only the Moon (primary=399).
    Saturn zone (fit_center=699): Titan, Enceladus, etc. (primary=699).
    Interplanetary zone (fit_center=10 Sun): SSB-orbiting asteroids/dwarfs
    whose primary resolves to the Sun.

    Sorted by mu_km3_s2 ascending so the smallest body — which has the
    tightest Hill sphere and therefore the most specific match — wins
    detection ties at chunks where multiple Hill spheres overlap.
    """
    out = [c for c in candidates if c.primary_naif_id == zone.fit_center_naif_id]
    out.sort(key=lambda c: c.mu_km3_s2)
    return out


def detect_fit_center(
    candidates: list[FitCenterCandidate],
    probe_naif_id: int,
    t_start_et: float,
    t_end_et: float,
    threshold_fraction: float = _DEFAULT_THRESHOLD_FRACTION,
    n_samples: int = _DEFAULT_SAMPLES_PER_WINDOW,
) -> FitCenterCandidate | None:
    """Pick the smallest candidate whose Hill sphere contains the probe for
    ≥ `threshold_fraction` of `n_samples` ETs across `[t_start_et, t_end_et]`.

    Returns None when no candidate hits the threshold — caller falls back
    to the zone's stored fit center. Hill radius is computed per-ET (not
    once at window center) so eccentric body orbits (Titan @ 0.029 e,
    Triton retrograde, comets) don't false-negative at apo when the
    instantaneous body-primary distance is largest.

    Failed spkpos calls (kernel gaps mid-window) count as "outside" for
    that sample — better to mis-route a few transition samples to the
    zone default and accept Chebyshev than to bias detection by
    pretending the lookup succeeded.
    """
    if not candidates:
        return None
    ets = np.linspace(t_start_et, t_end_et, n_samples)
    threshold_count = max(1, int(np.ceil(threshold_fraction * n_samples)))
    for cand in candidates:
        n_inside = 0
        for et in ets:
            try:
                probe_pos, _ = spiceypy.spkpos(
                    str(probe_naif_id),
                    float(et),
                    _FIT_CENTER_FRAME,
                    "NONE",
                    str(cand.naif_id),
                )
                body_to_primary, _ = spiceypy.spkpos(
                    str(cand.naif_id),
                    float(et),
                    _FIT_CENTER_FRAME,
                    "NONE",
                    str(cand.primary_naif_id),
                )
            except spiceypy.exceptions.SpiceyError:
                continue
            d_probe = float(np.linalg.norm(probe_pos))
            d_body = float(np.linalg.norm(body_to_primary))
            r_hill = d_body * (cand.mu_km3_s2 / (3.0 * cand.primary_mu_km3_s2)) ** (
                1.0 / 3.0
            )
            if d_probe < r_hill:
                n_inside += 1
                if n_inside >= threshold_count:
                    # Early exit: even if the remaining samples fail, this
                    # candidate already meets the threshold; smaller-Hill
                    # candidates were checked first so we keep this one.
                    return cand
    return None


def candidates_hash(candidates: list[FitCenterCandidate]) -> str:
    """Stable short hash of the candidate-set identity for sidecar signatures.

    Captures `(naif_id, primary_naif_id)` pairs only — GM and barycenter are
    derived from PCK / npz metadata that are downstream signals the user
    can't easily edit. The point is to invalidate chunks when the candidate
    *set* changes (new moon downloaded, asteroid added to chebyshev), not
    when an unrelated PCK value drifts."""
    payload = ",".join(f"{c.naif_id}:{c.primary_naif_id}" for c in candidates)
    return hashlib.sha256(payload.encode()).hexdigest()[:16]


def fit_center_header_fields(
    chosen: FitCenterCandidate | None,
) -> tuple[int, int]:
    """`(fit_center_id_value, fit_center_id_type)` for `pack_probe_header`.

    Returns the sentinel pair when no override applies (probe stays on the
    zone's stored fit center). Sentinels skip the renderer's
    primary-override path.
    """
    if chosen is None:
        return MISSING_INT32, MISSING_ID_TYPE
    return chosen.id_value, chosen.id_type_ordinal
