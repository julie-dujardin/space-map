"""Per-probe gravitational-primary detection for the probe fit.

Picks the real primary per (probe, chunk) by enumerating every body with a
SPICE Chebyshev npz and testing whether the probe sits inside that body's
Hill sphere for ≥80% of the window. Smallest-enclosing-body wins so a probe
inside Titan's Hill sphere routes to Titan over Saturn. Without this, a Moon
orbiter's Earth-relative state mixes the Moon's 28-day Earth orbit with the
spacecraft's local orbit and falls through to Chebyshev when Method-C Kepler
would describe it cleanly against the Moon.
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
from space_map_data.probes.small_bodies import SMALL_BODY_TARGET_NAIF_IDS
from space_map_data.probes.zones import Zone
from space_map_data.utils.naif import spk_id_from_naif

logger = logging.getLogger(__name__)

_FIT_CENTER_FRAME = "ECLIPJ2000"
_DEFAULT_THRESHOLD_FRACTION = 0.8
_DEFAULT_SAMPLES_PER_WINDOW = 5


@dataclass(frozen=True)
class FitCenterCandidate:
    """One body the writer may route a probe to.

    `naif_id` drives SPICE calls; `id_type`/`id_value` are what the binary
    stores (asteroids under SPKID, else NAIF). `primary_naif_id` is the
    dominant gravitating body — planet for moons, Sun for SSB asteroids —
    used for the Hill-sphere check.
    """

    naif_id: int
    id_type_ordinal: int
    id_value: int
    barycenter_naif_id: int
    primary_naif_id: int
    mu_km3_s2: float
    primary_mu_km3_s2: float


def _primary_for_barycenter(barycenter_naif_id: int) -> int:
    """Npz `parent_id` (a barycenter) → the body whose Hill sphere we
    measure. Planetary barycenters (1..9) → planet NAIF; SSB (0) → Sun."""
    if barycenter_naif_id == 0:
        return 10  # Sun
    if 1 <= barycenter_naif_id <= 9:
        return barycenter_naif_id * 100 + 99  # planet NAIF
    return barycenter_naif_id


def _resolve_id_for_naif(naif_id: int) -> tuple[int, int]:
    """`(id_type_ordinal, id_value)` for the per-probe-header fit_center
    encoding. Asteroids use SPKID (Vesta = `spkid-20000004`); everything
    else stays NAIF."""
    if 2_000_000 <= naif_id <= 2_999_999:
        spkid = spk_id_from_naif(naif_id)
        if spkid is not None:
            return ID_TYPE_ORDINAL[ID_TYPES.SPKID], spkid
    return ID_TYPE_ORDINAL[ID_TYPES.NAIF], naif_id


def load_candidates(chebyshev_dir: Path) -> list[FitCenterCandidate]:
    """Walk `chebyshev_dir/*.npz` and build the candidate list. Skips a
    body when SPICE has no `GM` for it or its primary. Requires PCK to be
    furnshed for the `bodvrd("GM")` lookups."""
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
        except OSError, KeyError:
            logger.debug("fit_centers: failed to read meta from %s", npz.name)
            continue
        barycenter_naif_id = int(meta[1])
        primary_naif_id = _primary_for_barycenter(barycenter_naif_id)
        if primary_naif_id == naif_id:
            # Planets are the zone fit center themselves, never an alternate.
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
    """Candidates whose gravitating primary is the zone's fit center. Sorted
    by mu ascending so the tightest Hill sphere wins detection ties."""
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
    ≥ `threshold_fraction` of `n_samples` ETs. Returns None when no
    candidate hits the threshold; failed spkpos lookups count as outside."""
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
                    return cand
    return None


def small_body_candidates() -> list[FitCenterCandidate]:
    """Candidates for the `small-bodies` zone: the curated target list from
    `probes.small_bodies`, all Sun-primary. Separate from the npz-derived
    interplanetary candidates ON PURPOSE — folding these into interplanetary
    would flip its candidates hash and invalidate every cached
    interplanetary fit. Requires LSK/PCK furnished; targets without a GM are
    skipped with a log (their fit would fail in `size_chunk` anyway)."""
    sun_mu = float(spiceypy.bodvrd("10", "GM", 1)[1][0])
    out: list[FitCenterCandidate] = []
    for naif_id in SMALL_BODY_TARGET_NAIF_IDS:
        try:
            mu = float(spiceypy.bodvrd(str(naif_id), "GM", 1)[1][0])
        except spiceypy.exceptions.SpiceyError:
            logger.warning("small_body_candidates: no GM for %d, skipped", naif_id)
            continue
        id_type_ordinal, id_value = _resolve_id_for_naif(naif_id)
        out.append(
            FitCenterCandidate(
                naif_id=naif_id,
                id_type_ordinal=id_type_ordinal,
                id_value=id_value,
                barycenter_naif_id=0,
                primary_naif_id=10,
                mu_km3_s2=mu,
                primary_mu_km3_s2=sun_mu,
            )
        )
    return out


def detect_nearest_center(
    candidates: list[FitCenterCandidate],
    probe_naif_id: int,
    t_start_et: float,
    t_end_et: float,
    max_dist_km: float,
    n_samples: int = 9,
) -> FitCenterCandidate | None:
    """Pick the candidate with the smallest minimum distance to the probe
    over the window, or None when none comes within `max_dist_km`.

    Distance-based rather than Hill-based because flyby targets (Lucy's
    Trojans, Arrokoth) have Hill spheres of tens of km that the spacecraft
    never enters — the encounter is still what the zone exists to show.
    Minimum rather than median for the same reason: a Halley-speed flyby is
    inside the radius for hours of a multi-day window. Failed spkpos
    lookups drop the sample; a candidate with no valid sample is out."""
    ets = np.linspace(t_start_et, t_end_et, n_samples)
    best: tuple[float, FitCenterCandidate] | None = None
    for cand in candidates:
        d_min: float | None = None
        for et in ets:
            try:
                rel, _ = spiceypy.spkpos(
                    str(probe_naif_id),
                    float(et),
                    _FIT_CENTER_FRAME,
                    "NONE",
                    str(cand.naif_id),
                )
            except spiceypy.exceptions.SpiceyError:
                continue
            d = float(np.linalg.norm(rel))
            if d_min is None or d < d_min:
                d_min = d
        if (
            d_min is not None
            and d_min < max_dist_km
            and (best is None or d_min < best[0])
        ):
            best = (d_min, cand)
    return best[1] if best is not None else None


def candidates_hash(candidates: list[FitCenterCandidate]) -> str:
    """Stable hash of the candidate set so sidecars invalidate when the set
    changes (new moon downloaded, asteroid added)."""
    payload = ",".join(f"{c.naif_id}:{c.primary_naif_id}" for c in candidates)
    return hashlib.sha256(payload.encode()).hexdigest()[:16]


def fit_center_header_fields(
    chosen: FitCenterCandidate | None,
) -> tuple[int, int]:
    """`(fit_center_id_value, fit_center_id_type)` for `pack_probe_header`.
    Sentinel pair means "stay on the zone's stored fit center"."""
    if chosen is None:
        return MISSING_INT32, MISSING_ID_TYPE
    return chosen.id_value, chosen.id_type_ordinal
