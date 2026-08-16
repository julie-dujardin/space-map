"""Test lat/lng sampling for landed probes against real SPICE data.

For each spacecraft with a landed phase: emits one anchor sample per UTC
midnight plus phase start/end, then sub-samples at `--fine-dt` cadence and
keeps extras wherever displacement since the last kept sample reaches
`--motion-m`. Each sample converts to (lat°, lon°, alt_km) via
`spiceypy.recgeo` (areodetic on Mars, geodetic on Earth, spherical where
f=0). Phases under `--stationary-m` peak displacement collapse to a
single fixed lat/lng.

Reports a summary table per (probe, phase) plus aggregate counts, and can
dump full per-sample data to JSON for inspection.

Run from data/:
    uv run python scripts/probe_landed_test.py
    uv run python scripts/probe_landed_test.py --mission MSL MARS2020
    uv run python scripts/probe_landed_test.py --json out/landed.json
"""

import argparse
import json
import logging
import math
import multiprocessing
import sys
from concurrent.futures import ProcessPoolExecutor, as_completed
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta
from pathlib import Path

import numpy as np
import spiceypy

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "data" / "src"))

from space_map_data.constants.providers import PROVIDERS  # noqa: E402
from space_map_data.download.providers.spice.probes import (  # noqa: E402
    LANDED_MISSIONS_DIR,
)
from space_map_data.export.position.probes.kernels import (  # noqa: E402
    collect_generic_kernels,
)
from space_map_data.probes.probe_id import load_registry as _load_probe_cache  # noqa: E402
from space_map_data.probes.trace import _IAU_FRAME, classify_trace  # noqa: E402
from space_map_data.probes.zones import PLANETARY_ZONES  # noqa: E402
from space_map_data.utils.paths import DOWNLOAD_DIR  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s: %(message)s")
logger = logging.getLogger(__name__)

_S_PER_DAY = 86400.0
_J2000_JD = 2451545.0
_KERNELS_ROOT = DOWNLOAD_DIR / PROVIDERS.SPICE / "kernels"

# Wire-format byte counts for `METHOD_LANDED` (mirrors the constants in
# `space_map_data.export.position.format`). One trailing record per
# (probe, streaming-chunk) overlap, sitting outside the regular sub-chunk
# grid — gated by `PROBE_FLAG_HAS_LANDED_RECORD` in the probe header.
#
#   SUBCHUNK_HDR  (method + reserved + payload_len)                  = 8  B
#   LANDED_HEADER (body_naif + flags + start/end offsets
#                  + lat_ref/lng_ref/alt_ref + sample_count)          = 32 B
#   per-sample    (et_offset + lat_e7 + lng_e7 + alt_mm)             = 16 B
_BYTES_SUBCHUNK_HDR = 8
_BYTES_LANDED_HDR = 32
_BYTES_PER_SAMPLE = 16

# Bodies that lack a directly-matching planetary zone (their `fit_center_naif_id`
# in PLANETARY_ZONES is the parent planet). Map landed-on body → zone key.
_NON_PLANET_BODY_TO_ZONE: dict[int, str] = {
    301: "earth-moon",  # Moon
    606: "saturn",  # Titan (Huygens) — saturn zone covers all Saturn moons
}


def _zone_for_body(body_naif_id: int) -> tuple[str, float]:
    """(zone_key, chunk_days) for the streaming chunks the landed phase will
    land in. Direct match against `fit_center_naif_id` for planet-centric
    bodies (Mars 499 → mars zone, Earth 399 → earth-moon, etc.), explicit
    mapping for moons (Titan, Luna). Falls back to a 1-yr default if a new
    body shows up that we haven't classified yet."""
    for z in PLANETARY_ZONES:
        if z.fit_center_naif_id == body_naif_id:
            return z.key, z.chunk_days
    if body_naif_id in _NON_PLANET_BODY_TO_ZONE:
        key = _NON_PLANET_BODY_TO_ZONE[body_naif_id]
        for z in PLANETARY_ZONES:
            if z.key == key:
                return z.key, z.chunk_days
    return "unknown", 365.25


