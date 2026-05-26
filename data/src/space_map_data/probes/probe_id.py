"""Stable per-probe identifier, packed into a single int32.

NAIF IDs are recycled across missions (NAIF -76 was Mariner 10 and is now MSL,
NAIF -12 is shared by LADEE and Pioneer Venus Multiprobe, etc.), so they can't
serve as a primary key for spacecraft. COSPAR survives forever but is
non-numeric and ambiguous when one launch carries multiple operated
spacecraft (rover + cruise stage + lander).

A `probe_id` packs the spacecraft's inception MJD with a per-day dedupe index:

    probe_id = ((mjd - MJD_EPOCH) << DEDUPE_BITS) | (dedupe & DEDUPE_MASK)

`MJD_EPOCH` corresponds to 1945-01-01 so the date field starts at zero for
the post-WWII era (sub-Sputnik margin for any future archival reclassification
of V-2 / early rocket trajectories). 20-bit date × 12-bit dedupe fits int32 and
covers up to year ~4817 with 4096 distinct probes per inception day.

Inception date is the start of the spacecraft's longest contiguous SPK
coverage interval at first registration. Persisted to `REGISTRY_PATH` so
probe_ids stay stable across DB rebuilds even when new kernels arrive that
shift the longest interval.

The registry file is the curated source of truth for probe identity. It's
not a cache — once an entry is written it persists, and identity fields
(`name`, `cospar_id`, `norad_cat_id`, `wikidata_qid`) are hand-edited or
filled by `scripts/populate_probe_registry.py`. Ingest reads from it; it
never gets regenerated from scratch.
"""

import json
import logging
from dataclasses import dataclass

from space_map_data.utils.paths import DOWNLOAD_DIR

logger = logging.getLogger(__name__)

# 1945-01-01 in MJD. JD(1945-01-01) = 2431456.5, MJD = JD - 2400000.5.
MJD_EPOCH = 31412

DEDUPE_BITS = 12
DEDUPE_MASK = (1 << DEDUPE_BITS) - 1  # 4095
MAX_DEDUPE = DEDUPE_MASK
DATE_BITS = 32 - DEDUPE_BITS  # 20 bits
MAX_DATE_OFFSET = (1 << DATE_BITS) - 1  # ~2872 years past 1945

REGISTRY_PATH = DOWNLOAD_DIR / "spice" / "probe_ids.json"
# Back-compat alias for callers that still import the old name. Remove after
# everything outside this module is updated.
CACHE_PATH = REGISTRY_PATH

# ET (TDB seconds past J2000) → MJD. J2000 = MJD 51544.5.
_J2000_MJD = 51544.5
_S_PER_DAY = 86400.0


def et_to_mjd(et: float) -> int:
    """Convert ephemeris time (TDB seconds past J2000) to integer MJD."""
    return int((et / _S_PER_DAY) + _J2000_MJD)


@dataclass(frozen=True)
class ProbeIdRecord:
    mission: str
    naif_id: int
    inception_mjd: int
    dedupe: int
    # Human-readable name used as `Object.name`. The export's per-language
    # bundle overrides this with the Wikidata label at display time, so this
    # is mostly the search-fallback and the in-DB identifier of last resort.
    name: str | None = None
    wikidata_qid: str | None = None
    # Cross-references for spacecraft also catalogued by CelesTrak/SATCAT.
    # The satcat-side ingest matches on these to point Satcat / CelesTrak
    # rows at this probe-* Object instead of minting a parallel
    # `norad_satcat-N`. Sub-spacecraft sharing a launch with the parent
    # (Huygens ↔ Cassini, LICIACube ↔ DART) and entries whose Horizons MB
    # designation is missing also need these patched in by hand.
    cospar_id: str | None = None
    norad_cat_id: int | None = None

    @property
    def probe_id(self) -> int:
        return encode(self.inception_mjd, self.dedupe)


def encode(inception_mjd: int, dedupe: int) -> int:
    """Pack an inception MJD + dedupe index into a single int32."""
    offset = inception_mjd - MJD_EPOCH
    if offset < 0:
        raise ValueError(
            f"inception MJD {inception_mjd} predates the 1945 epoch (MJD {MJD_EPOCH})"
        )
    if offset > MAX_DATE_OFFSET:
        raise ValueError(
            f"inception MJD offset {offset} exceeds the {DATE_BITS}-bit budget"
        )
    if not 0 <= dedupe <= MAX_DEDUPE:
        raise ValueError(f"dedupe {dedupe} out of range [0, {MAX_DEDUPE}]")
    return (offset << DEDUPE_BITS) | dedupe


def decode(probe_id: int) -> tuple[int, int]:
    """Return (inception_mjd, dedupe) from a packed probe_id."""
    offset = probe_id >> DEDUPE_BITS
    dedupe = probe_id & DEDUPE_MASK
    return MJD_EPOCH + offset, dedupe


