"""Horizons → synthetic SPK kernels.

For spacecraft Horizons can compute state vectors for but JPL/NAIF doesn't
publish a binary SPK for (~200 in the Horizons MB list), fetch VECTORS at an
adaptive cadence and pack them into a binary SPK locally via `spkw13`.

The cache is the source of truth: raw Horizons CSV per `(naif_id, window,
cadence)`. SPK files are derived artifacts, fully regenerable offline. Refresh
is gated by Horizons' `Revised :` header so repeated runs only re-hit the API
when the spacecraft solution actually changes.

Auto-tuning: a 7-day coarse pass over the full coverage feeds a Hill-sphere
proximity check; sub-windows where the spacecraft is within
`REFINE_HILL_FACTOR × R_hill` of a major body get re-fetched at 1-hour cadence.
"""

import json
import logging
import re
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

import httpx
import numpy as np
import orjson
import spiceypy

from space_map_data.constants.providers import PROVIDERS
from space_map_data.download.downloader import DownloadError, Downloader
from space_map_data.utils.paths import DOWNLOAD_DIR

logger = logging.getLogger(__name__)

HORIZONS_URL = "https://ssd.jpl.nasa.gov/api/horizons.api"

# Raw-CSV cache root. Each spacecraft lives under
# `<SYNTH_CACHE_ROOT>/<naif_id>/{meta.json,coarse_*.csv,refine_*.csv}`. SPK
# files are derived artifacts and land in `SYNTH_KERNELS_DIR` (under the
# `missions/` tree so the existing ingest walker finds them).
SYNTH_CACHE_ROOT = DOWNLOAD_DIR / "spice" / "horizons-synth"
SYNTH_KERNELS_DIR = DOWNLOAD_DIR / "spice" / "kernels" / "missions" / "HORIZONS-SYNTH"
# Back-compat alias for the smoke script and earlier callers.
SYNTH_ROOT = SYNTH_CACHE_ROOT

REFINE_STEP = "1 h"


def _coarse_step_for(span_days: int) -> str:
    """Pick a coarse-pass cadence that yields ≥ degree+1=8 samples while
    keeping the response small for long-lived spacecraft. Voyager-class
    decades-long missions get 7d; ~year missions get 1d; sub-2-month
    missions go straight to 1h and skip the refinement pass entirely."""
    if span_days <= 60:
        return "1 h"
    if span_days <= 365:
        return "1 d"
    return "7 d"


# Within this many Hill radii of any major body → refine to REFINE_STEP.
REFINE_HILL_FACTOR = 5.0
# Pad each refinement window so the approach and departure tails are
# resampled at the tight cadence too (avoids sharp 7d→1h transitions).
REFINE_PAD_DAYS = 7.0

# Major-body NAIF IDs and Hill-sphere radii in km. We use planet *barycenter*
# NAIF IDs for the outer planets (4, 5, 6, 7, 8) because de440.bsp only
# contains the barycenters of Mars onwards, not the planet bodies themselves
# (which need the per-system satellite kernels). The barycenter coincides
# with the planet to within a few thousand km for the outer planets — fine
# for proximity-bucket detection. Mercury/Venus barycenter == the planet
# itself (no moons) so we use 199 and 299 directly. Earth and Moon get their
# own IDs because they're separated by ~384 000 km and we want to detect
# proximity to either body, not just to the Earth-Moon barycenter.
MAJOR_BODY_HILL_KM: dict[int, float] = {
    199: 2.20e5,  # Mercury
    299: 1.01e6,  # Venus
    399: 1.50e6,  # Earth
    301: 6.61e4,  # Moon (Earth-centred Hill sphere)
    4: 1.08e6,  # Mars barycenter
    5: 5.31e7,  # Jupiter barycenter
    6: 6.50e7,  # Saturn barycenter
    7: 7.00e7,  # Uranus barycenter
    8: 1.16e8,  # Neptune barycenter
}

# Wide-span probe to detect actual coverage window. Horizons returns
# whatever overlap exists with the requested span; we trim from the returned
# first/last sample timestamps.
WINDOW_PROBE_START = "1957-10-04"  # Sputnik 1 launch — earliest plausible
WINDOW_PROBE_END = "2100-01-01"