def _phase_export_size(
    start_et: float,
    end_et: float,
    is_static: bool,
    n_samples: int,
    chunk_days: float,
) -> tuple[int, int]:
    """(total_bytes, n_chunks) the phase contributes to its zone's streaming
    chunks, summed across every chunk it overlaps.

    Static phase: 8-B sub-chunk header + 32-B landed-record header (samples=0)
    in every chunk the phase overlaps. The frontend swaps chunks independently,
    so each chunk must carry the static position on its own.

    Moving phase: same 40-B chunk overhead + 16 B per kept sample. We spread
    `n_samples` evenly across chunks; motion-triggered extras are rare
    (10 over 87 yr for MSL), so the approximation is tight."""
    chunk_s = chunk_days * _S_PER_DAY
    n_chunks = max(1, int(math.ceil((end_et - start_et) / chunk_s)))
    overhead = n_chunks * (_BYTES_SUBCHUNK_HDR + _BYTES_LANDED_HDR)
    if is_static:
        return overhead, n_chunks
    return overhead + n_samples * _BYTES_PER_SAMPLE, n_chunks


def _et_to_iso(et: float) -> str:
    """ET → 'YYYY-MM-DD HH:MM' UTC, for human-readable summary."""
    try:
        return spiceypy.et2utc(et, "ISOC", 0)
    except spiceypy.exceptions.SpiceyError:
        return "?"


@dataclass
class LandedSample:
    """One body-fixed sample. `et` keeps full SPICE precision; `xyz_m`
    drives decimation distance math; lat/lon/alt are display values.
    `is_anchor` flags samples that must always be kept (phase start/end
    and 00:00 UTC daily bookmarks) regardless of motion threshold."""

    et: float
    x_m: float
    y_m: float
    z_m: float
    lat_deg: float
    lon_deg: float
    alt_km: float
    is_anchor: bool = False


@dataclass
class PhaseResult:
    mission: str
    naif_id: int
    probe_label: str  # "MSL/-76" etc.
    body_naif_id: int
    body_frame: str
    start_et: float
    end_et: float
    start_utc: str
    end_utc: str
    duration_days: float
    n_raw: int
    n_decimated: int
    is_stationary: bool
    peak_displacement_m: float
    peak_step_m: float
    total_path_m: float
    zone_key: str  # streaming-chunk zone this phase falls into ("mars" etc.)
    chunk_days: float  # streaming-chunk span for that zone
    n_chunks: int  # streaming chunks the phase overlaps
    export_bytes: int  # METHOD_LANDED bytes added across all chunks (incl. headers)
    lat_min_deg: float
    lat_max_deg: float
    lon_min_deg: float
    lon_max_deg: float
    alt_min_km: float
    alt_max_km: float
    samples: list[LandedSample] = field(default_factory=list)


def _body_radii_and_flattening(body_naif_id: int) -> tuple[float, float]:
    """Equatorial radius (km) and flattening for `recgeo`. Flattening = 0
    for tri-axial bodies whose PCK lists Rx=Ry=Rz (Moon, asteroids); SPICE's
    recgeo collapses to a spherical lat/lon in that case."""
    radii = spiceypy.bodvrd(str(body_naif_id), "RADII", 3)[1]
    re = float(radii[0])
    rp = float(radii[2])
    f = (re - rp) / re if re > 0 else 0.0
    return re, f


def _daily_midnights(start_et: float, end_et: float) -> list[float]:
    """ETs for 00:00:00 UTC on each calendar day strictly between `start_et`
    and `end_et` (excludes both endpoints, which are added separately as
    phase anchors). Uses `str2et` per date so we stay UTC-aligned across
    leap seconds — adding 86400 ET-seconds drifts by ~1 s per ~1.5 yr."""
    start_iso = spiceypy.et2utc(start_et, "ISOC", 0)
    end_iso = spiceypy.et2utc(end_et, "ISOC", 0)
    first_midnight = datetime.fromisoformat(start_iso.split("T")[0]) + timedelta(days=1)
    last_midnight = datetime.fromisoformat(end_iso.split("T")[0])
    out: list[float] = []
    d = first_midnight
    while d <= last_midnight:
        et = spiceypy.str2et(d.strftime("%Y-%m-%dT00:00:00"))
        if start_et < et < end_et:
            out.append(float(et))
        d += timedelta(days=1)
    return out