def load_registry() -> dict[str, dict]:
    """Read the on-disk probe registry. Returns {} if missing or unreadable."""
    if not REGISTRY_PATH.exists():
        return {}
    try:
        return json.loads(REGISTRY_PATH.read_text())
    except (OSError, json.JSONDecodeError) as exc:
        logger.warning(
            "probe registry at %s unreadable (%s); treating as empty",
            REGISTRY_PATH,
            exc,
        )
        return {}


def save_registry(registry: dict[str, dict]) -> None:
    REGISTRY_PATH.parent.mkdir(parents=True, exist_ok=True)
    REGISTRY_PATH.write_text(json.dumps(registry, indent=2, sort_keys=True))


def registry_key(mission: str, naif_id: int) -> str:
    return f"{mission}/{naif_id}"


# Back-compat aliases. Prefer the new names in new code.
_load_cache = load_registry
_save_cache = save_registry
_cache_key = registry_key


def load_probe_labels() -> dict[int, str]:
    """`probe_id → "Label/naif"` for the on-disk cache.

    Label is the mission folder name by default, except for HORIZONS-SYNTH
    where the umbrella name is replaced with the per-naif Horizons
    spacecraft name from `missions/HORIZONS-SYNTH/_index.json` (so probes
    read as "Aditya-L1 (spacecraft)/-156" rather than "HORIZONS-SYNTH/-156"
    in the diagnostic scripts). Falls back gracefully when the synth index
    is missing or unreadable.
    """
    registry = load_registry()
    labels: dict[int, str] = {int(r["probe_id"]): key for key, r in registry.items()}

    synth_idx = (
        DOWNLOAD_DIR
        / "spice"
        / "kernels"
        / "missions"
        / "HORIZONS-SYNTH"
        / "_index.json"
    )
    if not synth_idx.exists():
        return labels
    try:
        idx = json.loads(synth_idx.read_text())
    except (OSError, json.JSONDecodeError):
        return labels
    naif_to_name: dict[int, str] = {
        int(t): f["name_horizons"]
        for f in idx.get("files", [])
        for t in f.get("targets", [])
        if f.get("name_horizons")
    }
    for r in registry.values():
        if r.get("mission") != "HORIZONS-SYNTH":
            continue
        nm = naif_to_name.get(int(r["naif_id"]))
        if nm:
            labels[int(r["probe_id"])] = f"{nm}/{r['naif_id']}"
    return labels


def _record_from_entry(mission: str, naif_id: int, entry: dict) -> ProbeIdRecord:
    return ProbeIdRecord(
        mission=mission,
        naif_id=naif_id,
        inception_mjd=int(entry["inception_mjd"]),
        dedupe=int(entry["dedupe"]),
        name=entry.get("name"),
        wikidata_qid=entry.get("wikidata_qid"),
        cospar_id=entry.get("cospar_id"),
        norad_cat_id=entry.get("norad_cat_id"),
    )


def assign(
    mission: str,
    naif_id: int,
    inception_mjd: int,
    registry: dict[str, dict] | None = None,
) -> ProbeIdRecord:
    """Return a stable probe_id for `(mission, naif_id)`.

    First call for a key allocates a dedupe slot (the lowest unused integer
    for the inception date, deterministic across runs) and persists the
    entry. Later calls return the persisted value even if `inception_mjd`
    shifts — the registered inception MJD wins, so adding earlier-coverage
    kernels later doesn't renumber existing probes.
    """
    owned = registry is None
    if registry is None:
        registry = load_registry()
    key = registry_key(mission, naif_id)
    if key in registry:
        return _record_from_entry(mission, naif_id, registry[key])

    used = {
        int(r["dedupe"])
        for r in registry.values()
        if int(r["inception_mjd"]) == inception_mjd
    }
    dedupe = next(i for i in range(MAX_DEDUPE + 1) if i not in used)
    record = ProbeIdRecord(mission, naif_id, inception_mjd, dedupe)
    registry[key] = {
        "mission": mission,
        "naif_id": naif_id,
        "inception_mjd": inception_mjd,
        "dedupe": dedupe,
        "probe_id": record.probe_id,
        "name": None,
        "wikidata_qid": None,
        "cospar_id": None,
        "norad_cat_id": None,
    }
    if owned:
        save_registry(registry)
    return record


def load_qids() -> set[str]:
    """Return every non-null `wikidata_qid` in the probe registry."""
    return {qid for rec in load_registry().values() if (qid := rec.get("wikidata_qid"))}


def assign_many(
    items: list[tuple[str, int, int]],
) -> dict[tuple[str, int], ProbeIdRecord]:
    """Bulk-assign probe IDs. Loads & saves the registry once.

    `items` is a list of `(mission, naif_id, inception_mjd)`. Deterministic
    over input order — when two items share an inception date and neither is
    registered yet, dedupe slots are assigned in the order they appear in
    `items`. Callers should pre-sort by `(inception_mjd, naif_id)` for stable
    output across runs.
    """
    registry = load_registry()
    out: dict[tuple[str, int], ProbeIdRecord] = {}
    for mission, naif_id, mjd in items:
        out[(mission, naif_id)] = assign(mission, naif_id, mjd, registry=registry)
    save_registry(registry)
    return out
