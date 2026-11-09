"""Johnston's Archive blocks for the object panel.

Two shapes, because the archive has two: a per-system block on the parent
(whole-system mass and density, Hill radius, the primary's shape and spin)
and a per-companion block on the moon (its mutual orbit as published, its
size, and who found it how).

The companion's ``i``/``om``/``w`` are deliberately not exported: the archive
reprints each paper's angles without stating a frame, so they cannot be drawn
or compared against the ecliptic values every other source is normalised to.
"""

from sqlalchemy.orm import Session

from space_map_data.export.objects.pick import pick_attrs
from space_map_data.export.quantities import UnitConverter
from space_map_data.models.object import JohnstonMoon, JohnstonSystem

_SYSTEM_FIELDS = (
    "confidence",
    "dynamical_type",
    "h_mag",
    "slope_g",
    "diameter_km",
    "diameter_km_sigma",
    "albedo",
    "albedo_sigma",
    "taxonomy",
    "density_g_cm3",
    "density_g_cm3_sigma",
    "hill_radius_km",
    "colour_ub",
    "colour_bv",
    "colour_vr",
    "colour_vi",
    "primary_diameter_km",
    "primary_diameter_km_sigma",
    "primary_dimensions",
    "primary_axial_ratios",
    "primary_rotation_h",
    "primary_rotation_h_sigma",
    "primary_amplitude_mag",
    # Pole direction is held but not shipped: the archive labels the pair
    # "Β, λ" and prints them in an order that disagrees with itself between
    # systems (Didymos reads 310°, -84°), and the map already takes poles from
    # the PCK and DAMIT, which state their frame.
    "last_updated",
)

_MOON_FIELDS = (
    "label",
    "binary_type",
    "a_km",
    "a_km_sigma",
    "a_over_primary_radius",
    "a_over_hill_radius",
    "per_d",
    "per_d_sigma",
    "e",
    "e_sigma",
    "epoch",
    "normalised_ang_mom",
    "diameter_km",
    "diameter_km_sigma",
    "diameter_ratio",
    "diameter_ratio_sigma",
    "dimensions",
    "mag_difference",
    "rotation_h",
    "discovery_date",
    "discoverers",
    "discovery_method",
    "discovery_facility",
    "announced",
    "provisional_designation",
)


def _page_url(page: str) -> str:
    return f"https://www.johnstonsarchive.net/astro/astmoons/{page}.html"


def load_johnston_systems(session: Session, units: UnitConverter) -> dict[str, dict]:
    """Map parent Object.id -> the system block."""
    out: dict[str, dict] = {}
    for row in session.query(JohnstonSystem).all():
        block = pick_attrs(row, _SYSTEM_FIELDS)
        block["page"] = _page_url(row.page)
        if row.mass_kg is not None:
            mass = units.best_unit(row.mass_kg, "mass")
            if mass is not None:
                block["mass"] = mass
                if row.mass_kg_nominal:
                    block["mass_nominal"] = True
        out[row.object_id] = block
    return out


def load_johnston_moons(session: Session) -> dict[str, dict]:
    """Map moon Object.id -> the companion block.

    Carries its system's page so a moon's panel cites the entry its numbers
    were read off, not the archive's index.
    """
    out: dict[str, dict] = {}
    for row, page in session.query(JohnstonMoon, JohnstonSystem.page).join(
        JohnstonSystem, JohnstonSystem.object_id == JohnstonMoon.parent_object_id
    ):
        out[row.object_id] = pick_attrs(row, _MOON_FIELDS) | {"page": _page_url(page)}
    return out