def _sample_at(
    naif_id: int,
    body_naif_id: int,
    frame: str,
    re: float,
    f: float,
    et: float,
    is_anchor: bool,
) -> LandedSample | None:
    try:
        pos, _ = spiceypy.spkpos(
            str(naif_id), float(et), frame, "NONE", str(body_naif_id)
        )
    except spiceypy.exceptions.SpiceyError:
        return None
    lon_rad, lat_rad, alt_km = spiceypy.recgeo(pos, re, f)
    return LandedSample(
        et=float(et),
        x_m=float(pos[0]) * 1000.0,
        y_m=float(pos[1]) * 1000.0,
        z_m=float(pos[2]) * 1000.0,
        lat_deg=float(np.degrees(lat_rad)),
        lon_deg=float(np.degrees(lon_rad)),
        alt_km=float(alt_km),
        is_anchor=is_anchor,
    )


def _sample_phase(
    naif_id: int,
    body_naif_id: int,
    start_et: float,
    end_et: float,
    fine_dt_s: float,
) -> list[LandedSample]:
    """All fine + anchor samples across the phase, sorted by ET.

    Anchors are (start, every UTC midnight strictly inside, end) — the
    "daily 00:00 UTC" emission requirement. Between anchors we sub-sample
    at `fine_dt_s` cadence so the decimator can detect intra-day motion
    and insert extra samples when displacement crosses the 100 m
    threshold. `is_anchor=True` on those samples lets the decimator
    keep them unconditionally."""
    frame = _IAU_FRAME.get(body_naif_id)
    if frame is None:
        return []
    re, f = _body_radii_and_flattening(body_naif_id)
    if end_et <= start_et:
        return []

    anchor_ets = {start_et, end_et, *_daily_midnights(start_et, end_et)}
    n_fine = max(2, int(math.ceil((end_et - start_et) / fine_dt_s)) + 1)
    fine_ets = np.linspace(start_et, end_et, n_fine).tolist()
    all_ets = sorted(set(fine_ets) | anchor_ets)

    out: list[LandedSample] = []
    for et in all_ets:
        s = _sample_at(naif_id, body_naif_id, frame, re, f, et, et in anchor_ets)
        if s is not None:
            out.append(s)
    return out


def _decimate(samples: list[LandedSample], motion_m: float) -> list[LandedSample]:
    """Keep every anchor sample (phase start/end + 00:00 UTC midnights),
    plus any intra-day fine sample whose displacement since the last kept
    sample reaches `motion_m`."""
    if not samples:
        return []
    kept: list[LandedSample] = [samples[0]]
    last = samples[0]
    for s in samples[1:]:
        if s.is_anchor:
            kept.append(s)
            last = s
            continue
        dx = s.x_m - last.x_m
        dy = s.y_m - last.y_m
        dz = s.z_m - last.z_m
        if math.sqrt(dx * dx + dy * dy + dz * dz) >= motion_m:
            kept.append(s)
            last = s
    return kept


def _summarize(
    mission: str,
    naif_id: int,
    probe_label: str,
    body_naif_id: int,
    phase_start_et: float,
    phase_end_et: float,
    fine_samples: list[LandedSample],
    motion_m: float,
    stationary_m: float,
    capture_samples: bool,
) -> PhaseResult | None:
    if not fine_samples:
        return None
    first = fine_samples[0]
    peak_disp = 0.0
    peak_step = 0.0
    total_path = 0.0
    prev = first
    for s in fine_samples[1:]:
        dxf = s.x_m - first.x_m
        dyf = s.y_m - first.y_m
        dzf = s.z_m - first.z_m
        peak_disp = max(peak_disp, math.sqrt(dxf * dxf + dyf * dyf + dzf * dzf))
        dxp = s.x_m - prev.x_m
        dyp = s.y_m - prev.y_m
        dzp = s.z_m - prev.z_m
        step = math.sqrt(dxp * dxp + dyp * dyp + dzp * dzp)
        peak_step = max(peak_step, step)
        total_path += step
        prev = s

    is_stationary = peak_disp < stationary_m
    if is_stationary:
        kept = [first]
        # Static probes only "moved" via frame-conversion noise — each step is
        # a few cm, sums to tens of km over decades of runout. Reporting that
        # as path makes static lines look like 30 km drives. Zero it out;
        # peak_displacement_m still tells the real noise floor.
        total_path = 0.0
        peak_step = 0.0
    else:
        kept = _decimate(fine_samples, motion_m)

    lats = [s.lat_deg for s in fine_samples]
    lons = [s.lon_deg for s in fine_samples]
    alts = [s.alt_km for s in fine_samples]

    zone_key, chunk_days = _zone_for_body(body_naif_id)
    export_bytes, n_chunks = _phase_export_size(
        start_et=phase_start_et,
        end_et=phase_end_et,
        is_static=is_stationary,
        n_samples=len(kept),
        chunk_days=chunk_days,
    )

    return PhaseResult(
        mission=mission,
        naif_id=naif_id,
        probe_label=probe_label,
        body_naif_id=body_naif_id,
        body_frame=_IAU_FRAME.get(body_naif_id, "?"),
        start_et=phase_start_et,
        end_et=phase_end_et,
        start_utc=_et_to_iso(phase_start_et),
        end_utc=_et_to_iso(phase_end_et),
        duration_days=(phase_end_et - phase_start_et) / _S_PER_DAY,
        n_raw=len(fine_samples),
        n_decimated=len(kept),
        is_stationary=is_stationary,
        peak_displacement_m=peak_disp,
        peak_step_m=peak_step,
        total_path_m=total_path,
        zone_key=zone_key,
        chunk_days=chunk_days,
        n_chunks=n_chunks,
        export_bytes=export_bytes,
        lat_min_deg=min(lats),
        lat_max_deg=max(lats),
        lon_min_deg=min(lons),
        lon_max_deg=max(lons),
        alt_min_km=min(alts),
        alt_max_km=max(alts),
        samples=kept if capture_samples else [],
    )


