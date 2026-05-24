"""Helpers: object_id resolution + tier-source selection + source hashing."""

import hashlib
import logging
from pathlib import Path

from space_map_data.constants.providers import ID_TYPES, make_object_id
from space_map_data.ingest.providers.models import config

log = logging.getLogger(__name__)


def resolve_mission_object_id(mission: dict) -> str | None:
    """Map one mission descriptor to its canonical object_id.

    Priority: ``probe_id`` > ``naif_id`` > ``norad_cat_id``. Returns None
    (and logs) when nothing resolves, so the caller can skip that mission.
    """
    probe_id = mission.get("probe_id")
    if probe_id is not None:
        return make_object_id(ID_TYPES.PROBE, probe_id)
    naif = mission.get("naif_id")
    if naif is not None:
        return make_object_id(ID_TYPES.NAIF, naif)
    norad = mission.get("norad_cat_id")
    if norad is not None:
        return make_object_id(ID_TYPES.NORAD_SATCAT, norad)
    return None


def pick_tier_sources(files: list[dict]) -> tuple[dict | None, dict | None]:
    """Pick (high_source, low_source_or_None) from a manifest entry's ``files:`` list.

    Filters out unsupported formats. Sorts convertible files by source-format
    priority then by size; largest = high. A second source is treated as a
    hand-authored low tier only when it's at most ``LOW_TIER_AUTHORED_MAX_RATIO``
    of the high tier's size — otherwise it's likely a variant (different
    resolution authored independently) and ``low`` is synthesised from ``high``
    downstream.
    """
    candidates = [m for m in files if m.get("type") in config.CONVERTIBLE_FORMATS]
    if not candidates:
        return None, None

    def rank(m: dict) -> tuple[int, int]:
        fmt_rank = config.FORMAT_PRIORITY.index(m["type"])
        return (fmt_rank, -int(m.get("size") or 0))

    candidates.sort(key=rank)
    high = candidates[0]

    if len(candidates) == 1:
        return high, None

    smallest = min(candidates[1:], key=lambda m: int(m.get("size") or 0))
    high_size = int(high.get("size") or 0)
    small_size = int(smallest.get("size") or 0)
    if high_size > 0 and small_size <= high_size * config.LOW_TIER_AUTHORED_MAX_RATIO:
        return high, smallest
    return high, None


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()
