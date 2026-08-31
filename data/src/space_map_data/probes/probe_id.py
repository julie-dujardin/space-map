"""Stable per-probe identifier, packed into a single int32.

NAIF IDs are recycled across missions (-76 was Mariner 10, now MSL), and
COSPAR is non-numeric and ambiguous when one launch carries several
operated spacecraft (rover + cruise stage + lander) — neither works as a
primary key.

    probe_id = ((mjd - MJD_EPOCH) << DEDUPE_BITS) | (dedupe & DEDUPE_MASK)

`MJD_EPOCH` is 1945-01-01 (sub-Sputnik margin for any future V-2 / early
rocket reclassification). 20-bit date x 12-bit dedupe fits int32, covering
year ~4817 with 4096 probes per inception day.

Inception date is the start of the spacecraft's longest contiguous SPK
coverage at first registration, then **frozen**: `assign()` reuses the
stored value, so later-discovered earlier kernels can't shift `probe_id`
and break URL stability.

File shape: a JSON list of entries with `probe_id, name, naif_id,
inception_mjd, dedupe, wikidata_qid, cospar_id, norad_cat_id,
kernel_sources: [{"mission": ..., "naif_id": ...}, ...]`.

`kernel_sources` is the source of truth for which (mission, naif_id) pairs
feed this probe — joint-mission folders (Cassini under both CASSINI/-82
and HUYGENS/-82) declare both sources on one entry instead of two rows.

The registry is curated, not a cache: entries persist once created,
identity fields are hand-edited, and frozen fields (`probe_id`,
`inception_mjd`, `dedupe`) are never overwritten.
"""

import json
import logging
from dataclasses import dataclass

from space_map_data.utils.paths import DERIVED_POSITION_DIR, SOURCES_POSITION_DIR

logger = logging.getLogger(__name__)

# 1945-01-01 in MJD. JD(1945-01-01) = 2431456.5, MJD = JD - 2400000.5.
MJD_EPOCH = 31412

DEDUPE_BITS = 12
DEDUPE_MASK = (1 << DEDUPE_BITS) - 1  # 4095
MAX_DEDUPE = DEDUPE_MASK
DATE_BITS = 32 - DEDUPE_BITS  # 20 bits
MAX_DATE_OFFSET = (1 << DATE_BITS) - 1  # ~2872 years past 1945

REGISTRY_PATH = DERIVED_POSITION_DIR / "tables" / "probe_ids.json"

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


# Sample-return capsules NAIF numbered in the shape of the sub-NAIF patterns
# below: -29900 and -47900 read as landing sites, -64090 as an instrument
# frame under OSIRIS-REx (-64). Each separates from its bus and flies its own
# entry trajectory, so name them rather than loosen rules that correctly
# exclude MER's -253900 and Curiosity's arm joints.
SAMPLE_RETURN_NAIFS: frozenset[int] = frozenset(
    {
        -29900,  # Stardust SRC
        -47900,  # Genesis SRC
        -64090,  # OSIRIS-REx SRC
    }
)


