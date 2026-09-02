"""Bulk selection from the Horizons MB list + mission-index emission."""

import csv
import json
import logging
import re
from collections import defaultdict

import orjson

from space_map_data.constants.earth_sats.satcat import (
    OrbitCenter,
    parse_orbit_center,
)
from space_map_data.utils.paths import SOURCES_POSITION_DIR

from ..naif_http import merge_intervals, spk_coverage
from .horizons_api import HORIZONS_URL
from .layout import SYNTH_CACHE_ROOT, SYNTH_KERNELS_DIR

logger = logging.getLogger(__name__)


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

# COSPAR designator format printed in the MB list's "Designation" column.
_COSPAR_RE = re.compile(r"^\d{4}-\d{3}[A-Z]+$")


def _parse_horizons_spacecraft(mb_text: str) -> list[tuple[int, str, str | None]]:
    """Parse Horizons MB listing → [(naif_id, name, cospar)] for real spacecraft.

    `cospar` is the contents of the MB list's "Designation" column (cols 46-56)
    when it matches `YYYY-NNNX`, else None. `_NAME_DROP_PATTERNS` is applied
    here; the SATCAT orbit-centre filter runs separately at the caller, which
    reads from disk and shouldn't be coupled to a pure parser.
    """
    out: list[tuple[int, str, str | None]] = []
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
        designation = line[46:57].strip() if len(line) > 46 else ""
        cospar = designation if _COSPAR_RE.match(designation) else None
        out.append((naif_id, name, cospar))
    return sorted(out, key=lambda r: -abs(r[0]))


def earth_orbit_excludes(candidates: list[tuple[int, str, str | None]]) -> set[int]:
    """NAIFs to drop as uncurated Earth satellites, not worth synthesising.

    Space-Track already holds an Earth orbiter's trajectory, in element sets
    far denser than Horizons samples, so a synth kernel for one is work whose
    only effect is to grow the registry with satellites.

    Only ever a spending decision. The manifest says what is a probe, and a
    candidate it claims is kept whatever SATCAT calls the orbit — SATCAT
    records the parking orbit of a craft that left Earth, so TESS, the
    Artemis-1 cubesats and Chang'e 3 all read as Earth-orbiting there, and
    TESS has no other source to fall back on. A claim is read off the
    registry's own `HORIZONS-SYNTH/<naif>` key first and its COSPAR only
    second: Horizons designates Chang'e 3 differently from SATCAT, and
    EQUULEUS has no COSPAR at all.
    """
    from space_map_data.probes.events import manifest_probe_ids
    from space_map_data.probes.probe_id import HORIZONS_SYNTH_MISSION, load_registry

    satcat = SOURCES_POSITION_DIR / "celestrak" / "satcat.csv"
    if not satcat.exists():
        logger.warning("no satcat.csv at %s; keeping every candidate", satcat)
        return set()
    manifest = manifest_probe_ids()
    claimed_naifs: set[int] = set()
    claimed_cospars: set[str] = set()
    for entry in load_registry():
        if entry["probe_id"] not in manifest:
            continue
        if entry.get("cospar_id"):
            claimed_cospars.add(entry["cospar_id"])
        claimed_naifs.update(
            int(src["naif_id"])
            for src in entry["kernel_sources"]
            if src["mission"] == HORIZONS_SYNTH_MISSION
        )
    wanted = {
        cospar
        for naif, _name, cospar in candidates
        if cospar and cospar not in claimed_cospars and naif not in claimed_naifs
    }
    earth_bound: set[str] = set()
    with satcat.open() as f:
        for row in csv.DictReader(f):
            cospar = (row.get("OBJECT_ID") or "").strip()
            if cospar in wanted:
                centre, _docked = parse_orbit_center(row.get("ORBIT_CENTER"))
                if centre is OrbitCenter.EARTH:
                    earth_bound.add(cospar)
    excludes = {naif for naif, _name, cospar in candidates if cospar in earth_bound}
    logger.info(
        "SATCAT orbit-centre filter: %d / %d candidates are uncurated Earth satellites",
        len(excludes),
        len(candidates),
    )
    return excludes


