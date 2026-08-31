"""Synthesise SPK kernels from Deep Space Catalog solar phases.

One ``GCAT-DEEP/<naif>-extrap.bsp`` per probe, holding a Type 5 segment per
solved phase. The naming and directory shape follow the propagation
synthesiser next door so the export walker treats both alike. The shared
``-extrap`` token also puts these in the predict tier, though nothing here
relies on that: only probes with no archive trajectory are solved at all, so a
derived kernel is never furnished against a real one for the same NAIF.

These are derived positions, not observations. They exist for probes the SPICE
archives never covered — the Soviet planetary programme above all — and carry
the error class measured in :mod:`space_map_data.probes.deepcat_arcs`.
"""

import collections
import hashlib
import json
import logging
from dataclasses import dataclass
from pathlib import Path

import httpx
import spiceypy

from space_map_data.constants.providers import PROVIDERS
from space_map_data.download.downloader import Downloader
from space_map_data.probes.deepcat import load_deepcat
from space_map_data.probes.deepcat_arcs import SolvedArc, solve_object
from space_map_data.probes.probe_id import (
    GCAT_DEEP_MISSION,
    has_archive_trajectory,
    load_registry,
)
from space_map_data.probes.propagation import (
    S_PER_YEAR,
    from_state_overrides,
    furnish_generic_kernels,
)
from space_map_data.utils.paths import SOURCES_POSITION_DIR

from .layout import MISSIONS_DIR
from .synthetic_index import (
    EXTRAP_SUFFIX,
    INDEX_NAME,
    cached_provenance,
    drop_file,
    ensure_index,
    record_file,
    write_type5,
)

logger = logging.getLogger(__name__)

MISSION_DIR_NAME = GCAT_DEEP_MISSION

# Key the index entry hangs its provenance off, and what the export reads back
# to state the arc's accuracy.
PROVENANCE_KEY = "deepcat"

# Bump to invalidate every cached kernel — when the synthesis changes shape, or
# when the index records something new about an unchanged kernel. Element and
# date changes already flow through the arc hash.
SYNTH_VERSION = 2

# How long a phase that never ends is still claimed for. Measured against
# archive trajectories: an open arc holds a median 0.10 AU out to five years,
# after which the ninetieth percentile runs away past an AU and the conic is
# inventing rather than extrapolating.
OPEN_ARC_YEARS = 5.0


@dataclass(frozen=True)
class DeepcatSynthResult:
    name: str
    naif: int
    arcs: int
    action: str  # "written" | "unchanged" | "removed"


def _arc_hash(naif: int, arcs: list[SolvedArc]) -> str:
    """Stable hash of everything that determines the kernel."""
    payload = {
        "version": SYNTH_VERSION,
        "naif": naif,
        "open_years": OPEN_ARC_YEARS,
        "arcs": [
            {
                "phase": a.phase,
                "start": a.start_et,
                "end": a.end_et,
                "epoch": a.solution.epoch_et,
                "state": list(a.solution.state_km_kms),
                "class": a.arc_class.value,
            }
            for a in arcs
        ],
    }
    return hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()[:16]


def _segment_bounds(arc: SolvedArc) -> tuple[float, float]:
    """Start and end ET the segment is valid over."""
    if arc.end_et is not None:
        return arc.start_et, arc.end_et
    return arc.start_et, arc.start_et + OPEN_ARC_YEARS * S_PER_YEAR


def arc_segments(
    arcs: list[SolvedArc], name: str
) -> list[tuple[tuple[float, ...], float, float, float, str]]:
    """One Type 5 segment per arc, in the shape `write_type5` takes."""
    return [
        (
            arc.solution.state_km_kms,
            arc.solution.epoch_et,
            *_segment_bounds(arc),
            f"GCAT {arc.deep_id} p{arc.phase} {name}",
        )
        for arc in arcs
    ]


def _drop_stale(mission_dir: Path, keep: set[str]) -> list[DeepcatSynthResult]:
    """Delete kernels for probes that no longer solve, so a tightened policy
    removes what it stops standing behind."""
    index = mission_dir / INDEX_NAME
    if not index.exists():
        return []
    removed: list[DeepcatSynthResult] = []
    for entry in json.loads(index.read_text()).get("files", []):
        filename = entry["name"]
        if filename in keep:
            continue
        (mission_dir / filename).unlink(missing_ok=True)
        naif = (entry.get("targets") or [0])[0]
        drop_file(mission_dir, filename, naif)
        removed.append(DeepcatSynthResult(filename, naif, 0, "removed"))
    return removed


