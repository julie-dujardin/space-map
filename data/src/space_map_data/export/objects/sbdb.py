"""SBDB (Small-Body Database) export helpers."""

from space_map_data.export.quantities import mass_quantity_from_kg
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
    "q",
    "ad",
    "prefix",
    "M1",
    "M2",
    "K1",
    "K2",
    "PC",
    "first_obs",
    "mass",
)


def build_sbdb(sbdb: SBDB) -> dict:
    """Build the SBDB extras dict, omitting None values."""
    data: dict = {}
    for attr in _SBDB_FIELDS:
        val = getattr(sbdb, attr)
        if val is not None:
            data[attr.rstrip("_")] = val
    if sbdb.mass_kg is not None:
        data["mass"] = mass_quantity_from_kg(sbdb.mass_kg)
    return data
