"""Bulk selection from the Horizons MB list + mission-index emission."""

import json
import logging
import re

import orjson

from space_map_data.utils.paths import DOWNLOAD_DIR

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


def qid_deduped_synth_naifs(cache: dict[str, dict] | None = None) -> set[int]:
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
    """
    from space_map_data.probes.probe_id import _load_cache

    if cache is None:
        cache = _load_cache()
    missions_dir = DOWNLOAD_DIR / "spice" / "kernels" / "missions"
    spk_missions: set[str] = set()
    if missions_dir.exists():
        spk_missions = {
            p.name
            for p in missions_dir.iterdir()
            if p.is_dir()
            and p.name != "HORIZONS-SYNTH"
            and (p / "_index.json").exists()
        }
    agency_qids: set[str] = {
        r["wikidata_qid"]
        for r in cache.values()
        if r.get("mission") in spk_missions and r.get("wikidata_qid")
    }
    return {
        int(r["naif_id"])
        for r in cache.values()
        if r.get("mission") == "HORIZONS-SYNTH" and r.get("wikidata_qid") in agency_qids
    }


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
    per-mission index plus per-file `name_horizons` and `revised` carried
    from the cached meta (used by the future precedence resolver — synth
    wins over agency only when synth `revised` is newer than agency mtime).
    """
    SYNTH_KERNELS_DIR.mkdir(parents=True, exist_ok=True)
    files = []
    targets: dict[str, list[str]] = {}
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