def is_spacecraft_naif(naif: int, all_targets: set[int]) -> bool:
    """True if `naif` is a real spacecraft target, not a landing-site or
    instrument/frame sub-NAIF. Shared so ingest and the export's
    `enumerate_probes` agree on what gets a probe row.

    Excludes landing-site NAIFs `-X900` (spacecraft x 1000 - 900, fixed
    body points) and instrument NAIFs `-X*1000 - k` when `-X` is itself a
    target (MSL rover -76's arm joints -76501..-76620, Perseverance -168's
    -168501..-168587 frames), less the `SAMPLE_RETURN_NAIFS` exceptions.
    """
    if naif >= 0:
        return False
    if naif in SAMPLE_RETURN_NAIFS:
        return True
    n = -naif
    if n % 1000 == 900:
        return False
    if n > 1000 and n % 1000 != 0 and -(n // 1000) in all_targets:
        return False
    return True


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
    """`probe_id -> "<canonical-name>/<naif>"` for diagnostic scripts.

    Label is the canonical mission folder name, except HORIZONS-SYNTH
    entries get the per-naif Horizons spacecraft name from
    `missions/HORIZONS-SYNTH/_index.json` ("Aditya-L1 (spacecraft)/-156"
    instead of "HORIZONS-SYNTH/-156"). Falls back gracefully if the synth
    index is missing.
    """
    registry = load_registry()
    labels: dict[int, str] = {}
    for entry in registry:
        mission, naif_id = entry["kernel_sources"][0]["mission"], entry["naif_id"]
        labels[int(entry["probe_id"])] = f"{mission}/{naif_id}"

    synth_idx = (
        SOURCES_POSITION_DIR
        / "spice-kernels"
        / "missions"
        / "HORIZONS-SYNTH"
        / "_index.json"
    )
    if not synth_idx.exists():
        return labels
    try:
        idx = json.loads(synth_idx.read_text())
    except OSError, json.JSONDecodeError:
        return labels
    naif_to_name: dict[int, str] = {
        int(t): f["name_horizons"]
        for f in idx.get("files", [])
        for t in f.get("targets", [])
        if f.get("name_horizons")
    }
    for entry in registry:
        # Only relabel entries whose first (canonical) source is the synth
        # folder — probes that merely also include a HORIZONS-SYNTH source
        # keep their agency name.
        if entry["kernel_sources"][0]["mission"] != "HORIZONS-SYNTH":
            continue
        nm = naif_to_name.get(int(entry["naif_id"]))
        if nm:
            labels[int(entry["probe_id"])] = f"{nm}/{entry['naif_id']}"
    return labels


# Mission names the registry treats specially, spelled once here because the
# producers, the export credit table and the registry itself all have to agree
# on them. `EVENTS-DB` is a probe registered from the events database with no
# kernels at all.
EVENTS_DB_MISSION = "EVENTS-DB"
EVENTS_STATE_MISSION = "EVENTS-STATE"
GCAT_DEEP_MISSION = "GCAT-DEEP"
HORIZONS_SYNTH_MISSION = "HORIZONS-SYNTH"
SPACETRACK_TLE_MISSION = "SPACETRACK-TLE"

# Folders holding a trajectory we derived rather than one an archive published:
# a two-body extension, a conic solved from a catalogue, element sets read out
# of the Space-Track archive. A probe carrying only these still counts as
# having no trajectory of its own, which is what the synthesisers select on.
DERIVED_MISSIONS: frozenset[str] = frozenset(
    {EVENTS_STATE_MISSION, GCAT_DEEP_MISSION, SPACETRACK_TLE_MISSION}
)

# Folders we write rather than mirror. Each holds kernels for a probe that
# already exists under some other source, so they attach to its entry instead
# of allocating a second probe for the same spacecraft. Horizons synthesis
# belongs here and not in DERIVED_MISSIONS: it is JPL's own ephemeris, just
# delivered as vectors rather than as a kernel.
SYNTHETIC_MISSIONS: frozenset[str] = DERIVED_MISSIONS | {HORIZONS_SYNTH_MISSION}

_NON_ARCHIVE_MISSIONS = DERIVED_MISSIONS | {EVENTS_DB_MISSION}


def has_archive_trajectory(entry: dict) -> bool:
    """Whether the probe already has a trajectory from somewhere real.

    Asked of the registry entry rather than of a NAIF, because the two do not
    line up: a probe's `naif_id` is whichever id first registered it, while its
    archive kernels can sit under a different id entirely — Stardust is
    registered as -90000165 from the events database and tracked as -29 by
    Horizons.
    """
    return any(
        source.get("mission") not in _NON_ARCHIVE_MISSIONS
        for source in entry.get("kernel_sources") or []
    )


def synthetic_sources(entry: dict) -> set[str]:
    """Which derived-kernel folders already claim this probe."""
    return {
        source.get("mission")
        for source in entry.get("kernel_sources") or []
        if source.get("mission") in SYNTHETIC_MISSIONS
    }


def _attach_synthetic_source(
    registry: list[dict], mission: str, naif_id: int, cospar: str | None = None
) -> dict | None:
    """Append ``mission`` to the entry that already owns this spacecraft.

    Matched on NAIF first, then on COSPAR. The second pass is what joins a
    real kernel to a probe the events database registered: that probe's
    ``naif_id`` is a synthetic one that indexes no kernel anywhere, so a NAIF
    match can never find it and the kernel would allocate a parallel probe for
    the same spacecraft — which is how DSCOVR ended up with its L1 trajectory
    on one page and its mission on another.

    Returns None when no entry owns it, or when more than one does — NAIF ids
    are reused across missions decades apart, and guessing which spacecraft a
    synthesised kernel belongs to would silently graft a trajectory onto the
    wrong probe.
    """
    owners = [e for e in registry if int(e["naif_id"]) == naif_id]
    matched_on = "NAIF"
    if not owners and cospar:
        owners = [e for e in registry if e.get("cospar_id") == cospar]
        matched_on = "COSPAR"
    if len(owners) != 1:
        if owners:
            logger.warning(
                "%s/%d: %d registry entries claim this %s; not attaching",
                mission,
                naif_id,
                len(owners),
                matched_on,
            )
        return None
    entry = owners[0]
    source = {"mission": mission, "naif_id": naif_id}
    if has_archive_trajectory(entry) or matched_on == "NAIF":
        entry["kernel_sources"].append(source)
        return entry
    # The probe had no kernel of any kind, so its stored NAIF indexes nothing.
    # The incoming one does, and `_collect_probes` walks kernels under the
    # first source's NAIF — so this source leads and the entry adopts its id.
    entry["kernel_sources"].insert(0, source)
    entry["naif_id"] = naif_id
    logger.info(
        "%s: adopted NAIF %d for %r, matched on COSPAR %s",
        mission,
        naif_id,
        entry.get("name"),
        cospar,
    )
    return entry


def record_from_entry(entry: dict) -> ProbeIdRecord:
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
    cospar: str | None = None,
) -> ProbeIdRecord:
    """Return a stable probe_id for `(mission, naif_id)`.

    Returns an existing entry verbatim if `kernel_sources` already has this
    pair — `probe_id`/`inception_mjd`/`dedupe` are frozen, so recomputed
    inception drift can't renumber existing probes.

    Otherwise allocates the lowest unused dedupe slot for the inception
    MJD. Caller must call save_registry() when `registry` is supplied; in
    stand-alone mode (registry=None) this loads + saves itself.
    """
    owned = registry is None
    if registry is None:
        registry = load_registry()
    if source_index is None:
        source_index = index_by_source(registry)

    existing = source_index.get((mission, naif_id))
    if existing is None and mission in SYNTHETIC_MISSIONS:
        existing = _attach_synthetic_source(registry, mission, naif_id, cospar)
        if existing is not None:
            source_index[(mission, naif_id)] = existing
            if owned:
                save_registry(registry)
    if existing is not None:
        return record_from_entry(existing)

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
    return record_from_entry(entry)


