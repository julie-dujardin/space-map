"""Citable literature behind the synthetic ring profiles, for the /credits page.

Same shape as constants/atmosphere/references.py: one entry per work we take
numbers from, with a one-line "what we get"; the full per-value provenance
lives as comments next to each constant in catalog.py.

Deliberately *not* a copy of the data-source list. The PDS ring tables and
NSSDCA fact sheets the numbers are read off are credited per body through each
bundle's own ``sources``, so repeating them here would double every row. What
belongs here is the literature standing behind those tables, which no per-body
row names — and it stays on /credits rather than the in-scene attribution UI,
which would become unusable listing individual papers.
"""

from typing import NamedTuple


class RingReference(NamedTuple):
    title: str
    url: str
    contribution: str


RING_REFERENCES: tuple[RingReference, ...] = (
    # The PDS Jupiter, Uranus and Neptune tables each attribute their values to
    # a chapter of this one book, so it is a single citation rather than three.
    RingReference(
        "Tiscareno & Murray (eds) 2018, Planetary Ring Systems "
        "(Cambridge University Press)",
        "https://doi.org/10.1017/9781316286791",
        "Ring boundaries, radii, widths and normal optical depths for Jupiter "
        "and Neptune (De Pater et al.) and for Uranus (Nicholson et al.), as "
        "tabulated by the PDS Ring-Moon Systems Node",
    ),
    RingReference(
        "de Pater et al. 2006 (Science 312)",
        "https://doi.org/10.1126/science.1125110",
        "Colours of the outer Uranian dust rings (ν red, µ blue)",
    ),
    # The small-body systems. Each body's own discovery and refinement papers
    # are credited per bundle; these two are the works standing behind the
    # numbers that no single body's row names.
    RingReference(
        "Sicardy et al. 2024 (Astronomy & Astrophysics Review 32)",
        "https://doi.org/10.1007/s00159-024-00156-x",
        "Consolidated ring radii, widths, optical depths and poles for "
        "Chariklo, Haumea and Quaoar, and the state of the evidence for "
        "Chiron",
    ),
    RingReference(
        "Sicardy et al. 2019 (Nature Astronomy 3)",
        "https://doi.org/10.1038/s41550-018-0616-8",
        "The spin-orbit resonances that place small-body rings, and why an "
        "elongated body clears its own synchronous orbit",
    ),
)
