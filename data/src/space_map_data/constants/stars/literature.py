"""Star values read from papers, for stars that no catalogue here places.

An entry is keyed by an id of the star that stays the same between ingests:
its Gaia DR3 id, else its HIP number, else its HD number. Our own IDs can
change, so they are not keys. Each value cites one work of REFERENCES by its
key. The ingest gives the values to their column group as the source
`literature`, first in the order of that group. The star's object entry cites
the work beside the value.
"""

from typing import NamedTuple

# (catalogue, release, catalogue id), as in the cross-ids of the registry.
type StarKey = tuple[str, str, str]


class Reference(NamedTuple):
    # Authors and year, as the star page names the work.
    short: str
    title: str
    url: str


class Distance(NamedTuple):
    # pc.
    value: float
    lower: float
    upper: float
    # A value of `distance_method`.
    method: str
    reference: str


REFERENCES: dict[str, Reference] = {
    "smith_2006": Reference(
        "Smith 2006",
        "The Structure of the Homunculus. I. Shape and Latitude Dependence from"
        " H2 and [Fe II] Velocity Maps of η Carinae (ApJ 644, 1151)",
        "https://doi.org/10.1086/503766",
    ),
}

DISTANCES: dict[StarKey, Distance] = {
    # η Car. The H2 shape of the Homunculus and its age of 160 yr give
    # 2350 ± 50 pc (Sect. 4.1).
    ("gaia", "dr3", "5350358584482202880"): Distance(
        2350, 2300, 2400, "expansion", "smith_2006"
    ),
}