_J2000_DATE = datetime(2000, 1, 1, 12, 0, 0, tzinfo=timezone.utc)


@dataclass
class Sample:
    et: float
    state: tuple[float, float, float, float, float, float]


@dataclass
class HorizonsObj:
    name: str
    revised: str  # raw "Mon DD, YYYY" string as printed by Horizons
    raw: str


# ---------------------------------------------------------------------------
# Time helpers
# ---------------------------------------------------------------------------


def _jd_to_iso(jd: float) -> str:
    """Convert JD-TDB → ISO calendar date (UTC, ±69s precision)."""
    dt = _J2000_DATE + timedelta(seconds=(jd - 2451545.0) * 86400.0)
    return dt.date().isoformat()


def _et_to_jd(et: float) -> float:
    return et / 86400.0 + 2451545.0


# ---------------------------------------------------------------------------
# Horizons fetch + parse
# ---------------------------------------------------------------------------


def _parse_horizons_csv(text: str) -> list[Sample]:
    m = re.search(r"\$\$SOE\s*\n(.*?)\n\$\$EOE", text, re.S)
    if not m:
        return []
    rows: list[Sample] = []
    for line in m.group(1).strip().splitlines():
        parts = [p.strip() for p in line.split(",")]
        if len(parts) < 8:
            continue
        try:
            jdtdb = float(parts[0])
            x = float(parts[2])
            y = float(parts[3])
            z = float(parts[4])
            vx = float(parts[5])
            vy = float(parts[6])
            vz = float(parts[7])
        except ValueError:
            continue
        et = (jdtdb - 2451545.0) * 86400.0
        rows.append(Sample(et, (x, y, z, vx, vy, vz)))
    return rows


def fetch_obj_data(client: httpx.Client, naif_id: int) -> HorizonsObj:
    """Probe Horizons for the spacecraft name + `Revised :` date."""
    resp = client.get(
        HORIZONS_URL,
        params={
            "format": "json",
            "COMMAND": f"'{naif_id}'",
            "OBJ_DATA": "YES",
            "MAKE_EPHEM": "NO",
        },
        timeout=60.0,
    )
    resp.raise_for_status()
    text = resp.json().get("result", "")
    rev_m = re.search(r"^\s*Revised\s*:\s*([A-Za-z]{3}\s+\d{1,2},\s*\d{4})", text, re.M)
    name_m = re.search(
        r"^\s*Revised\s*:\s*[A-Za-z]{3}\s+\d{1,2},\s*\d{4}\s+(.+?)\s+-?\d+\s*$",
        text,
        re.M,
    )
    return HorizonsObj(
        name=name_m.group(1).strip() if name_m else f"NAIF {naif_id}",
        revised=rev_m.group(1) if rev_m else "unknown",
        raw=text,
    )


def fetch_vectors(
    client: httpx.Client,
    naif_id: int,
    start: str,
    stop: str,
    step: str,
    *,
    timeout: float = 180.0,
) -> str:
    """Raw CSV text from Horizons VECTORS for `[start, stop]` at `step`."""
    resp = client.get(
        HORIZONS_URL,
        params={
            "format": "text",
            "COMMAND": f"'{naif_id}'",
            "OBJ_DATA": "NO",
            "MAKE_EPHEM": "YES",
            "EPHEM_TYPE": "VECTORS",
            "CENTER": "'@0'",
            "START_TIME": f"'{start}'",
            "STOP_TIME": f"'{stop}'",
            "STEP_SIZE": f"'{step}'",
            "REF_PLANE": "FRAME",
            "REF_SYSTEM": "J2000",
            "OUT_UNITS": "KM-S",
            "VEC_TABLE": "2",
            "CSV_FORMAT": "YES",
        },
        timeout=timeout,
    )
    resp.raise_for_status()
    return resp.text


