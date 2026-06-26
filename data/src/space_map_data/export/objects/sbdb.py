"""SBDB (Small-Body Database) export helpers."""

from space_map_data.export.quantities import UnitConverter
from space_map_data.export.small_body_color import resolve_small_body_color
from space_map_data.models.object import SBDB


_SBDB_FIELDS = (
    "neo",
    "pha",
    "class_",
    "sats",
    "diameter",
    "extent",
    "albedo",
    "rot_per",
    "GM",
    "H",
    "G",
    "spec_B",
    "spec_T",
    "BV",
    "UB",
    "IR",
    "moid",
    "moid_jup",
    "t_jup",
    "per_y",
    "ad",
    "prefix",
    "M1",
    "M2",
    "K1",
    "K2",
    "PC",
    "first_obs",
    "last_obs",
    "data_arc",
    "n_obs_used",
    "mass_kg",
    "condition_code",
)


def build_sbdb(sbdb: SBDB, units: UnitConverter) -> dict:
    """Build the SBDB extras dict, omitting None values.

    The orbit class is emitted as the enum *name* (e.g. ``"MBA"``) — that's
    also the export zone id the bodies of this class go into, and is
    locale-stable. The frontend resolves the human label via
    ``m.orbit_class_<name>``.
    """
    data: dict = {}
    for attr in _SBDB_FIELDS:
        val = getattr(sbdb, attr)
        if val is None:
            continue
        if attr == "class_":
            data["class"] = val.name
        else:
            data[attr.rstrip("_")] = val
    if sbdb.mass_kg is not None:
        converted = units.best_unit(sbdb.mass_kg, "mass")
        if converted is not None:
            data["mass"] = converted
    color, method = resolve_small_body_color(
        sbdb.spkid, sbdb.spec_B or sbdb.spec_T, sbdb.albedo
    )
    if color is not None:
        data["color"] = color
        data["color_method"] = method
    return data