def synthesise_all() -> list[DeepcatSynthResult]:
    """Solve every catalogued deep-space object that joins to a probe with no
    trajectory of its own, and write its arcs.

    Probes an archive already covers are skipped even where a solved arc would
    fill a gap in that archive. A derived conic dropped into a hole in real
    coverage reads downstream as coverage, and nothing in the exported spans
    says which windows were measured and which were inferred."""
    objects, phases = load_deepcat()
    by_object: dict[str, list] = {}
    for phase in phases:
        by_object.setdefault(phase.deep_id, []).append(phase)

    registry = load_registry()
    by_norad = {
        int(e["norad_cat_id"]): e for e in registry if e.get("norad_cat_id") is not None
    }
    # A hand-written state beats a catalogue solve; skip those probes entirely
    # rather than furnish two predict-tier kernels and let load order decide.
    curated = {p.get("naif_id") for p in from_state_overrides()}

    mission_dir = MISSIONS_DIR / MISSION_DIR_NAME
    mission_dir.mkdir(parents=True, exist_ok=True)
    ensure_index(mission_dir, MISSION_DIR_NAME)

    furnish_generic_kernels(SOURCES_POSITION_DIR / "spice-kernels")
    results: list[DeepcatSynthResult] = []
    keep: set[str] = set()
    try:
        for deep_id, obj in sorted(objects.items()):
            entry = by_norad.get(obj.norad_id) if obj.norad_id else None
            if entry is None:
                continue
            naif = entry.get("naif_id")
            if naif is None or naif in curated or has_archive_trajectory(entry):
                continue
            arcs, _ = solve_object(obj, by_object.get(deep_id, []))
            if not arcs:
                continue

            filename = f"{naif}{EXTRAP_SUFFIX}"
            keep.add(filename)
            arc_hash = _arc_hash(naif, arcs)
            cached = cached_provenance(mission_dir, filename, PROVENANCE_KEY)
            if cached is not None and cached.get("arc_hash") == arc_hash:
                results.append(
                    DeepcatSynthResult(entry["name"], naif, len(arcs), "unchanged")
                )
                continue

            out_path = mission_dir / filename
            tmp_path = out_path.with_suffix(out_path.suffix + ".tmp")
            try:
                write_type5(
                    tmp_path, naif, f"gcat{naif}", arc_segments(arcs, entry["name"])
                )
            except spiceypy.exceptions.SpiceyError:
                logger.exception("deepcat: spkw05 failed for %s (%d)", obj.name, naif)
                tmp_path.unlink(missing_ok=True)
                keep.discard(filename)
                continue
            tmp_path.replace(out_path)
            record_file(
                mission_dir,
                filename,
                naif,
                PROVENANCE_KEY,
                {
                    "arc_hash": arc_hash,
                    "arcs": len(arcs),
                    "median_error_au": max(a.median_error_au for a in arcs),
                },
                create_missing=True,
            )
            results.append(
                DeepcatSynthResult(entry["name"], naif, len(arcs), "written")
            )
        results.extend(_drop_stale(mission_dir, keep))
    finally:
        spiceypy.kclear()

    counts = collections.Counter(r.action for r in results)
    logger.info(
        "deepcat: %d probes solved → %d written, %d unchanged, %d removed",
        counts["written"] + counts["unchanged"],
        counts["written"],
        counts["unchanged"],
        counts["removed"],
    )
    return results


class DeepcatSynthDownloader(Downloader):
    """Synthesise catalogue-derived kernels in the download phase. No HTTP —
    it slots into the orchestrator so it runs after the archives and the
    propagation synthesiser without bespoke wiring."""

    name = PROVIDERS.SPICE_DEEPCAT

    def __init__(self, client: httpx.Client) -> None:
        self.client = client  # base-class contract; unused (no HTTP)
        self.out_dir = MISSIONS_DIR / MISSION_DIR_NAME
        self.out_dir.mkdir(parents=True, exist_ok=True)

    def is_complete(self, limit: int | None) -> bool:
        # The arc hash in _index.json already short-circuits per-probe.
        return False

    def download(self, limit: int | None = None, **_: object) -> None:
        results = synthesise_all()
        counts = collections.Counter(r.action for r in results)
        self._save_metadata(
            url="local-synthesis",
            record_count=len(results),
            complete=True,
            **counts,
        )


__all__ = [
    "MISSION_DIR_NAME",
    "PROVENANCE_KEY",
    "arc_segments",
    "OPEN_ARC_YEARS",
    "DeepcatSynthDownloader",
    "DeepcatSynthResult",
    "synthesise_all",
]
