"""Synthesise SPK Type 5 extension kernels for PROPAGATE_* probes.

Writes one ``-extrap.bsp`` per candidate: single Type 5 segment seeded from
the last state, two-body Sun propagation to ``end_year``. The ``extrap``
filename token maps to predict tier in ``kernel_precedence`` so real recon
kernels win on overlap. Idempotent via a state-hash recorded in
``_index.json``; verdict flips PROPAGATE → SKIP delete the kernel.

Also handles ``"propagation": {"mode": "from_state", ...}`` events entries
for probes with no SPK (Apollo S-IVBs, Mariner 2 without a NAIF, …).
"""

import hashlib
import json
import logging
from dataclasses import dataclass
from pathlib import Path

import httpx
import numpy as np
import spiceypy

from space_map_data.constants.providers import PROVIDERS
from space_map_data.download.downloader import Downloader
from space_map_data.probes.propagation import (
    GM_SUN,
    Candidate,
    PropagationConfig,
    detect_all,
    from_state_overrides,
)
from space_map_data.utils.time import jd_to_et, year_to_jd

from .layout import MISSIONS_DIR

logger = logging.getLogger(__name__)

EXTRAP_SUFFIX = "-extrap.bsp"
# Bump to invalidate every cached kernel — only when the synthesis itself
# changes shape (frame, central body); state changes already flow via the hash.
SYNTH_VERSION = 1


@dataclass(frozen=True)
class SynthResult:
    mission: str
    naif: int
    path: Path
    action: str  # "written" | "unchanged" | "removed"


def _state_hash(
    naif: int, state: tuple[float, ...], start_et: float, end_et: float, frame: str
) -> str:
    """Stable hash of the inputs that fully determine the extrap kernel."""
    payload = {
        "version": SYNTH_VERSION,
        "naif": naif,
        "state": list(state),
        "start_et": start_et,
        "end_et": end_et,
        "frame": frame,
        "gm": GM_SUN,
        "center": 10,
    }
    return hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()[:16]


def _write_type5_segment(
    out_path: Path,
    naif: int,
    state6: tuple[float, ...],
    start_et: float,
    end_et: float,
    segid: str,
) -> None:
    """Write a single-segment SPK Type 5 at ``out_path``. Overwrites; caller
    handles atomicity. ``segid`` is truncated to CSPICE's 40-char limit."""
    if out_path.exists():
        out_path.unlink()
    handle = spiceypy.spkopn(str(out_path), f"extrap{naif}", 0)
    try:
        spiceypy.spkw05(
            handle=handle,
            body=naif,
            center=10,
            inframe="ECLIPJ2000",
            first=start_et,
            last=end_et,
            segid=segid[:40],
            gm=GM_SUN,
            n=1,
            states=np.array([list(state6)], dtype=float),
            epochs=np.array([start_et], dtype=float),
        )
    finally:
        spiceypy.spkcls(handle)


def _update_index(
    mission_dir: Path,
    extrap_name: str,
    naif: int,
    state_hash: str,
) -> None:
    """Replace any prior entry for ``extrap_name`` so re-runs converge."""
    idx_path = mission_dir / "_index.json"
    if not idx_path.exists():
        logger.warning(
            "propagation: %s missing _index.json; skipping index update",
            mission_dir,
        )
        return
    idx = json.loads(idx_path.read_text())
    files = [f for f in idx.get("files", []) if f.get("name") != extrap_name]
    extrap_path = mission_dir / extrap_name
    files.append(
        {
            "name": extrap_name,
            "size_bytes": extrap_path.stat().st_size,
            "targets": [naif],
            "propagation": {"state_hash": state_hash},
        }
    )
    idx["files"] = sorted(files, key=lambda f: f["name"])
    targets = idx.get("targets", {})
    coverage = sorted(set(targets.get(str(naif), []) + [extrap_name]))
    targets[str(naif)] = coverage
    idx["targets"] = targets
    idx_path.write_text(json.dumps(idx, indent=2, sort_keys=True))


