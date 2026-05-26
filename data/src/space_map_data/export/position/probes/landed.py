"""Landed-phase fit pipeline.

One `LandedFit` per (probe, chunk) overlap; emitted as a trailing
`METHOD_LANDED` record after the probe's flying sub-chunks. See
`format.pack_landed_payload` for the wire layout.
"""

import math
from dataclasses import dataclass
from datetime import datetime, timedelta

import numpy as np
import spiceypy

from space_map_data.probes.trace import _IAU_FRAME

_LANDED_FINE_DT_S = 3600.0  # 1-hour sub-sampling between daily anchors
_LANDED_MOTION_M = 100.0
_LANDED_STATIONARY_M = 100.0


@dataclass(frozen=True)
class LandedFit:
    """Sampled landed-phase data for one streaming chunk."""

    body_naif_id: int
    is_static: bool
    start_offset_s: int  # seconds from chunk_start_jd
    end_offset_s: int
    lat_ref_deg: float
    lng_ref_deg: float
    alt_ref_m: float
    samples: list[tuple[int, float, float, float]]
    # (et_offset_s_from_chunk_start, lat_deg, lng_deg, alt_m)
    peak_displacement_m: float


def _daily_midnight_ets(t_start_et: float, t_end_et: float) -> list[float]:
    """ETs at 00:00:00 UTC each calendar day strictly inside (t_start_et,
    t_end_et). Uses `str2et` per date so we stay UTC-aligned across leap
    seconds (a 365 × 86400 ET sec increment drifts ~1 s per ~1.5 yr)."""
    if t_end_et <= t_start_et:
        return []
    start_iso = spiceypy.et2utc(t_start_et, "ISOC", 0)
    end_iso = spiceypy.et2utc(t_end_et, "ISOC", 0)
    first = datetime.fromisoformat(start_iso.split("T")[0]) + timedelta(days=1)
    last = datetime.fromisoformat(end_iso.split("T")[0])
    out: list[float] = []
    d = first
    while d <= last:
        et = float(spiceypy.str2et(d.strftime("%Y-%m-%dT00:00:00")))
        if t_start_et < et < t_end_et:
            out.append(et)
        d += timedelta(days=1)
    return out


def _body_radii_and_flattening(body_naif_id: int) -> tuple[float, float]:
    """Equatorial radius (km) and flattening for `recgeo`. Flattening = 0
    for tri-axial bodies whose PCK lists Rx=Ry=Rz (Moon, asteroids); SPICE's
    recgeo collapses to a spherical lat/lon in that case."""
    radii = spiceypy.bodvrd(str(body_naif_id), "RADII", 3)[1]
    re = float(radii[0])
    rp = float(radii[2])
    f = (re - rp) / re if re > 0 else 0.0
    return re, f


def fit_landed_chunk(
    probe_naif_id: int,
    body_naif_id: int,
    chunk_start_et: float,
    c_start_et: float,
    c_end_et: float,
) -> LandedFit | None:
    """Sample the probe's landed phase within `[c_start_et, c_end_et]`,
    decimate to (00:00 UTC daily anchors + intra-day samples whose motion
    crosses 100 m), pack as a `LandedFit`. Mirrors the validation logic in
    `data/scripts/probe_landed_test.py`.

    Returns None if the body has no IAU frame (asteroid/comet — not yet
    supported) or if every `spkpos` lookup fails in the window."""
    frame = _IAU_FRAME.get(body_naif_id)
    if frame is None:
        return None
    try:
        re, f = _body_radii_and_flattening(body_naif_id)
    except spiceypy.exceptions.SpiceyError:
        return None

    anchor_set = {c_start_et, c_end_et, *_daily_midnight_ets(c_start_et, c_end_et)}
    n_fine = max(2, int(math.ceil((c_end_et - c_start_et) / _LANDED_FINE_DT_S)) + 1)
    fine_ets = np.linspace(c_start_et, c_end_et, n_fine).tolist()
    all_ets = sorted(anchor_set | set(fine_ets))

    fine_samples: list[tuple[float, np.ndarray, float, float, float]] = []
    for et in all_ets:
        try:
            pos, _ = spiceypy.spkpos(
                str(probe_naif_id), float(et), frame, "NONE", str(body_naif_id)
            )
        except spiceypy.exceptions.SpiceyError:
            continue
        lon_rad, lat_rad, alt_km = spiceypy.recgeo(pos, re, f)
        fine_samples.append(
            (
                float(et),
                np.asarray(pos, dtype=np.float64) * 1000.0,  # body-fixed XYZ in metres
                float(np.degrees(lat_rad)),
                float(np.degrees(lon_rad)),
                float(alt_km) * 1000.0,  # alt in metres for the wire format
            )
        )
    if not fine_samples:
        return None

    first_et, first_xyz_m, first_lat, first_lng, first_alt_m = fine_samples[0]
    peak_disp = 0.0
    for et, xyz_m, _lat, _lng, _alt in fine_samples[1:]:
        d = float(np.linalg.norm(xyz_m - first_xyz_m))
        if d > peak_disp:
            peak_disp = d

    is_static = peak_disp < _LANDED_STATIONARY_M

    kept_samples: list[tuple[int, float, float, float]] = []
    if not is_static:
        last_xyz = first_xyz_m
        # Anchors and motion-triggered samples (skip the first; it becomes
        # the reference and is implied by the lat_ref / lng_ref fields).
        for et, xyz_m, lat, lng, alt_m in fine_samples[1:]:
            is_anchor = et in anchor_set
            d = float(np.linalg.norm(xyz_m - last_xyz))
            if is_anchor or d >= _LANDED_MOTION_M:
                offset_s = int(round(et - chunk_start_et))
                kept_samples.append((offset_s, lat, lng, alt_m))
                last_xyz = xyz_m

    return LandedFit(
        body_naif_id=body_naif_id,
        is_static=is_static,
        start_offset_s=int(round(c_start_et - chunk_start_et)),
        end_offset_s=int(round(c_end_et - chunk_start_et)),
        lat_ref_deg=first_lat,
        lng_ref_deg=first_lng,
        alt_ref_m=first_alt_m,
        samples=kept_samples,
        peak_displacement_m=peak_disp,
    )
