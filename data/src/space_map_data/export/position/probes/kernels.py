"""SPICE kernel discovery and ordering for the probes exporter.

Walks `missions/`, `landed_missions/`, and the generic-kernel tree under
`kernels/`, applying the active include patterns and the recon/predict
precedence rule. `enumerate_probes` yields one record per spacecraft NAIF
ID with its furnish-ready kernel list.
"""

import json
import logging
import re
from pathlib import Path

from space_map_data.download.providers.spice.bodies.names import (
    load_excluded_naif_ids,
)
from space_map_data.download.providers.spice.probes import (
    LANDED_INCLUDE,
    LANDED_MISSIONS_DIR,
    MISSION_INCLUDE,
    MISSIONS_DIR,
)
from space_map_data.download.providers.spice.synth import qid_deduped_synth_naifs
from space_map_data.utils.paths import DERIVED_POSITION_DIR

logger = logging.getLogger(__name__)

# Kernels we never furnish: stationary post-mission ephemerides extend
# coverage by decades at fixed coords and corrupt zone classification.
STATIONARY_PATTERNS = ("_imp_", "_crashsite_")

# Filename-token markers that classify a kernel by trajectory provenance.
# Reconstruction-class kernels furnshed LAST so SPICE last-loaded-wins picks
# them over any predict-class kernel that also covers the same ET. Tokens
# match against case-folded `_`/`.`/`-` splits of the filename so accidental
# substring hits (e.g. "merged" containing "rg") don't trigger.
_RECON_TOKENS: frozenset[str] = frozenset(
    {"rec", "recon", "reconstruction", "reconstructed", "fcp", "final"}
)
_PREDICT_TOKENS: frozenset[str] = frozenset(
    {"pre", "pred", "predict", "predicted", "flp", "ref", "forecast", "extrap"}
)


def kernel_precedence(name: str) -> int:
    """Lower = furnshed first (loses), higher = furnshed last (wins).

    Three tiers: 0 predict / forward-looking, 1 default, 2 reconstruction.
    Used to break SPICE last-loaded-wins ties in favor of the higher-quality
    kernel when two kernels cover the same ET — e.g. GAIA's `gaia_rec_*`
    (weekly reconstruction) wins over `gaia_flp_*` (long-arc flight predict),
    HERA's `_fcp_` (Flight Control Product) wins over `_flp_` (Forward-Looking
    Planned), JUNO's `juno_rec_orbit` wins over `juno_pred_orbit` and the
    `spk_ref_*` long-arc reference.
    """
    tokens = re.split(r"[_.\-]", name.lower())
    if any(t in _RECON_TOKENS for t in tokens):
        return 2
    if any(t in _PREDICT_TOKENS for t in tokens):
        return 0
    return 1


def kernels_from_index(mdir: Path) -> list[Path]:
    """Return mission kernels from `_index.json`'s `files` list, filtered
    and sorted ready to furnish.

    Steps:
      1. Read names from `_index.json` (NOT a directory glob — that would
         pick up `MEX/ORMM_*` monthlies and similar files the downloader
         intentionally excludes).
      2. Re-apply the current `MISSION_INCLUDE` pattern (so tightening it
         takes effect without re-download — e.g. dropping ENVISION planning
         scenario variants).
      3. Drop stationary kernels (post-mission ephemerides parked at impact
         site / surface that span decades at fixed coords).
      4. Sort by `(kernel_precedence, name)` — predict-class kernels
         furnshed first so reconstruction wins under SPICE's
         last-loaded-wins. Within a tier, alphabetical (preserves
         lex-last = latest version semantics).

    Shared between the writer's classify/fit passes and the benchmark, so
    both sides see identical truth.
    """
    return _kernels_from_index_with(mdir, MISSION_INCLUDE, skip_stationary=True)


def landed_kernels_from_index(mission_name: str) -> list[Path]:
    """Same shape as `kernels_from_index` but for the `landed_missions/<M>/`
    bucket, filtering against `LANDED_INCLUDE` instead of `MISSION_INCLUDE`.
    Stationary-pattern filtering is OFF — landed kernels are *meant* to be
    stationary (Viking/Phoenix landers, MSL runout tail)."""
    mdir = LANDED_MISSIONS_DIR / mission_name
    if not mdir.exists():
        return []
    return _kernels_from_index_with(mdir, LANDED_INCLUDE, skip_stationary=False)