def _fetch_vectors_chunked(
    client: httpx.Client,
    naif_id: int,
    start_iso: str,
    stop_iso: str,
    step: str,
    chunk_days: int = 365 * 5,
) -> str:
    """Fetch a long span in ≤chunk_days slices; concatenate the CSVs.

    The concatenated text has multiple $$SOE/$$EOE blocks; `_parse_horizons_csv`
    only reads the first block per call, so callers should re-parse each chunk
    separately if they need samples from all of them.
    """
    start = datetime.fromisoformat(start_iso).date()
    stop = datetime.fromisoformat(stop_iso).date()
    pieces: list[str] = []
    cur = start
    while cur < stop:
        nxt = min(stop, cur + timedelta(days=chunk_days))
        pieces.append(
            fetch_vectors(client, naif_id, cur.isoformat(), nxt.isoformat(), step)
        )
        cur = nxt
    return "\n".join(pieces)


def _parse_chunks(text: str) -> list[Sample]:
    """Concatenated multi-chunk CSV → flat sample list (dedup adjacent epochs)."""
    out: list[Sample] = []
    last_et: float | None = None
    for block in re.findall(r"\$\$SOE\s*\n(.*?)\n\$\$EOE", text, re.S):
        for s in _parse_horizons_csv(f"$$SOE\n{block}\n$$EOE"):
            if last_et is not None and s.et == last_et:
                continue
            out.append(s)
            last_et = s.et
    return out


_NO_EPHEM_PRIOR_RE = re.compile(
    r'No ephemeris for target "[^"]+" prior to A\.D\. '
    r"(\d{4}-[A-Z]{3}-\d{2})",
)
_NO_EPHEM_AFTER_RE = re.compile(
    r'No ephemeris for target "[^"]+" after A\.D\. '
    r"(\d{4}-[A-Z]{3}-\d{2})",
)
_MONTHS = {
    "JAN": "01",
    "FEB": "02",
    "MAR": "03",
    "APR": "04",
    "MAY": "05",
    "JUN": "06",
    "JUL": "07",
    "AUG": "08",
    "SEP": "09",
    "OCT": "10",
    "NOV": "11",
    "DEC": "12",
}


def _horizons_date_to_iso(s: str) -> str:
    y, m, d = s.split("-")
    return f"{y}-{_MONTHS[m]}-{d}"


