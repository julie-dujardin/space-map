"""Hand-edited per-spacecraft pointing config.

A YAML file maps full object IDs (``probe-22904832``, ``norad_satcat-25544``,
...) to a two-vector attitude spec the frontend applies to the focused model:
a ``primary`` body axis is aimed exactly at a target direction, an optional
``secondary`` axis is aimed as close as possible at a second target. Absent
file or unmatched ids degrade silently to the south-toward-parent default.
"""

import logging
from pathlib import Path
from typing import Any

import yaml

from space_map_data.utils.paths import SOURCES_POSITION_DIR

logger = logging.getLogger(__name__)

CONFIG_PATH = SOURCES_POSITION_DIR / "spacecraft-orientation.yaml"

_AXES = {"+x", "-x", "+y", "-y", "+z", "-z"}
_TARGETS = {"parent", "sun", "velocity"}


def _normalize_constraint(value: Any, object_id: str, slot: str) -> dict | None:
    """Validate one ``{axis, target}`` pair; log and drop it if malformed."""
    if not isinstance(value, dict):
        logger.warning(
            "spacecraft-orientation: %s %s is not a mapping; dropping", object_id, slot
        )
        return None
    axis, target = value.get("axis"), value.get("target")
    if axis not in _AXES:
        logger.warning(
            "spacecraft-orientation: %s %s has invalid axis %r (want one of %s); dropping",
            object_id,
            slot,
            axis,
            sorted(_AXES),
        )
        return None
    if target not in _TARGETS:
        logger.warning(
            "spacecraft-orientation: %s %s has invalid target %r (want one of %s); dropping",
            object_id,
            slot,
            target,
            sorted(_TARGETS),
        )
        return None
    return {"axis": axis, "target": target}


def load_orientation_config(path: Path = CONFIG_PATH) -> dict[str, dict]:
    """Parse the YAML into ``{object_id: {"primary": ..., "secondary"?: ...}}``.

    Returns ``{}`` when the file is absent or unreadable; logs every dropped
    entry so silently-broken config is visible.
    """
    if not path.exists():
        logger.info(
            "spacecraft-orientation: no config at %s; using attitude defaults", path
        )
        return {}
    try:
        raw = yaml.safe_load(path.read_text())
    except (OSError, yaml.YAMLError):
        logger.exception("spacecraft-orientation: failed to read %s; ignoring", path)
        return {}
    if not isinstance(raw, dict):
        logger.warning(
            "spacecraft-orientation: top level of %s is not a mapping; ignoring", path
        )
        return {}

    specs: dict[str, dict] = {}
    for object_id, entry in raw.items():
        object_id = str(object_id)
        if not isinstance(entry, dict):
            logger.warning(
                "spacecraft-orientation: %s entry is not a mapping; skipping", object_id
            )
            continue
        primary = _normalize_constraint(entry.get("primary"), object_id, "primary")
        if primary is None:
            logger.warning(
                "spacecraft-orientation: %s has no valid primary; skipping", object_id
            )
            continue
        spec: dict = {"primary": primary}
        if "secondary" in entry:
            secondary = _normalize_constraint(
                entry.get("secondary"), object_id, "secondary"
            )
            if secondary is not None:
                spec["secondary"] = secondary
        specs[object_id] = spec
    return specs


def apply_orientation_config(
    global_data: dict[str, dict], config: dict[str, dict] | None = None
) -> int:
    """Inject ``pointing`` into each matching object's global entry.

    Logs every configured id that has no exported object. Returns the count
    actually applied.
    """
    if config is None:
        config = load_orientation_config()
    applied = 0
    for object_id, spec in config.items():
        entry = global_data.get(object_id)
        if entry is None:
            logger.warning(
                "spacecraft-orientation: no exported object %s; pointing spec ignored",
                object_id,
            )
            continue
        entry["pointing"] = spec
        applied += 1
    if config:
        logger.info(
            "spacecraft-orientation: applied pointing to %d/%d configured objects",
            applied,
            len(config),
        )
    return applied