def _kernels_from_index_with(
    mdir: Path,
    include_map: dict[str, tuple[str, ...]],
    skip_stationary: bool,
) -> list[Path]:
    idx_path = mdir / "_index.json"
    if not idx_path.exists():
        return []
    idx = json.loads(idx_path.read_text())
    include_pats = tuple(
        re.compile(p, re.IGNORECASE) for p in include_map.get(mdir.name, ())
    )
    candidates: list[Path] = []
    for entry in idx.get("files", []):
        name = entry["name"]
        path = mdir / name
        if not path.exists():
            continue
        if skip_stationary and any(p in name for p in STATIONARY_PATTERNS):
            continue
        # Synthesised extrap kernels (Type 5 two-body extensions written by
        # `download/providers/spice/probes/propagation.py`) bypass the
        # include pattern — they're emitted by us, not downloaded, so the
        # per-mission whitelist that gates upstream archives doesn't apply.
        is_extrap = name.endswith("-extrap.bsp")
        if (
            not is_extrap
            and include_pats
            and not any(p.match(name) for p in include_pats)
        ):
            logger.debug(
                "drop %s/%s: no longer matches include patterns", mdir.name, name
            )
            continue
        candidates.append(path)
    return sorted(candidates, key=lambda p: (kernel_precedence(p.name), p.name))


def collect_generic_kernels(
    kernels_dir: Path,
) -> tuple[list[Path], list[Path]]:
    """Collect generic kernels under `kernels/`, splitting them by role.

    Returns `(lsk_pck_paths, generic_spk_paths)`:
      * LSK (.tls) / PCK (.tpc) — leapseconds and physical constants. No SPK
        precedence implications; load once at outer scope.
      * Generic SPKs (.bsp under `spk/`) — planetary ephemerides (de440,
        sat441, …). Must be furnshed AFTER mission kernels so they win for
        shared targets (Saturn 699, Saturn-barycenter 6, etc.). Mission
        kernels like p11-a.bsp embed their own 1970s-era planetary data,
        which would otherwise contaminate the fit.

    `missions/` and `probes/` subtrees are excluded (handled per-probe).
    """
    skip_dirs = {"missions", "probes"}
    lsk_pck: list[Path] = []
    generic_spk: list[Path] = []
    for path in sorted(kernels_dir.rglob("*")):
        if not path.is_file():
            continue
        if any(part in skip_dirs for part in path.relative_to(kernels_dir).parts):
            continue
        suffix = path.suffix.lower()
        if suffix in (".tls", ".tpc"):
            lsk_pck.append(path)
        elif suffix == ".bsp":
            generic_spk.append(path)
    return lsk_pck, generic_spk


def enumerate_probes() -> list[tuple[Path, list[Path], int]]:
    """Return `[(mission_dir, kernels, naif_id)]` for every spacecraft NAIF.

    Includes every negative target from trajectory + landed indexes (NAIF
    reserves negatives for spacecraft), minus the simulation/debris set from
    major_bodies.txt. Landing-site-only NAIFs (`-X900`) go through the
    events-JSON ingest instead.
    """
    out: list[tuple[Path, list[Path], int]] = []
    mission_names: set[str] = set()
    if MISSIONS_DIR.exists():
        mission_names.update(p.name for p in MISSIONS_DIR.iterdir() if p.is_dir())
    if LANDED_MISSIONS_DIR.exists():
        mission_names.update(
            p.name for p in LANDED_MISSIONS_DIR.iterdir() if p.is_dir()
        )
    synth_qid_dups = qid_deduped_synth_naifs()
    excluded_naif_ids = load_excluded_naif_ids(DERIVED_POSITION_DIR / "tables")
    for name in sorted(mission_names):
        mdir = MISSIONS_DIR / name
        trajectory_kernels = (
            kernels_from_index(mdir) if (mdir / "_index.json").exists() else []
        )
        landed_kernels = landed_kernels_from_index(name)
        if not trajectory_kernels and not landed_kernels:
            continue
        targets: set[int] = set()
        if (mdir / "_index.json").exists():
            traj_idx = json.loads((mdir / "_index.json").read_text())
            targets.update(int(s) for s in traj_idx.get("targets", {}))
        landed_idx_path = LANDED_MISSIONS_DIR / name / "_index.json"
        if landed_idx_path.exists():
            landed_idx = json.loads(landed_idx_path.read_text())
            targets.update(int(s) for s in landed_idx.get("targets", {}))
        spacecraft_ids = sorted(
            t for t in targets if t < 0 and t not in excluded_naif_ids
        )
        filtered = sorted(set(targets) - set(spacecraft_ids))
        if filtered:
            logger.info(
                "mission=%s: filtered %d non-spacecraft targets: %s",
                name,
                len(filtered),
                filtered,
            )
        # Furnish trajectory first then landed so landed wins under SPICE
        # last-loaded-wins where ET coverage overlaps (EDL window).
        combined = trajectory_kernels + landed_kernels
        for naif_id in spacecraft_ids:
            if name == "HORIZONS-SYNTH" and naif_id in synth_qid_dups:
                logger.info(
                    "skipping HORIZONS-SYNTH naif=%d: QID already covered "
                    "by an agency mission probe",
                    naif_id,
                )
                continue
            out.append((mdir, combined, naif_id))
    return out
