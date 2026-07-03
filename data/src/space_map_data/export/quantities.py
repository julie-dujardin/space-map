"""Quantity conversion helpers for export.

Builds unit ladders from Wikidata P2370 (conversion factor) and P31 (instance of)
claims on preloaded unit entities, replacing hardcoded conversion tables.
"""

import logging
from typing import NamedTuple

from space_map_data.export.wikidata import WikidataEntityCache

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# P31 QID → quantity type name
# ---------------------------------------------------------------------------
_QUANTITY_TYPE_QIDS: dict[str, str] = {
    "Q3647172": "mass",
    "Q1978718": "length",
    "Q10387685": "density",
    "Q55433947": "density",
    "Q15222637": "speed",
    "Q39699875": "acceleration",
    "Q1790144": "time",
    "Q1371562": "area",
    "Q1302471": "volume",
    "Q10387689": "power",
    "Q13587321": "angle",
    "Q27084": "ratio",
    "Q4173969": "pressure",
    "Q21162604": "frequency",
}

# P31 types that mark a unit as belonging to an accepted system
_ACCEPTED_SYSTEM_P31: set[str] = {
    "Q208469",  # SI derived unit
    "Q69197847",  # coherent SI unit
    "Q223662",  # SI base unit
    "Q82047057",  # UCUM derived unit
    "Q68618328",  # SI unit with special name
    "Q61610698",  # SI unit
    "Q82047053",  # UCUM base unit
    "Q106839753",  # SI-accepted non-SI unit
    "Q3268848",  # non-SI unit accepted with the SI
    "Q12036470",  # decimal multiple of a unit
    "Q110762942",  # decimal multiple of a unit (variant)
}

# Non-SI units explicitly allowed (astronomical units essential for display)
_ASTRONOMICAL_ALLOWLIST: set[str] = {
    "Q180892",  # solar mass
    "Q651336",  # Jupiter mass
    "Q681996",  # Earth mass
    "Q48440",  # solar radius
    "Q3421309",  # Jupiter radius
    "Q4243638",  # cubic kilometre
    "Q3674704",  # kilometre per second
}

# Units explicitly excluded (imperial/US customary that slip in via UCUM derived)
_UNIT_DENYLIST: set[str] = {
    "Q218593",  # inch
    "Q232291",  # square mile
    "Q469356",  # short ton
    "Q626299",  # pound per square inch
    "Q130964",  # small calorie
}

# Labels for base units that may not be in the downloaded unit files
_BASE_UNIT_LABELS: dict[str, str] = {
    "Q11573": "metre",
    "Q199": "1",  # dimensionless base for ratio
    "Q25236": "watt",
    "Q33680": "radian",
    "Q44395": "pascal",
}

# Temperature can't join the multiplicative P2370 ladders (K↔°C is an offset,
# not a scale), so it's normalized separately to a canonical kelvin. Values:
# (scale, offset) with kelvin = value * scale + offset.
_TEMPERATURE_TO_KELVIN: dict[str, tuple[float, float]] = {
    "Q11579": (1.0, 0.0),  # kelvin
    "Q25267": (1.0, 273.15),  # degree Celsius
    "Q42289": (5.0 / 9.0, 273.15 - 32.0 * 5.0 / 9.0),  # degree Fahrenheit
}


class UnitEntry(NamedTuple):
    label: str  # normalized English label, e.g. "solar_mass"
    qid: str  # e.g. "Q180892"
    factor: float  # conversion factor to the SI base unit for this type


