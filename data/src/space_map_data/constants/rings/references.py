"""Citable sources behind the synthetic ring profiles, for the /credits page.

Same shape as constants/atmosphere/references.py: one entry per work we take
numbers from, full per-value provenance as comments next to each constant.
Not yet exported — wiring into credits.json comes with full ring integration.
"""

from typing import NamedTuple


class RingReference(NamedTuple):
    title: str
    url: str
    contribution: str


RING_REFERENCES: tuple[RingReference, ...] = (
    RingReference(
        "PDS Ring-Moon Systems Node — Jupiter ring table",
        "https://pds-rings.seti.org/jupiter/jupiter_rings_table.html",
        "Jovian ring boundaries + optical depths (De Pater et al. 2018 values)",
    ),
    RingReference(
        "PDS Ring-Moon Systems Node — Uranus ring table",
        "https://pds-rings.seti.org/uranus/uranus_rings_table.html",
        "Uranian ring mid-radii, widths + optical depths "
        "(Nicholson et al. 2018 values)",
    ),
    RingReference(
        "PDS Ring-Moon Systems Node — Neptune ring table",
        "https://pds-rings.seti.org/neptune/neptune_rings_table.html",
        "Neptunian ring mid-radii, widths + optical depths",
    ),
    RingReference(
        "NSSDCA Jupiter Rings Fact Sheet",
        "https://nssdc.gsfc.nasa.gov/planetary/factsheet/jupringfact.html",
        "Cross-check boundaries; main-ring τ + particle albedo",
    ),
    RingReference(
        "NSSDCA Uranus Rings Fact Sheet",
        "https://nssdc.gsfc.nasa.gov/planetary/factsheet/uranringfact.html",
        "Cross-check radii; eccentric-ring width ranges + particle albedos",
    ),
    RingReference(
        "NSSDCA Neptunian Rings Fact Sheet",
        "https://nssdc.gsfc.nasa.gov/planetary/factsheet/nepringfact.html",
        "Cross-check radii + optical depths",
    ),
    RingReference(
        "de Pater et al. 2006 (Science 312)",
        "https://doi.org/10.1126/science.1125110",
        "Colors of the outer Uranian dust rings (ν red, µ blue)",
    ),
)
