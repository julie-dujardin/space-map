"""Continent enum for the origin of an IAU feature name's etymology.

Values come from the IAU planetary-nomenclature KML ``continent`` field, which
ships only these seven labels (plus blanks for entries with no continent).
"""

from enum import StrEnum


class Continent(StrEnum):
    AFRICA = "Africa"
    ANTARCTICA = "Antarctica"
    ASIA = "Asia"
    EUROPE = "Europe"
    NORTH_AMERICA = "North America"
    OCEANIA = "Oceania"
    SOUTH_AND_CENTRAL_AMERICA = "South and Central America"
