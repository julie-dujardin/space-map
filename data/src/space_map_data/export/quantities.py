"""Quantity conversion helpers for export."""

import math

# Unit ladder for mass: (resolved_unit_name, factor_in_kg), largest first
_MASS_UNITS: tuple[tuple[str, float], ...] = (
    ("solar_mass", 1.988416e30),
    ("jupiter_mass", 1.89813e27),
    # ("earth_mass", 5.9722e24),
    ("ronnagram", 1e24),
    ("yottagram", 1e21),
    ("zettagram", 1e18),
    ("exagram", 1e15),
    ("petagram", 1e12),
    ("teragram", 1e9),
    ("tonne", 1e3),
    ("kilogram", 1.0),
)

# kg factor per resolved unit name — used to normalise incoming quantities.
MASS_UNIT_KG: dict[str, float] = {name: kg for name, kg in _MASS_UNITS}


def _round_sigfigs(x: float, sig: int) -> float:
    """Round x to sig significant figures."""
    if x == 0:
        return 0.0
    magnitude = math.floor(math.log10(abs(x)))
    factor = 10 ** (sig - 1 - magnitude)
    return round(x * factor) / factor


def mass_quantity_from_kg(mass_kg: float) -> dict:
    """Convert a mass in kg to a human-readable {value, unit} dict."""
    for unit_name, unit_kg in _MASS_UNITS:
        value = mass_kg / unit_kg
        if value > 1.1:
            return {"value": _round_sigfigs(value, 4), "unit": unit_name}
    return {"value": _round_sigfigs(mass_kg, 4), "unit": "kilogram"}