# ── Multiprocessing wiring (mirrors classify.classify_pass) ──────────────


def _worker_init(kernel_paths: list[str]) -> None:
    for p in kernel_paths:
        spiceypy.furnsh(p)


def _worker(
    mission_name: str,
    kernel_paths: list[str],
    naif_id: int,
    probe_label: str,
    fine_dt_s: float,
    motion_m: float,
    stationary_m: float,
    capture_samples: bool,
) -> list[dict]:
    """Run classify_trace then sample/decimate each landed phase.

    Returns a list of `PhaseResult` dicts (jsonable) so the parent can
    aggregate without pickling dataclass classes.
    """
    for k in kernel_paths:
        spiceypy.furnsh(k)
    try:
        result = classify_trace(naif_id, kernel_paths)
        out: list[dict] = []
        for phase in result.landed_phases:
            fine = _sample_phase(
                naif_id, phase.body_naif_id, phase.start_et, phase.end_et, fine_dt_s
            )
            summary = _summarize(
                mission=mission_name,
                naif_id=naif_id,
                probe_label=probe_label,
                body_naif_id=phase.body_naif_id,
                phase_start_et=phase.start_et,
                phase_end_et=phase.end_et,
                fine_samples=fine,
                motion_m=motion_m,
                stationary_m=stationary_m,
                capture_samples=capture_samples,
            )
            if summary is not None:
                out.append(asdict(summary))
        return out
    finally:
        for k in kernel_paths:
            spiceypy.unload(k)