def _drop_from_index(mission_dir: Path, extrap_name: str, naif: int) -> None:
    """Remove an extrap entry from ``_index.json``."""
    idx_path = mission_dir / "_index.json"
    if not idx_path.exists():
        return
    idx = json.loads(idx_path.read_text())
    idx["files"] = [f for f in idx.get("files", []) if f.get("name") != extrap_name]
    targets = idx.get("targets", {})
    if str(naif) in targets:
        targets[str(naif)] = [n for n in targets[str(naif)] if n != extrap_name]
        if not targets[str(naif)]:
            targets.pop(str(naif))
    idx["targets"] = targets
    idx_path.write_text(json.dumps(idx, indent=2, sort_keys=True))


def _cached_state_hash(mission_dir: Path, extrap_name: str) -> str | None:
    """Recorded state hash for this filename, or None if absent."""
    idx_path = mission_dir / "_index.json"
    if not idx_path.exists():
        return None
    idx = json.loads(idx_path.read_text())
    for f in idx.get("files", []):
        if f.get("name") == extrap_name:
            prop = f.get("propagation") or {}
            return prop.get("state_hash")
    return None


def synthesise_from_candidate(cand: Candidate, end_year: int) -> SynthResult | None:
    """Write or refresh the extrap kernel for one PROPAGATE_* candidate.
    Returns None for non-candidates; short-circuits when the state hash is
    unchanged."""
    if not cand.is_propagate:
        return None
    mission_dir = MISSIONS_DIR / cand.mission
    if not mission_dir.exists():
        logger.warning(
            "propagation: %s mission dir missing; cannot write extrap",
            cand.mission,
        )
        return None
    extrap_name = f"{cand.naif}{EXTRAP_SUFFIX}"
    end_et = jd_to_et(year_to_jd(end_year))
    if end_et <= cand.end_et:
        return None
    state_hash = _state_hash(
        cand.naif, cand.state_km_kms, cand.end_et, end_et, "ECLIPJ2000"
    )
    if _cached_state_hash(mission_dir, extrap_name) == state_hash:
        return SynthResult(
            cand.mission, cand.naif, mission_dir / extrap_name, "unchanged"
        )

    out_path = mission_dir / extrap_name
    tmp_path = out_path.with_suffix(out_path.suffix + ".tmp")
    _write_type5_segment(
        tmp_path,
        cand.naif,
        cand.state_km_kms,
        cand.end_et,
        end_et,
        segid=f"EXTRAP {cand.mission} {cand.naif}",
    )
    tmp_path.replace(out_path)
    _update_index(mission_dir, extrap_name, cand.naif, state_hash)
    return SynthResult(cand.mission, cand.naif, out_path, "written")


def remove_obsolete(cand: Candidate) -> SynthResult | None:
    """Delete the extrap kernel if the verdict flipped PROPAGATE → SKIP."""
    mission_dir = MISSIONS_DIR / cand.mission
    extrap_name = f"{cand.naif}{EXTRAP_SUFFIX}"
    out_path = mission_dir / extrap_name
    if not out_path.exists():
        return None
    out_path.unlink()
    _drop_from_index(mission_dir, extrap_name, cand.naif)
    return SynthResult(cand.mission, cand.naif, out_path, "removed")


def synthesise_all(config: PropagationConfig | None = None) -> list[SynthResult]:
    """Detect + write extrap kernels for every PROPAGATE_* probe; also
    process ``from_state`` events entries. Returns one SynthResult per
    touched probe."""
    cfg = config or PropagationConfig()
    candidates = detect_all(cfg)
    results: list[SynthResult] = []
    try:
        for cand in candidates:
            try:
                if cand.is_propagate:
                    r = synthesise_from_candidate(cand, cfg.end_year)
                else:
                    r = remove_obsolete(cand)
            except spiceypy.exceptions.SpiceyError:
                logger.exception(
                    "propagation: spkw05 failed for %s/%d", cand.mission, cand.naif
                )
                continue
            if r is not None:
                results.append(r)

        for probe in from_state_overrides():
            r = _synthesise_from_state_entry(probe, cfg.end_year)
            if r is not None:
                results.append(r)
    finally:
        spiceypy.kclear()

    counts = {
        a: sum(1 for r in results if r.action == a)
        for a in ("written", "unchanged", "removed")
    }
    logger.info(
        "propagation: %d candidates → %d written, %d unchanged, %d removed",
        sum(1 for c in candidates if c.is_propagate),
        counts["written"],
        counts["unchanged"],
        counts["removed"],
    )
    return results


