"""Bulk selection from the Horizons MB list + mission-index emission."""

import csv
import json
import logging
import re
from collections import defaultdict

import orjson

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

# Hand-curated NAIF blocklist for entries the CelesTrak filter can't catch
# (no COSPAR in the MB row, or a special-case override). Most CelesTrak-tracked
# Earth orbiters are filtered automatically via `celestrak_active_excludes()`.
_NAIF_BLOCKLIST: frozenset[int] = frozenset()


class CelestrakWhitelistConflict(RuntimeError):
    """Raised when a CelesTrak-active NAIF is ALSO claimed by an agency probe.

    Means our probe registry and SATCAT/CelesTrak disagree about the same
    spacecraft. Fix the data (drop the stale registry entry or update SATCAT
    cross-references) instead of silently dropping the agency record.
    """


def _parse_horizons_spacecraft(mb_text: str) -> list[tuple[int, str, str | None]]:
    """Parse Horizons MB listing → [(naif_id, name, cospar)] for real spacecraft.

    `cospar` is the contents of the MB list's "Designation" column (cols 46-56)
    when it matches `YYYY-NNNX`, else None. Name patterns from
    `_NAME_DROP_PATTERNS` and the hand-curated `_NAIF_BLOCKLIST` are applied
    here; the CelesTrak/SATCAT cross-reference filter runs separately at the
    caller (it depends on on-disk CelesTrak snapshots and the probe registry,
    which we don't want to couple to a pure parser).
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
        if naif_id in _NAIF_BLOCKLIST:
            continue
        designation = line[46:57].strip() if len(line) > 46 else ""
        cospar = designation if _COSPAR_RE.match(designation) else None
        out.append((naif_id, name, cospar))
    return sorted(out, key=lambda r: -abs(r[0]))


def _latest_gp_active_norads() -> set[int]:
    """NORAD IDs in the freshest `gp-active.csv` snapshot.

    Empty set if no snapshot is on disk yet (e.g. CelesTrak hasn't been
    downloaded) — the synth pipeline then falls back to the legacy behavior of
    accepting every MB candidate.
    """
    celestrak_dir = SOURCES_POSITION_DIR / "celestrak"
    paths = sorted(celestrak_dir.glob("*/*/*/gp-active.csv"))
    if not paths:
        logger.warning(
            "no gp-active.csv under %s; skipping CelesTrak-active filter",
            celestrak_dir,
        )
        return set()
    norads: set[int] = set()
    with paths[-1].open() as f:
        for row in csv.DictReader(f):
            try:
                norads.add(int(row["NORAD_CAT_ID"]))
            except (KeyError, ValueError, TypeError):
                continue
    logger.info(
        "loaded %d CelesTrak-active NORADs from %s",
        len(norads),
        paths[-1].relative_to(SOURCES_POSITION_DIR),
    )
    return norads


def _satcat_cospar_to_norad() -> dict[str, int]:
    """`COSPAR → NORAD CAT ID` from CelesTrak SATCAT. Empty if missing."""
    satcat = SOURCES_POSITION_DIR / "celestrak" / "satcat.csv"
    if not satcat.exists():
        logger.warning("no satcat.csv at %s; cannot resolve COSPAR→NORAD", satcat)
        return {}
    out: dict[str, int] = {}
    with satcat.open() as f:
        for row in csv.DictReader(f):
            cospar = (row.get("OBJECT_ID") or "").strip()
            norad_s = (row.get("NORAD_CAT_ID") or "").strip()
            if not cospar or not norad_s:
                continue
            try:
                out[cospar] = int(norad_s)
            except ValueError:
                continue
    return out


def celestrak_active_excludes(
    candidates: list[tuple[int, str, str | None]],
    registry: list[dict] | None = None,
) -> set[int]:
    """NAIFs to drop because CelesTrak ships their NORAD as a daily-refreshed
    SGP4 element (= no benefit from a parallel Horizons synth SPK).

    Join: candidate COSPAR (MB designator) → NORAD (SATCAT) → membership in
    the latest gp-active.csv snapshot. Candidates without a parseable COSPAR
    are kept (no information to disqualify them).

    Raises `CelestrakWhitelistConflict` if the resulting blacklist overlaps
    the agency-backed probe registry whitelist — meaning two of our sources
    claim the same NAIF and the discrepancy should be resolved before silently
    dropping a probe with real agency SPK coverage.
    """
    from space_map_data.probes.probe_id import load_registry

    active_norads = _latest_gp_active_norads()
    if not active_norads:
        return set()
    cospar_to_norad = _satcat_cospar_to_norad()
    if not cospar_to_norad:
        return set()

    excludes: set[int] = set()
    for naif_id, _name, cospar in candidates:
        if not cospar:
            continue
        norad = cospar_to_norad.get(cospar)
        if norad is None:
            continue
        if norad in active_norads:
            excludes.add(naif_id)

    if registry is None:
        registry = load_registry()
    whitelist = {
        int(entry["naif_id"])
        for entry in registry
        if (entry.get("kernel_sources") or [{"mission": "HORIZONS-SYNTH"}])[0][
            "mission"
        ]
        != "HORIZONS-SYNTH"
    }
    conflict = excludes & whitelist
    if conflict:
        details = []
        by_naif = {int(e["naif_id"]): e for e in registry}
        for n in sorted(conflict):
            entry = by_naif[n]
            details.append(
                f"naif={n} mission={entry['kernel_sources'][0]['mission']} "
                f"name={entry.get('name')!r}"
            )
        raise CelestrakWhitelistConflict(
            "CelesTrak-active filter would drop NAIFs that are agency-backed "
            "in probe registry; resolve before merging. Conflicts:\n  "
            + "\n  ".join(details)
        )

    logger.info(
        "CelesTrak-active filter: dropping %d / %d candidates",
        len(excludes),
        len(candidates),
    )
    return excludes


def qid_deduped_synth_naifs(registry: list[dict] | None = None) -> set[int]:
    """NAIF IDs of HORIZONS-SYNTH probes whose QID matches an SPK-backed agency probe.

    Resolves cases where Horizons assigns its own NAIF to a spacecraft already
    served by an agency SPK under a different NAIF — e.g. INTEGRAL (agency
    -275 / Horizons -198, both Q50021). Horizons' coarse-sampled ephemerides
    cannot resolve highly elliptical perigee passes and may place the probe
    below the central body's surface, so the agency SPK always wins when both
    are present. The filter is consulted at synthesis time (skips re-fetch)
    AND at export-enumeration time (drops the synth probe from the chunk plan
    even when `_index.json` still lists it).

    Only agency missions that publish SPK kernels (those with an
    `<mission>/_index.json` under `missions/`) count as "covered" — metadata-
    only buckets like EVENTS-DB carry probe-events but no ephemeris, so
    deduping a synth against them would leave the probe with no trajectory
    at all (e.g. Tianwen-1 has only the Horizons synth at NAIF -86).

    A registry entry's "mission" is its canonical (first) kernel_source.
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
        except (json.JSONDecodeError, OSError):
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


def _write_index(coverage: dict[int, str]) -> None:
    """Emit a `missions/HORIZONS-SYNTH/_index.json` so the agency ingest walker
    finds these kernels alongside the rest. Schema matches ProbesDownloader's
    per-mission index plus per-file `name_horizons` and `revised` carried
    from the cached meta (used by the future precedence resolver — synth
    wins over agency only when synth `revised` is newer than agency mtime).
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
            except (orjson.JSONDecodeError, OSError):
                pass
        files.append(
            {
                "name": spk.name,
                "size_bytes": spk.stat().st_size,
                "targets": [naif_id],
                "name_horizons": name,
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
