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
coverage interval at first registration. Persisted to `REGISTRY_PATH` and
**frozen** thereafter — `assign()` reuses the stored value rather than
recomputing, so adding earlier-coverage kernels later doesn't shift
`probe_id`, which would break URL stability.

File shape: a JSON list of entries. Each entry has

    probe_id, name, naif_id, inception_mjd, dedupe,
    wikidata_qid, cospar_id, norad_cat_id,
    kernel_sources: [{"mission": ..., "naif_id": ...}, ...]

`kernel_sources` is the source of truth for which (mission, naif_id) pairs in
the SPICE tree contribute kernels to this probe — joint-mission folders
(Cassini orbiter exposed under both CASSINI/-82 and HUYGENS/-82) declare both
sources on the same canonical entry rather than minting two probe rows.

The registry is the curated source of truth for probe identity. It's not a
cache — once an entry exists it persists, identity fields are hand-edited,
and frozen fields (`probe_id`, `inception_mjd`, `dedupe`) are never
overwritten.
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

# ET (TDB seconds past J2000) → MJD. J2000 = MJD 51544.5.
_J2000_MJD = 51544.5
_S_PER_DAY = 86400.0


def et_to_mjd(et: float) -> int:
    """Convert ephemeris time (TDB seconds past J2000) to integer MJD."""
    return int((et / _S_PER_DAY) + _J2000_MJD)


@dataclass(frozen=True)
class ProbeIdRecord:
    probe_id: int
    naif_id: int
    inception_mjd: int
    dedupe: int
    # Tuple of (mission, naif_id) pairs naming every kernel-folder source that
    # contributes trajectory data to this probe. Length ≥ 1. The first source
    # is canonical (used as the "mission" identity in legacy contexts).
    kernel_sources: tuple[tuple[str, int], ...]
    name: str | None = None
    wikidata_qid: str | None = None
    # Cross-references for spacecraft also catalogued by CelesTrak/SATCAT.
    cospar_id: str | None = None
    norad_cat_id: int | None = None

    @property
    def mission(self) -> str:
        """Canonical mission (first kernel source's mission folder)."""
        return self.kernel_sources[0][0]


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


def load_registry() -> list[dict]:
    """Read the on-disk probe registry. Returns [] if missing or unreadable."""
    if not REGISTRY_PATH.exists():
        return []
    try:
        data = json.loads(REGISTRY_PATH.read_text())
    except (OSError, json.JSONDecodeError) as exc:
        logger.warning(
            "probe registry at %s unreadable (%s); treating as empty",
            REGISTRY_PATH,
            exc,
        )
        return []
    if not isinstance(data, list):
        raise ValueError(
            f"probe registry at {REGISTRY_PATH} must be a JSON list of entries"
        )
    return data


def save_registry(registry: list[dict]) -> None:
    """Persist the registry. Entries are sorted by probe_id for stable diffs."""
    REGISTRY_PATH.parent.mkdir(parents=True, exist_ok=True)
    REGISTRY_PATH.write_text(
        json.dumps(sorted(registry, key=lambda e: e["probe_id"]), indent=2)
    )


def index_by_source(registry: list[dict]) -> dict[tuple[str, int], dict]:
    """Build a `(mission, naif_id) → entry` lookup from every kernel source."""
    out: dict[tuple[str, int], dict] = {}
    for entry in registry:
        for src in entry["kernel_sources"]:
            out[(src["mission"], int(src["naif_id"]))] = entry
    return out


