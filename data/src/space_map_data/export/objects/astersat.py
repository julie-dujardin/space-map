"""AsterSat (NSDB) mutual-orbit provenance for the object panel.

The elements themselves ship in the position zone; what's carried here is how
much the fit is worth — how many observations went into it, over what arc,
and what the residuals came to — plus the system mass and component radii
AsterSat prints alongside.
"""

from sqlalchemy.orm import Session

from space_map_data.export.quantities import UnitConverter
from space_map_data.models.object import AsterSatMoon

# Newtonian G, for turning the published GM into a system mass.
_G = 6.674_30e-20  # km^3 kg^-1 s^-2


def load_astersat(session: Session, units: UnitConverter) -> dict[str, dict]:
    """Map moon Object.id -> the panel block, for every fitted mutual orbit."""
    out: dict[str, dict] = {}
    for moon in session.query(AsterSatMoon).all():
        block: dict = {"frame": moon.frame}
        if moon.n_obs is not None:
            block["n_obs"] = moon.n_obs
        if moon.rms_arcsec is not None:
            block["rms_arcsec"] = moon.rms_arcsec
        if moon.obs_arc_start is not None and moon.obs_arc_end is not None:
            block["obs_arc"] = [moon.obs_arc_start, moon.obs_arc_end]
        if moon.gm is not None:
            block["gm"] = moon.gm
            mass = units.best_unit(moon.gm / _G, "mass")
            if mass is not None:
                block["system_mass"] = mass
        if moon.primary_radius_km is not None:
            block["primary_radius_km"] = moon.primary_radius_km
        if moon.satellite_radius_km is not None:
            block["radius_km"] = moon.satellite_radius_km
        out[moon.object_id] = block
    return out