def _enumerate_landed_probes() -> list[tuple[Path, list[Path], int]]:
    """Walk `LANDED_MISSIONS_DIR/*` and return one entry per
    `(mission_dir, kernel_list, naif)`.

    Picks the *most informative* NAIF per mission: prefer the spacecraft-
    body NAIF (`-76` for MSL etc.) when its trajectory is covered by a
    `surf_rover_loc_*` kernel, else fall back to the landing-site NAIF
    (`-76900` pattern: `spacecraft_naif*1000 - 900` in absolute terms).
    For MER neither rover has a trajectory kernel — only the static
    landing site — so the LS NAIF is the only option.

    Prefers the per-mission `_index.json`. Falls back to globbing +
    spkobj when the index is missing.
    """
    out: list[tuple[Path, list[Path], int]] = []
    if not LANDED_MISSIONS_DIR.exists():
        return out
    cache = _load_probe_cache()
    for mdir in sorted(LANDED_MISSIONS_DIR.iterdir()):
        if not mdir.is_dir():
            continue
        idx_path = mdir / "_index.json"
        if idx_path.exists():
            idx = json.loads(idx_path.read_text())
            kernels = [mdir / f["name"] for f in idx.get("files", [])]
            kernels = [k for k in kernels if k.exists()]
            targets = sorted(
                int(s) for s in idx.get("targets", {}) if -999_999_999 < int(s) < 0
            )
        else:
            kernels = sorted(p for p in mdir.iterdir() if p.suffix.lower() == ".bsp")
            target_set: set[int] = set()
            for k in kernels:
                try:
                    cell = spiceypy.cell_int(1000)
                    spiceypy.spkobj(str(k), cell)
                    for i in range(spiceypy.card(cell)):
                        target_set.add(int(cell[i]))
                except spiceypy.exceptions.SpiceyError:
                    continue
            targets = sorted(t for t in target_set if t < 0)
        if not kernels or not targets:
            continue
        spacecraft_targets = {t for t in targets if f"{mdir.name}/{t}" in cache}
        # Landing-site NAIFs (`-X900` from `spacecraft_naif*1000 - 900`) only
        # picked up when no matching spacecraft-body trajectory is present —
        # avoids double-emitting per (probe, ls) pair for missions that have
        # both (MSL/MARS2020 keep their rover-body trace).
        emitted_per_probe: set[int] = set()
        for sc in sorted(spacecraft_targets):
            out.append((mdir, kernels, sc))
            emitted_per_probe.add(sc)
        for t in sorted(targets):
            if t in spacecraft_targets:
                continue
            sc_candidate = -((-t) // 1000) if (-t) % 1000 == 900 else None
            if sc_candidate is None or sc_candidate in emitted_per_probe:
                continue
            if f"{mdir.name}/{sc_candidate}" in cache:
                out.append((mdir, kernels, t))
                emitted_per_probe.add(sc_candidate)
    return out


# ── Driver ──────────────────────────────────────────────────────────────


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
    p.add_argument(
        "--mission",
        nargs="+",
        help="restrict to one or more mission folders by name (case-insensitive)",
    )
    p.add_argument(
        "--fine-dt",
        type=float,
        default=3600.0,
        help="fine-sample cadence within a landed phase, seconds (default: 3600)",
    )
    p.add_argument(
        "--motion-m",
        type=float,
        default=100.0,
        help="emit a new decimated sample after this many meters of motion "
        "(default: 100). Daily 00:00 UTC anchors are always emitted "
        "regardless — this only controls intra-day refinement.",
    )
    p.add_argument(
        "--stationary-m",
        type=float,
        default=100.0,
        help="peak displacement under this is treated as a fixed lat/lng "
        "(default: 100, matches --motion-m — anything smaller would be "
        "frame-conversion noise that wouldn't trigger a decimated sample "
        "anyway, e.g. Phoenix's 93m drift over 91 years of runout)",
    )
    p.add_argument(
        "--workers",
        type=int,
        default=max(1, min(8, multiprocessing.cpu_count() // 2)),
        help="parallel worker processes (default: half of cpu_count, capped at 8)",
    )
    p.add_argument(
        "--json",
        type=Path,
        help="write per-phase results (including all decimated samples) to this file",
    )
    return p.parse_args()


def main() -> int:
    args = _parse_args()
    if not LANDED_MISSIONS_DIR.exists():
        print(f"No landed-missions dir at {LANDED_MISSIONS_DIR}")
        return 1

    probes_raw = _enumerate_landed_probes()
    if args.mission:
        wanted = {m.upper() for m in args.mission}
        probes_raw = [t for t in probes_raw if t[0].name.upper() in wanted]
    if not probes_raw:
        print("No probes match the filter.")
        return 1

    lsk_pck, generic_spk = collect_generic_kernels(_KERNELS_ROOT)
    init_paths = [str(p) for p in (lsk_pck + generic_spk)]
    logger.info(
        "Scanning %d probes across %d workers for landed phases…",
        len(probes_raw),
        args.workers,
    )

    phase_results: list[dict] = []
    with ProcessPoolExecutor(
        max_workers=args.workers,
        initializer=_worker_init,
        initargs=(init_paths,),
    ) as ex:
        # The parent process didn't furnish LSK either, but we need it for
        # the et2utc call in _et_to_iso the *parent* runs after. Load here.
        for p in lsk_pck:
            spiceypy.furnsh(str(p))
        futures = {}
        for mdir, kernels, naif_id in probes_raw:
            label = f"{mdir.name}/{naif_id}"
            kpaths = [str(k) for k in kernels]
            fut = ex.submit(
                _worker,
                mdir.name,
                kpaths,
                naif_id,
                label,
                args.fine_dt,
                args.motion_m,
                args.stationary_m,
                args.json is not None,
            )
            futures[fut] = (mdir.name, naif_id)
        for fut in as_completed(futures):
            mission, naif_id = futures[fut]
            try:
                results = fut.result()
            except Exception:
                logger.exception("Worker failed for %s/%d", mission, naif_id)
                continue
            for r in results:
                phase_results.append(r)
                logger.info(
                    "  %-20s naif=%-7d body=%-3d %s..%s %s %d→%d samples disp=%.1fm path=%.1fm",
                    r["mission"],
                    r["naif_id"],
                    r["body_naif_id"],
                    r["start_utc"][:10],
                    r["end_utc"][:10],
                    "STATIC " if r["is_stationary"] else "MOVING ",
                    r["n_raw"],
                    r["n_decimated"],
                    r["peak_displacement_m"],
                    r["total_path_m"],
                )

    if not phase_results:
        print("No landed phases found.")
        return 0

    _print_summary(phase_results)
    if args.json:
        args.json.parent.mkdir(parents=True, exist_ok=True)
        args.json.write_text(json.dumps(phase_results, indent=2))
        logger.info("Wrote %d phase records to %s", len(phase_results), args.json)
    return 0


def _print_summary(results: list[dict]) -> None:
    """Print a per-phase table sorted by mission + start time, then a
    body-aggregate tally.

    `B/chunk` is the projected `METHOD_LANDED` bytes added to *each*
    streaming chunk this phase touches — the relevant cost since these
    sub-chunk records bolt onto the existing per-chunk file the
    trajectory pipeline already writes.

      * Static phase: 8-B sub-chunk header + 20-B landed-record = 28 B/chunk
        (every chunk the phase spans pays this; the rover sits in place).
      * Moving phase: 32 B header + 16 B per kept sample in that chunk;
        with ~30 daily samples/chunk on Mars that's ~512 B/chunk avg.
    """
    print()
    print(
        f"{'mission':<14} {'naif':>6} {'body':>5} {'start':>10} {'end':>10} "
        f"{'days':>7} {'stat?':>6} {'disp_m':>9} {'path_m':>10} "
        f"{'lat°':>8} {'lon°':>9} {'alt_km':>8} {'n_raw':>6} {'n_dec':>5} "
        f"{'zone':>11} {'chunks':>7} {'B/chunk':>9}"
    )
    print("-" * 175)
    for r in sorted(results, key=lambda x: (x["mission"], x["start_et"])):
        b_per_chunk = r["export_bytes"] / max(1, r["n_chunks"])
        print(
            f"{r['mission'][:14]:<14} {r['naif_id']:>6} {r['body_naif_id']:>5} "
            f"{r['start_utc'][:10]:>10} {r['end_utc'][:10]:>10} "
            f"{r['duration_days']:>7.1f} "
            f"{'yes' if r['is_stationary'] else 'no':>6} "
            f"{r['peak_displacement_m']:>9.1f} {r['total_path_m']:>10.1f} "
            f"{r['lat_min_deg']:>8.3f} {r['lon_min_deg']:>9.3f} "
            f"{r['alt_min_km']:>8.3f} {r['n_raw']:>6} {r['n_decimated']:>5} "
            f"{r['zone_key']:>11} {r['n_chunks']:>7} "
            f"{b_per_chunk:>9.0f}"
        )

    by_body: dict[int, list[dict]] = {}
    for r in results:
        by_body.setdefault(r["body_naif_id"], []).append(r)
    print()
    print("by body (avg B/chunk = sum bytes ÷ sum chunks across phases):")
    for body, rows in sorted(by_body.items()):
        n_static = sum(1 for r in rows if r["is_stationary"])
        n_moving = len(rows) - n_static
        n_kept = sum(r["n_decimated"] for r in rows)
        total_chunks = sum(r["n_chunks"] for r in rows)
        total_bytes = sum(r["export_bytes"] for r in rows)
        avg_b = total_bytes / max(1, total_chunks)
        print(
            f"  body={body:>3}  phases={len(rows):>3}  static={n_static:>3}  "
            f"moving={n_moving:>3}  samples={n_kept:>6}  "
            f"chunks={total_chunks:>5}  avg B/chunk={avg_b:>5.0f}"
        )


if __name__ == "__main__":
    sys.exit(main())
