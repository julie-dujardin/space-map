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
coverage interval at first ingest. Cached to a JSON file under `DOWNLOAD_DIR`
since the DB is rebuilt regularly — the cache pins each (mission, naif_id) to
a `probe_id` so the value is stable across re-ingests even if new kernels add
earlier coverage later.
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

CACHE_PATH = DOWNLOAD_DIR / "spice" / "probe_ids.json"

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


def _load_cache() -> dict[str, dict]:
    """Read the on-disk cache. Returns {} if missing or unreadable."""
    if not CACHE_PATH.exists():
        return {}
    try:
        return json.loads(CACHE_PATH.read_text())
    except (OSError, json.JSONDecodeError) as exc:
        logger.warning(
            "probe_id cache at %s unreadable (%s); rebuilding", CACHE_PATH, exc
        )
        return {}


def _save_cache(cache: dict[str, dict]) -> None:
    CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
    CACHE_PATH.write_text(json.dumps(cache, indent=2, sort_keys=True))


def _cache_key(mission: str, naif_id: int) -> str:
    return f"{mission}/{naif_id}"


def assign(
    mission: str,
    naif_id: int,
    inception_mjd: int,
    cache: dict[str, dict] | None = None,
) -> ProbeIdRecord:
    """Return a stable probe_id for `(mission, naif_id)`.

    First call for a key allocates a dedupe slot (the lowest unused integer for
    the inception date, deterministic across runs) and caches the result. Later
    calls return the cached value even if `inception_mjd` shifts — the cached
    inception MJD wins, so adding earlier-coverage kernels later doesn't
    renumber existing probes.
    """
    owned = cache is None
    if cache is None:
        cache = _load_cache()
    key = _cache_key(mission, naif_id)
    if key in cache:
        rec = cache[key]
        return ProbeIdRecord(
            mission=mission,
            naif_id=naif_id,
            inception_mjd=int(rec["inception_mjd"]),
            dedupe=int(rec["dedupe"]),
        )

    used = {
        int(r["dedupe"])
        for r in cache.values()
        if int(r["inception_mjd"]) == inception_mjd
    }
    dedupe = next(i for i in range(MAX_DEDUPE + 1) if i not in used)
    record = ProbeIdRecord(mission, naif_id, inception_mjd, dedupe)
    cache[key] = {
        "mission": mission,
        "naif_id": naif_id,
        "inception_mjd": inception_mjd,
        "dedupe": dedupe,
        "probe_id": record.probe_id,
    }
    if owned:
        _save_cache(cache)
    return record


def assign_many(
    items: list[tuple[str, int, int]],
) -> dict[tuple[str, int], ProbeIdRecord]:
    """Bulk-assign probe IDs. Loads & saves the cache once.

    `items` is a list of `(mission, naif_id, inception_mjd)`. Deterministic
    over input order — when two items share an inception date and neither is
    in the cache yet, dedupe slots are assigned in the order they appear in
    `items`. Callers should pre-sort by `(inception_mjd, naif_id)` for stable
    output across runs.
    """
    cache = _load_cache()
    out: dict[tuple[str, int], ProbeIdRecord] = {}
    for mission, naif_id, mjd in items:
        out[(mission, naif_id)] = assign(mission, naif_id, mjd, cache=cache)
    _save_cache(cache)
    return out