class UnitConverter:
    """Data-driven unit conversion built from Wikidata P2370/P31 claims."""

    def __init__(self, cache: WikidataEntityCache) -> None:
        ladders: dict[str, list[UnitEntry]] = {}
        qid_index: dict[str, tuple[str, float]] = {}
        base_units: dict[str, set[str]] = {}

        for qid, entity in cache.unit_items().items():
            claims = entity["claims"]

            p31_ids = self._p31_qids(claims)
            qty_types = {
                _QUANTITY_TYPE_QIDS[t] for t in p31_ids if t in _QUANTITY_TYPE_QIDS
            }
            if not qty_types:
                continue

            if qid in _UNIT_DENYLIST:
                continue
            in_accepted = bool(p31_ids & _ACCEPTED_SYSTEM_P31)
            if not in_accepted and qid not in _ASTRONOMICAL_ALLOWLIST:
                continue

            conv = self._extract_p2370(claims)
            if conv is None:
                continue
            factor, base_qid = conv

            for qty_type in qty_types:
                base_units.setdefault(qty_type, set()).add(base_qid)

            label_raw = entity["labels"].get("en")
            if not label_raw:
                continue
            label = label_raw.lower().replace(" ", "_")

            entry = UnitEntry(label=label, qid=qid, factor=factor)
            for qty_type in qty_types:
                ladders.setdefault(qty_type, []).append(entry)
                qid_index[qid] = (qty_type, factor)

        # Add synthetic entries for base units not present in the unit files.
        for qty_type, base_qids in base_units.items():
            for base_qid in base_qids:
                if base_qid not in qid_index:
                    label = _BASE_UNIT_LABELS.get(base_qid, base_qid)
                    entry = UnitEntry(label=label, qid=base_qid, factor=1.0)
                    ladders.setdefault(qty_type, []).append(entry)
                    qid_index[base_qid] = (qty_type, 1.0)

        for entries in ladders.values():
            entries.sort(key=lambda e: e.factor, reverse=True)

        self._ladders = ladders
        self._qid_index = qid_index
        self.used_units: set[str] = set()

        logger.info(
            "Built unit ladders: %s",
            ", ".join(f"{t}={len(es)}" for t, es in sorted(ladders.items())),
        )

    def convert(self, value: float, unit_qid: str) -> dict | None:
        """Convert a quantity to its best display unit.

        Returns {"value": float, "unit": str} or None if the unit QID is unknown.
        """
        info = self._qid_index.get(unit_qid)
        if info is None:
            return None
        qty_type, factor = info
        return self.best_unit(value * factor, qty_type)

    def convert_temperature(self, value: float, unit_qid: str) -> dict | None:
        """Normalize a temperature to canonical kelvin, or None if unit unknown.

        Kept off the P2370 ladders because temperature conversions are affine
        (offset), not multiplicative. Emitting a single canonical unit lets the
        frontend display every body's temperature in one scale regardless of
        the source unit.
        """
        conv = _TEMPERATURE_TO_KELVIN.get(unit_qid)
        if conv is None:
            return None
        scale, offset = conv
        self.used_units.add("kelvin")
        return {
            "value": self._strip_trailing_zeros(value * scale + offset),
            "unit": "kelvin",
        }

    def convert_to_base(
        self,
        value: float,
        unit_qid: str,
        expected_type: str | None = None,
    ) -> float | None:
        """Convert a value to its SI base unit. Returns None if QID unknown or type mismatch."""
        info = self._qid_index.get(unit_qid)
        if info is None:
            return None
        qty_type, factor = info
        if expected_type and qty_type != expected_type:
            return None
        return value * factor

    def best_unit(self, value_in_base: float, qty_type: str) -> dict | None:
        """Pick the best display unit for a value already in base units."""
        ladder = self._ladders.get(qty_type)
        if not ladder:
            return None
        strip = self._strip_trailing_zeros
        for entry in ladder:
            value = value_in_base / entry.factor
            if abs(value) > 1.1:
                self.used_units.add(entry.label)
                return {"value": strip(value), "unit": entry.label}
        # Fallback: use the smallest unit in the ladder
        last = ladder[-1]
        self.used_units.add(last.label)
        return {
            "value": strip(value_in_base / last.factor),
            "unit": last.label,
        }

    @staticmethod
    def _strip_trailing_zeros(x: float) -> float:
        """Drop unnecessary trailing zeros from *x*."""
        return float(f"{x:g}")

    @staticmethod
    def _p31_qids(claims: dict) -> set[str]:
        """Extract all entity QIDs from P31 (instance of) claims."""
        result: set[str] = set()
        for stmt in claims.get("P31", []):
            if stmt.get("rank") == "deprecated":
                continue
            val = stmt.get("mainsnak", {}).get("datavalue", {}).get("value")
            if isinstance(val, dict) and "id" in val:
                result.add(val["id"])
        return result

    @staticmethod
    def _extract_p2370(claims: dict) -> tuple[float, str] | None:
        """Extract P2370 conversion factor as (amount_float, base_unit_qid)."""
        for stmt in claims.get("P2370", []):
            if stmt.get("rank") == "deprecated":
                continue
            val = stmt.get("mainsnak", {}).get("datavalue", {}).get("value")
            if not isinstance(val, dict) or "amount" not in val:
                continue
            try:
                amount = float(val["amount"])
            except (ValueError, TypeError):
                continue
            unit_uri = val.get("unit", "1")
            if unit_uri == "1":
                continue
            base_qid = unit_uri.rsplit("/", 1)[-1] if "/" in unit_uri else unit_uri
            return amount, base_qid
        return None
