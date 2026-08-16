"""Every vocabulary value the Structure tab draws has a label to draw it with.

Nothing else catches a missing one: constants tests only check that a value
is in its own vocabulary, and the frontend can't know which are in use — a
gap surfaces only as a raw key like `shell_thickness_modelled` in the panel.

Only English is asserted: the other locales fall back to it, so a missing
translation still reads, while a missing key reads as nothing.
"""

from space_map_data.constants.atmosphere.structure import ATMOSPHERE_STRUCTURE
from space_map_data.constants.interior.bodies import INTERIOR_FACTS
from space_map_data.utils.paths import PROJECT_ROOT

MESSAGES = PROJECT_ROOT / "frontend" / "messages" / "en.json"


def _in_use() -> dict[str, set[str]]:
    """Values actually used, by message prefix — not the whole vocabulary; an
    unused role needs no label yet."""
    used: dict[str, set[str]] = {
        "interior_layer": set(),
        "interior_state": set(),
        "interior_note": set(),
        "material": set(),
        "species_name": set(),
        "atmosphere_layer": set(),
        "atmosphere_structure_note": set(),
        "atmosphere_datum": set(),
    }
    for body in INTERIOR_FACTS.values():
        for layer in body.layers:
            used["interior_layer"].add(layer.role)
            if layer.state:
                used["interior_state"].add(layer.state)
            if layer.note:
                used["interior_note"].add(layer.note)
            for component in layer.composition:
                used["material"].add(component.material)
            if layer.detail:
                # Normalized the way the frontend builds the key: formula
                # lowercased, "-" to "_" (Fe-Ni → species_name_fe_ni).
                for species, _ in layer.detail.entries:
                    used["species_name"].add(species.lower().replace("-", "_"))
    for body in ATMOSPHERE_STRUCTURE.values():
        used["atmosphere_datum"].add(body.datum)
        if body.note:
            used["atmosphere_structure_note"].add(body.note)
        for layer in body.layers:
            used["atmosphere_layer"].add(layer.role)
            if layer.note:
                used["atmosphere_structure_note"].add(layer.note)
    return used
