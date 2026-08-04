"""Every vocabulary value the Structure tab draws has a label to draw it with.

The pipeline ships keys and the frontend ships the sentences, which means a new
layer role or note added here shows up in the panel as a raw `shell_thickness_
modelled` until somebody writes twelve translations for it. Nothing else catches
that: the constants tests only check the value is in its own vocabulary, and the
frontend has no way to know which values are actually in use.

Only English is asserted. The other eleven locales fall back to it rather than
to the key, so a missing translation degrades to readable English; a missing key
degrades to nothing at all.
"""

import json

import pytest

from space_map_data.constants.atmosphere.structure import ATMOSPHERE_STRUCTURE
from space_map_data.constants.interior.bodies import INTERIOR_FACTS
from space_map_data.utils.paths import PROJECT_ROOT

MESSAGES = PROJECT_ROOT / "frontend" / "messages" / "en.json"


def _in_use() -> dict[str, set[str]]:
    """Every value any body actually carries, by the message prefix that names
    it. Not the whole vocabulary — an unused role needs no label yet."""
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


@pytest.mark.skipif(not MESSAGES.exists(), reason="frontend not checked out")
def test_every_value_in_use_has_a_label():
    messages = json.loads(MESSAGES.read_text(encoding="utf-8"))
    missing = [
        f"{prefix}_{value}"
        for prefix, values in _in_use().items()
        for value in sorted(values)
        if f"{prefix}_{value}" not in messages
    ]
    assert not missing, f"no English label for: {', '.join(missing)}"