def _synthesise_from_state_entry(probe: dict, end_year: int) -> SynthResult | None:
    """Write an extrap kernel from a curated last state into the synthetic
    ``EVENTS-STATE`` mission dir so the standard walker picks it up."""
    prop = probe.get("propagation") or {}
    state = prop.get("state_ecliptic_j2000_km_kms")
    epoch = prop.get("epoch")
    naif = probe.get("naif_id")
    if not (isinstance(state, list) and len(state) == 6 and epoch and naif):
        logger.warning(
            "propagation: events entry %r has incomplete from_state block; skipping",
            probe.get("name"),
        )
        return None
    try:
        start_et = spiceypy.utc2et(epoch.rstrip("Z"))
    except spiceypy.exceptions.SpiceyError:
        logger.exception("propagation: cannot parse epoch %r", epoch)
        return None
    end_et = jd_to_et(year_to_jd(end_year))
    if end_et <= start_et:
        return None
    mission_dir = MISSIONS_DIR / "EVENTS-STATE"
    mission_dir.mkdir(parents=True, exist_ok=True)
    idx_path = mission_dir / "_index.json"
    if not idx_path.exists():
        idx_path.write_text(
            json.dumps(
                {
                    "server": "EVENTS-STATE",
                    "mission": "EVENTS-STATE",
                    "spk_url": None,
                    "bucket": "trajectory",
                    "files": [],
                    "targets": {},
                },
                indent=2,
                sort_keys=True,
            )
        )

    state6 = tuple(float(x) for x in state)
    state_hash = _state_hash(int(naif), state6, start_et, end_et, "ECLIPJ2000")
    extrap_name = f"{naif}{EXTRAP_SUFFIX}"
    if _cached_state_hash(mission_dir, extrap_name) == state_hash:
        return SynthResult(
            "EVENTS-STATE", int(naif), mission_dir / extrap_name, "unchanged"
        )

    out_path = mission_dir / extrap_name
    tmp_path = out_path.with_suffix(out_path.suffix + ".tmp")
    _write_type5_segment(
        tmp_path,
        int(naif),
        state6,
        start_et,
        end_et,
        segid=f"EVENTS-STATE {probe.get('name', '?')} {naif}",
    )
    tmp_path.replace(out_path)
    _update_index(mission_dir, extrap_name, int(naif), state_hash)
    return SynthResult("EVENTS-STATE", int(naif), out_path, "written")


class PropagationDownloader(Downloader):
    """Synthesise extrap kernels in the download phase. Not a real download
    — no HTTP — but slots into the existing orchestrator so it runs after
    ProbesDownloader / HorizonsSyntheticDownloader without bespoke wiring."""

    name = PROVIDERS.SPICE_PROBES_PROPAGATION

    def __init__(self, client: httpx.Client) -> None:
        self.client = client  # base-class contract; unused (no HTTP)
        self.out_dir = MISSIONS_DIR
        self.out_dir.mkdir(parents=True, exist_ok=True)

    def is_complete(self, limit: int | None) -> bool:
        # State hash in _index.json already short-circuits per-probe.
        return False

    def download(self, limit: int | None = None, **_: object) -> None:
        results = synthesise_all()
        written = sum(1 for r in results if r.action == "written")
        unchanged = sum(1 for r in results if r.action == "unchanged")
        removed = sum(1 for r in results if r.action == "removed")
        self._save_metadata(
            url="local-synthesis",
            record_count=len(results),
            complete=True,
            written=written,
            unchanged=unchanged,
            removed=removed,
        )


__all__ = [
    "EXTRAP_SUFFIX",
    "PropagationDownloader",
    "SynthResult",
    "remove_obsolete",
    "synthesise_all",
    "synthesise_from_candidate",
]