def load_qids() -> set[str]:
    """Return every non-null `wikidata_qid` in the probe registry."""
    return {qid for entry in load_registry() if (qid := entry.get("wikidata_qid"))}


def load_mission_qids() -> set[str]:
    """Return every mission `primary_qid` (the per-mission Wikidata QID)."""
    return {qid for entry in load_registry() if (qid := entry.get("primary_qid"))}


def assign_many(
    items: list[tuple[str, int, int]],
    cospars: dict[tuple[str, int], str | None] | None = None,
) -> dict[tuple[str, int], ProbeIdRecord]:
    """Bulk-assign probe IDs, loading & saving the registry once.

    `items` is `(mission, naif_id, inception_mjd)`. Deterministic over
    input order — when two unregistered items share an inception date,
    dedupe slots go in `items` order, so callers should pre-sort by
    `(inception_mjd, naif_id)` for stable output.

    `cospars` names each item's COSPAR where the mission index records one. A
    synthesised kernel uses it to find the probe it belongs to when that probe
    was registered under a NAIF of its own.
    """
    registry = load_registry()
    source_index = index_by_source(registry)
    out: dict[tuple[str, int], ProbeIdRecord] = {}
    for mission, naif_id, mjd in items:
        out[(mission, naif_id)] = assign(
            mission,
            naif_id,
            mjd,
            registry=registry,
            source_index=source_index,
            cospar=(cospars or {}).get((mission, naif_id)),
        )
    save_registry(registry)
    return out
