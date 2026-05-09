"""Shared test factories for constructing model instances without a database."""

from typing import Any

from space_map_data.models.object import (
    ElementsScale,
    Horizons,
    Object,
    ObjectType,
    OrbitalSource,
)

# Kepler-element kwargs the factory accepts as a convenience and routes to the
# correct sub-table relation (or to the celestrak transient overlay attribute).
_KEPLER_KEYS = ("epoch_jd", "a", "e", "i", "om", "w", "ma", "n", "om_dot", "w_dot")

_KEPLER_DEFAULTS: dict[str, Any] = {
    "epoch_jd": 2451545.0,
    "a": 1.0,
    "e": 0.0167,
    "i": 0.0,
    "om": 0.0,
    "w": 0.0,
    "ma": 0.0,
    "n": 0.9856,
    "om_dot": None,
    "w_dot": None,
}


def make_object(**overrides) -> Object:
    """Create an Object with the right sub-table populated for kepler reads.

    Kepler kwargs (epoch_jd, a, e, i, om, w, ma, n, om_dot, w_dot) are popped
    off and routed to:
    * Horizons sub-table for horizons / spice / None sources (the default
      fallback the writer uses when ``Object.orbital_source`` doesn't pin a
      sub-table)
    * a transient ``_daily_kepler`` dict for celestrak source — celestrak rows
      don't persist kepler elements, the daily overlay supplies them
    SBDB-source tests should set ``obj.sbdb`` themselves with element values
    on the SBDB row directly (its column names already match the unified set).
    """
    kepler = {k: overrides.pop(k) for k in list(overrides) if k in _KEPLER_KEYS}
    daily_kepler = overrides.pop("daily_kepler", None)

    defaults = {
        "id": "naif-399",
        "name": "Earth",
        "object_type": ObjectType.planet,
        "scale": ElementsScale.system,
        "parent_naif_id": 0,
        "orbital_source": OrbitalSource.horizons,
    }
    defaults.update(overrides)
    obj = Object(**defaults)

    merged = {**_KEPLER_DEFAULTS, **kepler}
    src = obj.orbital_source

    if src == OrbitalSource.celestrak:
        if daily_kepler is None:
            daily_kepler = {
                "epoch_jd": merged["epoch_jd"],
                "a": merged["a"],
                "e": merged["e"],
                "i": merged["i"],
                "om": merged["om"],
                "w": merged["w"],
                "ma": merged["ma"],
                "n": merged["n"],
                "BSTAR": None,
                "MEAN_MOTION_DOT": None,
                "MEAN_MOTION_DDOT": None,
                "ELEMENT_SET_NO": None,
                "REV_AT_EPOCH": None,
            }
        obj._daily_kepler = daily_kepler  # type: ignore[attr-defined]
    elif src != OrbitalSource.sbdb:
        # horizons / spice / None — populate Horizons sub-table.
        obj.horizons = Horizons(
            naif_id=obj.naif_id,
            object_id=obj.id,
            JDTDB=merged["epoch_jd"],
            A=merged["a"],
            EC=merged["e"],
            IN_=merged["i"],
            OM=merged["om"],
            W=merged["w"],
            MA=merged["ma"],
            N=merged["n"],
            om_dot=merged["om_dot"],
            w_dot=merged["w_dot"],
        )
    return obj
