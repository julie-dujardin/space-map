"""AsterSat (NSDB) mutual-orbit provenance for the object panel.

The elements themselves ship in the position zone; what's carried here is how
much the fit is worth — how many observations went into it, over what arc,
and what the residuals came to — plus the system mass and component radii
AsterSat prints alongside.
"""

from sqlalchemy.orm import Session

from space_map_data.export.objects.pick import pick_attrs
from space_map_data.export.quantities import UnitConverter
from space_map_data.ingest.providers.objects.sbdb import G_KM3_PER_KG_S2
from space_map_data.models.object import AsterSatMoon

_FIELDS = ("frame", "n_obs", "rms_arcsec", "primary_radius_km")


def load_astersat(session: Session, units: UnitConverter) -> dict[str, dict]:
    """Map moon Object.id -> the panel block, for every fitted mutual orbit."""
    out: dict[str, dict] = {}
    for moon in session.query(AsterSatMoon).all():
        block = pick_attrs(moon, _FIELDS)
        if moon.obs_arc_start is not None and moon.obs_arc_end is not None:
            block["obs_arc"] = [moon.obs_arc_start, moon.obs_arc_end]
        # The panel wants a mass, not a gravitational parameter; GM stays in
        # the DB for anyone who needs the published figure.
        if moon.gm is not None:
            mass = units.best_unit(moon.gm / G_KM3_PER_KG_S2, "mass")
            if mass is not None:
                block["system_mass"] = mass
        if moon.satellite_radius_km is not None:
            block["radius_km"] = moon.satellite_radius_km
        out[moon.object_id] = block
    return out
