"""Synthesise SPK kernels from the Space-Track TLE archive.

One ``SPACETRACK-TLE/<naif>-extrap.bsp`` per probe, holding a Type 10 segment
per tracked run. Type 10 stores the element sets verbatim and lets SPICE run
its own SGP4/SDP4 over them, so nothing here propagates an orbit or rotates
TEME into J2000 — both belong to the model the elements were fitted against.
The naming and directory shape follow the two synthesisers next door, so the
export walker treats all three alike, and the shared ``-extrap`` token puts
these in the predict tier: where an archive covers the same window, the archive
wins.

These exist for one population. Space-Track follows a spacecraft only while it
is Earth-bound, so a probe leaving for another body gets one to three element
sets on its launch day and nothing after — Queqiao two, Tianwen-2 one, both in
the parking orbit. Nothing at L1 or L2 is carried at all. What is left is the
handful of science probes that stayed in a high Earth orbit and were followed
for decades, of which the catalogue is the only record: the four Cluster II
craft above all, tracked from 2000 with several hundred element sets a year,
whose pages carry a mission and no trajectory. Horizons cannot stand in — it
answers for Cluster only from 2026.

Accuracy, measured against INTEGRAL's ESA reconstruction (a 64-hour orbit
reaching 150,000 km, the closest analogue carrying both sources): a median
24 km and a ninetieth percentile of 38 km. The 2% of samples past 100 km fall
around the manoeuvres that reshaped that orbit, where the element set in force
predates the burn.
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
from space_map_data.export.position.elements.spacetrack_source import (
    ARCHIVE_YEARS,
    archive_norads_by_group,
    archive_source_groups,
    archive_zip_fingerprints,
    iter_archive_tle_lines,
    source_zips_for,
)
from space_map_data.probes.probe_id import (
    SPACETRACK_TLE_MISSION,
    has_archive_trajectory,
    load_registry,
    synthetic_sources,
)
from space_map_data.probes.propagation import furnish_generic_kernels
from space_map_data.utils.paths import SOURCES_POSITION_DIR

from .layout import MISSIONS_DIR
from .synthetic_index import (
    EXTRAP_SUFFIX,
    INDEX_NAME,
    cached_provenance,
    drop_file,
    ensure_index,
    record_file,
    write_type10,
)

logger = logging.getLogger(__name__)

MISSION_DIR_NAME = SPACETRACK_TLE_MISSION

# Key the index entry hangs its provenance off, and what the export reads back
# to state the trajectory's accuracy.
PROVENANCE_KEY = "spacetrack_tle"

# Bump to invalidate every cached kernel — the provenance keys on the archive
# zips, which do not move when only this code does.
SYNTH_VERSION = 2

# A craft the catalogue followed, against one it logged on its way out of Earth
# orbit. Measured across the whole archive: a followed probe carries 150 to 830
# element sets a year, a departing one gets between one and three, all dated
# its launch day. Nothing observed sits between the two.
MIN_ELEMENT_SETS = 20
MIN_SPAN_DAYS = 30.0

# Longer than this between element sets and the catalogue had stopped
# following, so the run ends. Within a segment SPICE answers from the nearest
# element set, which across a hole reads as coverage rather than as the gap it
# is. Matches the slack the Earth zone allows an element set either side of its
# epoch.
MAX_GAP_DAYS = 14.0

# Two element sets is the shortest thing that states a trajectory rather than
# an instant, and it drops the stray corrupt epoch — Spektr-R carries one dated
# 1970 — which gap splitting leaves alone in a run of its own.
MIN_SETS_PER_RUN = 2

_S_PER_DAY = 86400.0

# The year `getelm` resolves a TLE's two-digit epoch against: the window runs
# 1957 to 2056, which covers the catalogue from its first entry.
_TLE_EPOCH_BASE_YEAR = 1957


@dataclass(frozen=True)
class TleSynthResult:
    name: str
    naif: int
    norad: int
    element_sets: int
    runs: int
    action: str  # "written" | "unchanged" | "removed" | "too-sparse"


def _signature(norad: int, fingerprints: list[dict]) -> str:
    """Everything that decides the kernel, short of reading the zips.

    Deliberately computable without a scan: the archive is ~12 GB, and a run
    that changed nothing has to be able to say so before opening it.
    """
    payload = {
        "version": SYNTH_VERSION,
        "norad": norad,
        "min_sets": MIN_ELEMENT_SETS,
        "min_span_days": MIN_SPAN_DAYS,
        "max_gap_days": MAX_GAP_DAYS,
        "min_sets_per_run": MIN_SETS_PER_RUN,
        "archive": fingerprints,
    }
    return hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()[:16]


def _candidates() -> dict[int, dict]:
    """Registry probes a TLE kernel could place, keyed by NAIF.

    A probe an archive already covers is left alone even where the catalogue
    also followed it: a derived trajectory dropped beside a published one reads
    downstream as one more source, and nothing in the exported spans says which
    is which. Same for a probe another synthesiser already claims — two derived
    kernels over one window make load order the arbiter.

    A NORAD several probes claim is dropped rather than shared. The catalogue
    entry follows one object, and the craft claiming it launched bolted
    together — Chang'e 5's lander, orbiter and returner are all 47097 — so
    copying the one trajectory to each would fly the lander in Earth orbit.
    Which of them the catalogue actually tracked is not in the data, and the
    carried-craft resolver is where a passenger borrows a position anyway.
    """
    by_norad: dict[int, list[dict]] = collections.defaultdict(list)
    for entry in load_registry():
        norad = entry.get("norad_cat_id")
        naif = entry.get("naif_id")
        if norad is None or naif is None or has_archive_trajectory(entry):
            continue
        claimed = synthetic_sources(entry) - {SPACETRACK_TLE_MISSION}
        if claimed:
            logger.info(
                "tle: %s already carries a derived kernel from %s; skipping",
                entry.get("name"),
                ", ".join(sorted(claimed)),
            )
            continue
        by_norad[int(norad)].append(entry)

    out: dict[int, dict] = {}
    for norad, entries in by_norad.items():
        if len(entries) > 1:
            logger.info(
                "tle: NORAD %d is claimed by %s; no kernel — the catalogue "
                "follows one object and the data does not say which",
                norad,
                ", ".join(sorted(str(e.get("name")) for e in entries)),
            )
            continue
        out[int(entries[0]["naif_id"])] = entries[0]
    return out


def collect_element_sets(norads: set[int]) -> dict[int, dict[float, list[float]]]:
    """Read every element set the archive holds for ``norads``.

    One streaming pass per source group that holds one of them, and none over
    the rest. Keyed by epoch so a set the archive reissued verbatim is stored
    once — Type 10 needs strictly increasing epochs, and roughly two in five of
    the pairs read are repeats.
    """
    by_group = archive_norads_by_group(ARCHIVE_YEARS)
    found: dict[int, dict[float, list[float]]] = collections.defaultdict(dict)
    pairs = 0
    rejected = 0
    for label, group_years in archive_source_groups(ARCHIVE_YEARS):
        wanted = norads & by_group.get(label, set())
        if not wanted:
            continue
        for zip_path in source_zips_for(group_years[0]):
            logger.info(
                "tle: reading %s for %d satellite(s)", zip_path.name, len(wanted)
            )
            for norad, line1, line2 in iter_archive_tle_lines(zip_path, wanted):
                try:
                    epoch, elements = spiceypy.getelm(
                        _TLE_EPOCH_BASE_YEAR, [line1, line2]
                    )
                except spiceypy.exceptions.SpiceyError:
                    rejected += 1
                    continue
                pairs += 1
                found[norad][round(epoch, 6)] = list(elements)
    if rejected and not pairs:
        # Every pair failing means the toolkit could not read any of them —
        # a missing leapseconds kernel reads exactly like a corrupt archive.
        raise RuntimeError(
            f"tle: all {rejected} line pairs rejected by getelm; is the LSK furnished?"
        )
    if rejected:
        logger.warning("tle: %d line pair(s) rejected by getelm", rejected)
    logger.info(
        "tle: %d element sets from %d line pairs across %d satellite(s)",
        sum(len(v) for v in found.values()),
        pairs,
        len(found),
    )
    return found


def split_runs(element_sets: dict[float, list[float]]) -> list[tuple[list, list]]:
    """Split element sets into contiguous runs at gaps in the tracking."""
    runs: list[tuple[list, list]] = []
    epochs: list[float] = []
    elements: list[list[float]] = []
    for epoch, element_set in sorted(element_sets.items()):
        if epochs and epoch - epochs[-1] > MAX_GAP_DAYS * _S_PER_DAY:
            runs.append((epochs, elements))
            epochs, elements = [], []
        epochs.append(epoch)
        elements.append(element_set)
    if epochs:
        runs.append((epochs, elements))
    return [r for r in runs if len(r[0]) >= MIN_SETS_PER_RUN]


def _is_followed(runs: list[tuple[list, list]]) -> bool:
    """Whether the catalogue followed this craft rather than logging its exit."""
    total = sum(len(epochs) for epochs, _ in runs)
    if total < MIN_ELEMENT_SETS:
        return False
    span = max(epochs[-1] for epochs, _ in runs) - min(epochs[0] for epochs, _ in runs)
    return span >= MIN_SPAN_DAYS * _S_PER_DAY


def _drop_stale(mission_dir: Path, keep: set[str]) -> list[TleSynthResult]:
    """Delete kernels for probes that no longer qualify, so a tightened
    threshold removes what it stops standing behind."""
    index = mission_dir / INDEX_NAME
    if not index.exists():
        return []
    removed: list[TleSynthResult] = []
    for entry in json.loads(index.read_text()).get("files", []):
        filename = entry["name"]
        if filename in keep:
            continue
        (mission_dir / filename).unlink(missing_ok=True)
        naif = (entry.get("targets") or [0])[0]
        drop_file(mission_dir, filename, naif)
        removed.append(TleSynthResult(filename, naif, 0, 0, 0, "removed"))
    return removed


def synthesise_all() -> list[TleSynthResult]:
    """Write a kernel for every registry probe the catalogue followed."""
    candidates = _candidates()
    if not candidates:
        logger.info("tle: no registry probe wants a catalogue trajectory")
        return []

    mission_dir = MISSIONS_DIR / MISSION_DIR_NAME
    mission_dir.mkdir(parents=True, exist_ok=True)
    ensure_index(mission_dir, MISSION_DIR_NAME)

    # `getelm` resolves each TLE epoch to ET, so the leapseconds kernel has to
    # be loaded before a single pair is read.
    furnish_generic_kernels(SOURCES_POSITION_DIR / "spice-kernels")
    try:
        return _synthesise(candidates, mission_dir)
    finally:
        spiceypy.kclear()


def _synthesise(candidates: dict[int, dict], mission_dir: Path) -> list[TleSynthResult]:
    fingerprints = archive_zip_fingerprints(ARCHIVE_YEARS)
    signatures = {
        naif: _signature(int(entry["norad_cat_id"]), fingerprints)
        for naif, entry in candidates.items()
    }
    results: list[TleSynthResult] = []
    keep: set[str] = set()
    stale: set[int] = set()
    for naif, entry in candidates.items():
        norad = int(entry["norad_cat_id"])
        filename = f"{naif}{EXTRAP_SUFFIX}"
        cached = cached_provenance(mission_dir, filename, PROVENANCE_KEY)
        if cached is not None and cached.get("signature") == signatures[naif]:
            keep.add(filename)
            results.append(
                TleSynthResult(
                    entry.get("name") or str(norad),
                    naif,
                    norad,
                    cached.get("element_sets", 0),
                    cached.get("runs", 0),
                    "unchanged",
                )
            )
            continue
        stale.add(naif)

    if not stale:
        logger.info("tle: %d kernel(s) unchanged; archive not read", len(results))
        results.extend(_drop_stale(mission_dir, keep))
        return results

    collected = collect_element_sets(
        {int(candidates[naif]["norad_cat_id"]) for naif in stale}
    )
    for naif in sorted(stale):
        entry = candidates[naif]
        norad = int(entry["norad_cat_id"])
        name = entry.get("name") or str(norad)
        runs = split_runs(collected.get(norad, {}))
        total = sum(len(epochs) for epochs, _ in runs)
        if not runs or not _is_followed(runs):
            logger.info(
                "tle: %s (NORAD %d) has %d element set(s); the catalogue logged "
                "its exit rather than following it — no kernel",
                name,
                norad,
                total,
            )
            results.append(TleSynthResult(name, naif, norad, total, 0, "too-sparse"))
            continue

        filename = f"{naif}{EXTRAP_SUFFIX}"
        out_path = mission_dir / filename
        tmp_path = out_path.with_suffix(out_path.suffix + ".tmp")
        segments = [
            (epochs, elements, f"TLE {norad} {name}") for epochs, elements in runs
        ]
        try:
            write_type10(tmp_path, naif, f"tle{norad}", segments)
        except spiceypy.exceptions.SpiceyError:
            logger.exception("tle: spkw10 failed for %s (NORAD %d)", name, norad)
            tmp_path.unlink(missing_ok=True)
            continue
        tmp_path.replace(out_path)
        keep.add(filename)
        record_file(
            mission_dir,
            filename,
            naif,
            PROVENANCE_KEY,
            {
                "signature": signatures[naif],
                "norad": norad,
                "element_sets": total,
                "runs": len(runs),
                "first_epoch_et": min(epochs[0] for epochs, _ in runs),
                "last_epoch_et": max(epochs[-1] for epochs, _ in runs),
                "median_error_km": 24.0,
            },
            create_missing=True,
        )
        results.append(TleSynthResult(name, naif, norad, total, len(runs), "written"))

    results.extend(_drop_stale(mission_dir, keep))
    counts = collections.Counter(r.action for r in results)
    logger.info(
        "tle: %d probe(s) considered → %d written, %d unchanged, %d too sparse, "
        "%d removed",
        len(candidates),
        counts["written"],
        counts["unchanged"],
        counts["too-sparse"],
        counts["removed"],
    )
    return results


class SpacetrackTleDownloader(Downloader):
    """Synthesise catalogue-derived kernels in the download phase. No HTTP —
    it slots into the orchestrator so it runs after the archives and the other
    synthesisers without bespoke wiring."""

    name = PROVIDERS.SPICE_SPACETRACK_TLE

    def __init__(self, client: httpx.Client) -> None:
        self.client = client  # base-class contract; unused (no HTTP)
        self.out_dir = MISSIONS_DIR / MISSION_DIR_NAME
        self.out_dir.mkdir(parents=True, exist_ok=True)

    def is_complete(self, limit: int | None) -> bool:
        # The signature in _index.json already short-circuits per-probe.
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