def load_probe_labels() -> dict[int, str]:
    """`probe_id → "<canonical-name>/<naif>"` for diagnostic scripts.

    Label is the canonical mission folder name by default, except for
    HORIZONS-SYNTH where the umbrella name is replaced with the per-naif
    Horizons spacecraft name from `missions/HORIZONS-SYNTH/_index.json` (so
    probes read as "Aditya-L1 (spacecraft)/-156" rather than
    "HORIZONS-SYNTH/-156"). Falls back gracefully when the synth index is
    missing or unreadable.
    """
    registry = load_registry()
    labels: dict[int, str] = {}
    for entry in registry:
        mission, naif_id = entry["kernel_sources"][0]["mission"], entry["naif_id"]
        labels[int(entry["probe_id"])] = f"{mission}/{naif_id}"

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
    for entry in registry:
        # Only relabel entries whose first (canonical) kernel source is the
        # synth folder — agency-canonical probes that happen to ALSO include
        # a HORIZONS-SYNTH source keep their agency name.
        if entry["kernel_sources"][0]["mission"] != "HORIZONS-SYNTH":
            continue
        nm = naif_to_name.get(int(entry["naif_id"]))
        if nm:
            labels[int(entry["probe_id"])] = f"{nm}/{entry['naif_id']}"
    return labels


def _record_from_entry(entry: dict) -> ProbeIdRecord:
    sources = tuple(
        (src["mission"], int(src["naif_id"])) for src in entry["kernel_sources"]
    )
    return ProbeIdRecord(
        probe_id=int(entry["probe_id"]),
        naif_id=int(entry["naif_id"]),
        inception_mjd=int(entry["inception_mjd"]),
        dedupe=int(entry["dedupe"]),
        kernel_sources=sources,
        name=entry.get("name"),
        wikidata_qid=entry.get("wikidata_qid"),
        cospar_id=entry.get("cospar_id"),
        norad_cat_id=entry.get("norad_cat_id"),
    )


def assign(
    mission: str,
    naif_id: int,
    inception_mjd: int,
    registry: list[dict] | None = None,
    source_index: dict[tuple[str, int], dict] | None = None,
) -> ProbeIdRecord:
    """Return a stable probe_id for `(mission, naif_id)`.

    Looks up an existing entry whose `kernel_sources` contains the given
    (mission, naif_id). If found, returns it verbatim — `probe_id`,
    `inception_mjd`, and `dedupe` are frozen on the persisted entry, so
    re-computed inception drift doesn't renumber existing probes.

    Otherwise allocates a new entry: the lowest unused dedupe slot for the
    inception MJD, with the new `(mission, naif_id)` as the sole
    kernel_source. The caller is responsible for save_registry() if
    `registry` is supplied; in stand-alone mode (registry=None) this
    function loads + saves.
    """
    owned = registry is None
    if registry is None:
        registry = load_registry()
    if source_index is None:
        source_index = index_by_source(registry)

    existing = source_index.get((mission, naif_id))
    if existing is not None:
        return _record_from_entry(existing)

    used = {
        int(e["dedupe"]) for e in registry if int(e["inception_mjd"]) == inception_mjd
    }
    dedupe = next(i for i in range(MAX_DEDUPE + 1) if i not in used)
    probe_id = encode(inception_mjd, dedupe)
    entry = {
        "probe_id": probe_id,
        "name": None,
        "naif_id": naif_id,
        "inception_mjd": inception_mjd,
        "dedupe": dedupe,
        "wikidata_qid": None,
        "cospar_id": None,
        "norad_cat_id": None,
        "kernel_sources": [{"mission": mission, "naif_id": naif_id}],
    }
    registry.append(entry)
    source_index[(mission, naif_id)] = entry
    if owned:
        save_registry(registry)
    return _record_from_entry(entry)


def load_qids() -> set[str]:
    """Return every non-null `wikidata_qid` in the probe registry."""
    return {qid for entry in load_registry() if (qid := entry.get("wikidata_qid"))}


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
    source_index = index_by_source(registry)
    out: dict[tuple[str, int], ProbeIdRecord] = {}
    for mission, naif_id, mjd in items:
        out[(mission, naif_id)] = assign(
            mission, naif_id, mjd, registry=registry, source_index=source_index
        )
    save_registry(registry)
    return out