def detect_window(client: httpx.Client, naif_id: int) -> tuple[str, str]:
    """Find Horizons coverage by probing wide and parsing "prior to / after"
    error messages. Step is adaptive: small enough to fit short-coverage
    spacecraft (Tianwen-1 ~6 months, Apollo S-IVB ~20 days), large enough
    to keep the response small over a 140-year wide span. We also apply both
    clamps in one round when Horizons returns both errors at once.
    """
    start = WINDOW_PROBE_START
    end = WINDOW_PROBE_END
    for _ in range(4):
        span_days = (
            datetime.fromisoformat(end).date() - datetime.fromisoformat(start).date()
        ).days
        step_days = max(1, span_days // 20)
        step = f"{step_days} d"
        text = fetch_vectors(client, naif_id, start, end, step)
        samples = _parse_horizons_csv(text)
        if samples:
            return (
                _jd_to_iso(_et_to_jd(samples[0].et)),
                _jd_to_iso(_et_to_jd(samples[-1].et)),
            )
        m_prior = _NO_EPHEM_PRIOR_RE.search(text)
        m_after = _NO_EPHEM_AFTER_RE.search(text)
        progressed = False
        if m_prior:
            # Horizons quotes the launch instant (e.g. 1977-Aug-20 15:32:32 TDB);
            # asking for the date alone reads as midnight, still before launch.
            # Bumping +1d places us safely after.
            boundary = datetime.fromisoformat(
                _horizons_date_to_iso(m_prior.group(1))
            ).date() + timedelta(days=1)
            start = boundary.isoformat()
            logger.info("naif %d: clamping START → %s (prior-to error)", naif_id, start)
            progressed = True
        if m_after:
            boundary = datetime.fromisoformat(
                _horizons_date_to_iso(m_after.group(1))
            ).date() - timedelta(days=1)
            end = boundary.isoformat()
            logger.info("naif %d: clamping STOP → %s (after error)", naif_id, end)
            progressed = True
        if progressed:
            continue
        snippet = text[-400:].strip()
        raise RuntimeError(
            f"naif {naif_id}: window-probe returned no samples and no "
            f"parseable boundary message: ...{snippet!r}"
        )
    raise RuntimeError(f"naif {naif_id}: window-detect did not converge after 4 rounds")


# ---------------------------------------------------------------------------
# Refinement (auto-tune)
# ---------------------------------------------------------------------------


def _identify_refinement_windows(
    samples: list[Sample],
    get_body_pos,
    *,
    coverage_start_iso: str,
    coverage_end_iso: str,
) -> list[tuple[str, str]]:
    """Coarse samples + per-body Hill-radius proximity check → 1h windows.

    `get_body_pos(naif_id, et)` returns the body's SSB-relative position (km).
    Returned (start, end) iso pairs are clamped to the spacecraft's coverage
    window minus a 1-day margin so Horizons doesn't reject the fetch as
    out-of-coverage.
    """
    if not samples:
        return []
    cov_start = datetime.fromisoformat(coverage_start_iso).date() + timedelta(days=1)
    cov_end = datetime.fromisoformat(coverage_end_iso).date() - timedelta(days=1)
    n = len(samples)
    near = np.zeros(n, dtype=bool)
    for i, s in enumerate(samples):
        spc = np.asarray(s.state[:3])
        for body_id, hill_km in MAJOR_BODY_HILL_KM.items():
            try:
                body_pos = np.asarray(get_body_pos(body_id, s.et))
            except spiceypy.exceptions.SpiceyError:
                continue
            if np.linalg.norm(spc - body_pos) < REFINE_HILL_FACTOR * hill_km:
                near[i] = True
                break

    windows: list[tuple[str, str]] = []
    i = 0
    while i < n:
        if not near[i]:
            i += 1
            continue
        j = i
        while j < n and near[j]:
            j += 1
        a_jd = _et_to_jd(samples[i].et) - REFINE_PAD_DAYS
        b_jd = _et_to_jd(samples[j - 1].et) + REFINE_PAD_DAYS
        a = max(cov_start, datetime.fromisoformat(_jd_to_iso(a_jd)).date())
        b = min(cov_end, datetime.fromisoformat(_jd_to_iso(b_jd)).date())
        if a < b:
            windows.append((a.isoformat(), b.isoformat()))
        i = j
    return windows


def _furnish_planets() -> list[Path]:
    """Furnish lsk + de440 so spkpos can return planet positions. Returns the
    paths so the caller can `spiceypy.unload` them when done."""
    kernels_root = DOWNLOAD_DIR / "spice" / "kernels"
    paths = [
        kernels_root / "lsk" / "naif0012.tls",
        kernels_root / "spk" / "planets" / "de440.bsp",
    ]
    for p in paths:
        spiceypy.furnsh(str(p))
    return paths


# ---------------------------------------------------------------------------
# Fetch loop (cache aware)
# ---------------------------------------------------------------------------


def fetch_one(client: httpx.Client, naif_id: int, *, force: bool = False) -> dict:
    """Probe + fetch coarse + auto-refine → write cache. Returns meta dict.

    Cache layout:
      {SYNTH_ROOT}/{naif_id}/meta.json
      {SYNTH_ROOT}/{naif_id}/coarse_{start}_{end}_7d.csv
      {SYNTH_ROOT}/{naif_id}/refine_{start}_{end}_1h.csv  (per window)

    Skip rule: if `meta.json` already records the current Horizons `Revised :`
    date, all subsequent network work is suppressed.
    """
    cache_dir = SYNTH_CACHE_ROOT / str(naif_id)
    cache_dir.mkdir(parents=True, exist_ok=True)
    meta_path = cache_dir / "meta.json"

    obj = fetch_obj_data(client, naif_id)
    logger.info("naif %d → %s (revised %s)", naif_id, obj.name, obj.revised)

    if not force and meta_path.exists():
        prev = orjson.loads(meta_path.read_bytes())
        if prev.get("revised") == obj.revised:
            logger.info(
                "naif %d: cache up to date (revised %s), skipping fetch",
                naif_id,
                obj.revised,
            )
            return prev

    win_start, win_end = detect_window(client, naif_id)
    span_days = (
        datetime.fromisoformat(win_end).date()
        - datetime.fromisoformat(win_start).date()
    ).days
    coarse_step = _coarse_step_for(span_days)
    skip_refine = coarse_step == "1 h"
    logger.info(
        "naif %d window: %s → %s (%dd, coarse=%s%s)",
        naif_id,
        win_start,
        win_end,
        span_days,
        coarse_step,
        "; refinement skipped" if skip_refine else "",
    )

    coarse_tag = coarse_step.replace(" ", "")
    coarse_name = f"coarse_{win_start}_{win_end}_{coarse_tag}.csv"
    coarse_path = cache_dir / coarse_name
    coarse_text = _fetch_vectors_chunked(
        client, naif_id, win_start, win_end, coarse_step
    )
    coarse_path.write_text(coarse_text)
    coarse_samples = _parse_chunks(coarse_text)
    logger.info("naif %d: coarse %d samples", naif_id, len(coarse_samples))

    refine_meta: list[dict] = []
    if coarse_samples and not skip_refine:
        furnished = _furnish_planets()
        try:

            def get_pos(body_id: int, et: float) -> np.ndarray:
                pos, _ = spiceypy.spkpos(str(body_id), et, "J2000", "NONE", "0")
                return pos

            windows = _identify_refinement_windows(
                coarse_samples,
                get_pos,
                coverage_start_iso=win_start,
                coverage_end_iso=win_end,
            )
        finally:
            for p in furnished:
                spiceypy.unload(str(p))

        logger.info("naif %d: %d refinement windows", naif_id, len(windows))
        for ws, we in windows:
            fn = f"refine_{ws}_{we}_1h.csv"
            path = cache_dir / fn
            logger.info("naif %d: refining %s..%s @ 1h", naif_id, ws, we)
            try:
                text = fetch_vectors(client, naif_id, ws, we, REFINE_STEP)
            except httpx.HTTPError as exc:
                logger.warning("naif %d refine %s..%s failed: %s", naif_id, ws, we, exc)
                continue
            path.write_text(text)
            samples = _parse_horizons_csv(text)
            refine_meta.append(
                {
                    "start": ws,
                    "end": we,
                    "cadence": "1h",
                    "file": fn,
                    "count": len(samples),
                }
            )

    meta = {
        "naif_id": naif_id,
        "name": obj.name,
        "revised": obj.revised,
        "window_start": win_start,
        "window_end": win_end,
        "last_fetch": datetime.now(timezone.utc).isoformat(),
        "coarse": {
            "file": coarse_name,
            "cadence": coarse_tag,
            "count": len(coarse_samples),
        },
        "refined": refine_meta,
    }
    meta_path.write_bytes(orjson.dumps(meta, option=orjson.OPT_INDENT_2))
    return meta


# ---------------------------------------------------------------------------
# SPK build
# ---------------------------------------------------------------------------


def _write_segment(
    handle: int,
    naif_id: int,
    samples: list[Sample],
    segid: str,
    *,
    degree: int = 7,
) -> bool:
    if len(samples) < degree + 1:
        logger.warning(
            "naif %d seg '%s': %d samples below degree+1=%d, skipping",
            naif_id,
            segid,
            len(samples),
            degree + 1,
        )
        return False
    states = np.asarray([s.state for s in samples], dtype=float)
    epochs = np.asarray([s.et for s in samples], dtype=float)
    spiceypy.spkw13(
        handle,
        naif_id,
        0,
        "J2000",
        float(epochs[0]),
        float(epochs[-1]),
        segid[:40],
        degree,
        len(samples),
        states,
        epochs,
    )
    return True


def build_one(naif_id: int) -> Path:
    """Assemble cached CSVs into a single multi-segment SPK13.

    Coarse segment first, then refined segments — SPICE evaluates with the
    last matching segment in the file winning for overlapping epochs, so
    queries inside a refinement window automatically use the 1h data.
    """
    cache_dir = SYNTH_CACHE_ROOT / str(naif_id)
    meta = orjson.loads((cache_dir / "meta.json").read_bytes())
    SYNTH_KERNELS_DIR.mkdir(parents=True, exist_ok=True)
    spk_path = SYNTH_KERNELS_DIR / f"{naif_id}.bsp"
    if spk_path.exists():
        spk_path.unlink()

    handle = spiceypy.spkopn(str(spk_path), f"Horizons synth {meta['name']}"[:60], 0)
    written = 0
    try:
        coarse_samples = _parse_chunks((cache_dir / meta["coarse"]["file"]).read_text())
        if _write_segment(handle, naif_id, coarse_samples, f"coarse_{meta['revised']}"):
            written += 1
        for r in meta["refined"]:
            samples = _parse_horizons_csv((cache_dir / r["file"]).read_text())
            if _write_segment(
                handle, naif_id, samples, f"refine_{r['start']}_{r['end']}"
            ):
                written += 1
    finally:
        spiceypy.spkcls(handle)

    if written == 0:
        spk_path.unlink(missing_ok=True)
        raise RuntimeError(f"naif {naif_id}: no usable segments")

    logger.info(
        "naif %d: wrote %s (%d segments, %d bytes)",
        naif_id,
        spk_path.name,
        written,
        spk_path.stat().st_size,
    )
    return spk_path


# ---------------------------------------------------------------------------
# Bulk selection from the Horizons major-body list
# ---------------------------------------------------------------------------


# Trailing tokens that mark non-spacecraft entries (PDC tabletop asteroids,
# debris, rocket stages). The MB list groups these alongside real spacecraft
# under negative NAIF IDs but they aren't navigable trajectories.
_NAME_DROP_PATTERNS: tuple[re.Pattern, ...] = tuple(
    re.compile(p, re.IGNORECASE)
    for p in (
        r"\(simulation\)\s*$",
        r"\(debris\)\s*$",
        r"\bSTAGE\b",
        r"\bCentaur RB\b",
        r"\bAtlas Centaur\b",
        r"\bPropulsion Module\b",
        r"_imp\b",  # post-impact stationary debris
        r"\bImpactor\b",  # already covered via agency missions (Deep Impact, DART)
    )
)


def _parse_horizons_spacecraft(mb_text: str) -> list[tuple[int, str]]:
    """Parse Horizons MB listing → [(naif_id, name)] for real spacecraft only."""
    out: list[tuple[int, str]] = []
    in_data = False
    for line in mb_text.splitlines():
        if line.startswith("  -------"):
            in_data = True
            continue
        if not in_data or len(line) < 11:
            continue
        id_str = line[0:9].strip()
        if not id_str.lstrip("-").isdigit():
            continue
        naif_id = int(id_str)
        if naif_id >= 0:
            continue
        name = line[11:45].strip()
        if not name:
            continue
        if any(p.search(name) for p in _NAME_DROP_PATTERNS):
            continue
        out.append((naif_id, name))
    return sorted(out, key=lambda r: -abs(r[0]))


def _existing_agency_naifs() -> set[int]:
    """NAIF IDs already covered by agency-published SPKs under `missions/`."""
    missions_dir = DOWNLOAD_DIR / "spice" / "kernels" / "missions"
    out: set[int] = set()
    if not missions_dir.exists():
        return out
    for mdir in missions_dir.iterdir():
        if not mdir.is_dir() or mdir.name == "HORIZONS-SYNTH":
            continue
        idx_path = mdir / "_index.json"
        if not idx_path.exists():
            continue
        try:
            idx = json.loads(idx_path.read_text())
        except (json.JSONDecodeError, OSError):
            continue
        for t in idx.get("targets", {}):
            try:
                naif = int(t)
            except ValueError:
                continue
            if naif < 0:
                out.add(naif)
    return out


def _write_index(coverage: dict[int, str]) -> None:
    """Emit a `missions/HORIZONS-SYNTH/_index.json` so the agency ingest walker
    finds these kernels alongside the rest. Schema matches ProbesDownloader's
    per-mission index.
    """
    SYNTH_KERNELS_DIR.mkdir(parents=True, exist_ok=True)
    files = []
    targets: dict[str, list[str]] = {}
    for naif_id, name in sorted(coverage.items()):
        spk = SYNTH_KERNELS_DIR / f"{naif_id}.bsp"
        if not spk.exists():
            continue
        files.append(
            {
                "name": spk.name,
                "size_bytes": spk.stat().st_size,
                "targets": [naif_id],
                "name_horizons": name,
            }
        )
        targets[str(naif_id)] = [spk.name]
    (SYNTH_KERNELS_DIR / "_index.json").write_text(
        json.dumps(
            {
                "server": "JPL-Horizons-synth",
                "mission": "HORIZONS-SYNTH",
                "spk_url": HORIZONS_URL,
                "files": files,
                "targets": targets,
            },
            indent=2,
            sort_keys=True,
        )
    )


# ---------------------------------------------------------------------------
# Provider
# ---------------------------------------------------------------------------


class HorizonsSyntheticDownloader(Downloader):
    """Synthesize per-spacecraft SPKs from Horizons VECTORS.

    Selection: walk the cached Horizons MB list, drop simulation/debris/
    stage/booster entries, drop NAIF IDs already covered by an agency SPK in
    `missions/`, then fetch+build the remainder. Cache-skip via OBJ_DATA's
    `Revised :` header makes repeated runs cheap.
    """

    name = PROVIDERS.SPICE_HORIZONS_SYNTH

    def __init__(self, client: httpx.Client) -> None:
        # Skip Downloader's default `out_dir = DOWNLOAD_DIR / name`; the cache
        # tree lives under spice/horizons-synth/ so it's grouped with other
        # SPICE data.
        self.client = client
        self.out_dir = SYNTH_CACHE_ROOT
        self.out_dir.mkdir(parents=True, exist_ok=True)

    def _candidates(self, limit: int | None) -> list[tuple[int, str]]:
        mb_path = DOWNLOAD_DIR / "horizons" / "major_bodies.txt"
        if not mb_path.exists():
            raise DownloadError(
                f"Need {mb_path}; run `space-map-download --sources horizons` first"
            )
        all_sc = _parse_horizons_spacecraft(mb_path.read_text())
        agency = _existing_agency_naifs()
        candidates = [(n, nm) for n, nm in all_sc if n not in agency]
        logger.info(
            "horizons-synth: %d MB spacecraft - %d already in missions/ "
            "= %d to synthesize",
            len(all_sc),
            len(agency),
            len(candidates),
        )
        if limit is not None:
            candidates = candidates[:limit]
            logger.info("horizons-synth: limiting to %d", limit)
        return candidates

    def download(self, limit: int | None = None, **kwargs: object) -> None:
        candidates = self._candidates(limit)
        succeeded: dict[int, str] = {}
        skipped: list[tuple[int, str, str]] = []
        failed: list[tuple[int, str, str]] = []

        for i, (naif_id, name) in enumerate(candidates, 1):
            logger.info("[%d/%d] naif %d (%s)", i, len(candidates), naif_id, name)
            try:
                fetch_one(self.client, naif_id)
            except RuntimeError as exc:
                logger.warning("naif %d fetch failed: %s", naif_id, exc)
                failed.append((naif_id, name, f"fetch: {exc}"))
                continue
            except httpx.HTTPError as exc:
                logger.warning("naif %d HTTP error: %s", naif_id, exc)
                failed.append((naif_id, name, f"http: {exc}"))
                continue
            try:
                build_one(naif_id)
            except RuntimeError as exc:
                # build_one raises if no segments meet degree+1 — common
                # for spacecraft whose Horizons coverage is < 8 days.
                logger.warning("naif %d build failed: %s", naif_id, exc)
                skipped.append((naif_id, name, f"build: {exc}"))
                continue
            succeeded[naif_id] = name
            # Light pacing between spacecraft.
            time.sleep(0.5)

        _write_index(succeeded)
        self._save_metadata(
            HORIZONS_URL,
            len(succeeded),
            complete=False,  # cache-skip handles per-spacecraft idempotency
            attempted=len(candidates),
            succeeded=len(succeeded),
            skipped=len(skipped),
            failed=len(failed),
            failed_examples=[
                {"naif_id": n, "name": nm, "reason": r} for n, nm, r in failed[:10]
            ],
            skipped_examples=[
                {"naif_id": n, "name": nm, "reason": r} for n, nm, r in skipped[:10]
            ],
        )
        logger.info(
            "horizons-synth: %d succeeded / %d skipped / %d failed (of %d)",
            len(succeeded),
            len(skipped),
            len(failed),
            len(candidates),
        )