def qid_deduped_synth_naifs(registry: list[dict] | None = None) -> set[int]:
    """NAIF IDs of HORIZONS-SYNTH probes whose QID matches an SPK-backed agency probe.

    Resolves cases where Horizons assigns its own NAIF to a spacecraft already
    served by an agency SPK under a different NAIF (e.g. INTEGRAL: agency -275
    / Horizons -198, both Q50021). Horizons' coarse ephemerides can't resolve
    highly elliptical perigee passes and may place the probe below the central
    body's surface, so the agency SPK always wins when both exist. Consulted
    both at synthesis (skips re-fetch) and export-enumeration (drops the synth
    from the chunk plan even if `_index.json` still lists it).

    Only agency missions that publish SPK kernels count as "covered" —
    metadata-only buckets like EVENTS-DB carry probe-events but no ephemeris,
    so deduping against them would leave a probe with no trajectory at all
    (e.g. Tianwen-1 has only the Horizons synth, at NAIF -86).
    """
    from space_map_data.probes.probe_id import load_registry

    if registry is None:
        registry = load_registry()
    missions_dir = SOURCES_POSITION_DIR / "spice-kernels" / "missions"
    spk_missions: set[str] = set()
    if missions_dir.exists():
        spk_missions = {
            p.name
            for p in missions_dir.iterdir()
            if p.is_dir()
            and p.name != "HORIZONS-SYNTH"
            and (p / "_index.json").exists()
        }

    def _primary_mission(entry: dict) -> str | None:
        sources = entry.get("kernel_sources") or []
        return sources[0]["mission"] if sources else None

    agency_qids: set[str] = {
        entry["wikidata_qid"]
        for entry in registry
        if _primary_mission(entry) in spk_missions and entry.get("wikidata_qid")
    }
    return {
        int(entry["naif_id"])
        for entry in registry
        if _primary_mission(entry) == "HORIZONS-SYNTH"
        and entry.get("wikidata_qid") in agency_qids
    }


def agency_naif_coverage(
    exclude_mission: str | None = None,
) -> dict[int, list[tuple[float, float]]]:
    """Merged ET coverage per negative NAIF across agency missions/.

    Reads `targets_coverage` from each `_index.json`; falls back to opening
    the SPKs with `spkcov` when an index predates the coverage field.
    """
    missions_dir = SOURCES_POSITION_DIR / "spice-kernels" / "missions"
    by_naif: dict[int, list[tuple[float, float]]] = defaultdict(list)
    if not missions_dir.exists():
        return {}
    for mdir in missions_dir.iterdir():
        if not mdir.is_dir() or mdir.name == exclude_mission:
            continue
        idx_path = mdir / "_index.json"
        if not idx_path.exists():
            continue
        try:
            idx = json.loads(idx_path.read_text())
        except json.JSONDecodeError, OSError:
            continue
        tc = idx.get("targets_coverage")
        if tc:
            for naif_str, intervals in tc.items():
                try:
                    naif = int(naif_str)
                except ValueError:
                    continue
                if naif >= 0:
                    continue
                by_naif[naif].extend((float(s), float(e)) for s, e in intervals)
        else:
            for naif_str, fnames in idx.get("targets", {}).items():
                try:
                    naif = int(naif_str)
                except ValueError:
                    continue
                if naif >= 0:
                    continue
                for fname in fnames:
                    by_naif[naif].extend(spk_coverage(mdir / fname, naif))
    return {n: merge_intervals(iv) for n, iv in by_naif.items()}


def _write_index(
    coverage: dict[int, str], cospars: dict[int, str | None] | None = None
) -> None:
    """Emit a `missions/HORIZONS-SYNTH/_index.json` so the ingest walker finds
    these kernels alongside the rest. Matches ProbesDownloader's per-mission
    index plus per-file `name_horizons`/`revised` (for a future precedence
    resolver: synth wins over agency only when its `revised` is newer) and the
    MB list's `cospar`, which is how a kernel reaches the probe it belongs to
    when that probe was registered from the events database under a synthetic
    NAIF of its own.
    """
    SYNTH_KERNELS_DIR.mkdir(parents=True, exist_ok=True)
    files = []
    targets: dict[str, list[str]] = {}
    targets_coverage: dict[str, list[list[float]]] = {}
    for naif_id, name in sorted(coverage.items()):
        spk = SYNTH_KERNELS_DIR / f"{naif_id}.bsp"
        if not spk.exists():
            continue
        meta_path = SYNTH_CACHE_ROOT / str(naif_id) / "meta.json"
        revised = "unknown"
        if meta_path.exists():
            try:
                revised = orjson.loads(meta_path.read_bytes()).get("revised", "unknown")
            except orjson.JSONDecodeError, OSError:
                pass
        files.append(
            {
                "name": spk.name,
                "size_bytes": spk.stat().st_size,
                "targets": [naif_id],
                "name_horizons": name,
                "cospar": (cospars or {}).get(naif_id),
                "revised": revised,
            }
        )
        targets[str(naif_id)] = [spk.name]
        targets_coverage[str(naif_id)] = [list(iv) for iv in spk_coverage(spk, naif_id)]
    (SYNTH_KERNELS_DIR / "_index.json").write_text(
        json.dumps(
            {
                "server": "JPL-Horizons-synth",
                "mission": "HORIZONS-SYNTH",
                "spk_url": HORIZONS_URL,
                "files": files,
                "targets": targets,
                "targets_coverage": targets_coverage,
            },
            indent=2,
            sort_keys=True,
        )
    )
