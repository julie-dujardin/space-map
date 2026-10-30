"""The citations of the orbits and the held stars in the System tiles.

A `references` item of the System table names a source and a key in it
(`tables.REFERENCE`). The tiles serve each item as a CITATION: the source and
the key, and the work as a page names it, where the constants give it:
`short` (the authors and the year), `title` (with the journal) and `url` (a
DOI or an ADS page). A page shows `short` and `title`, else the key, and
links them to `url`. The keys by source:

- literature: a key of the paper tables (`binaries.REFERENCES`,
  `literature.REFERENCES`);
- gaia-dr3-orbits: a Gaia DR3 solution id, cited as the Gaia DR3 orbits;
- sbx: a bibcode, linked to its ADS page;
- msc: the note of an MSC orbit. A bibcode in the note links to its ADS page,
  and the note of a Gaia DR3 orbit ("NSS SB1", "DR3 AORB") cites the Gaia DR3
  orbits;
- orb6: a WDS reference code ("Msn2023"). Its work is not in the downloads,
  so it has no citation.
"""

import re
from urllib.parse import quote

import pyarrow as pa

from space_map_data.constants.stars import binaries, literature
from space_map_data.constants.stars.literature import Reference
from space_map_data.extrasolar.systems.nodes import GAIA_ORBITS
from space_map_data.extrasolar.systems.orbits import LITERATURE, MSC, SBX

CITATION = pa.struct(
    [
        pa.field("source", pa.string()),
        pa.field("reference", pa.string()),
        pa.field("short", pa.string()),
        pa.field("title", pa.string()),
        pa.field("url", pa.string()),
    ]
)
CITED = ("short", "title", "url")
PAPERS: dict[str, Reference] = {**literature.REFERENCES, **binaries.REFERENCES}
GAIA_ORBITS_PAPER = Reference(
    "Gaia Collaboration, Arenou et al. 2023",
    "Gaia Data Release 3. Stellar multiplicity, a teaser for the hidden treasure"
    " (A&A 674, A34)",
    "https://ui.adsabs.harvard.edu/abs/2023A&A...674A..34G",
)
ADS_URL = "https://ui.adsabs.harvard.edu/abs/"
# Year, journal, volume, qualifier, page and initial: 19 characters.
BIBCODE = re.compile(
    r"(?<!\S)(\d{4}[A-Za-z&.]{5}[\w.]{4}[\w.][\w.]{4}[A-Z.])(?=[\s,]|$)"
)
# An MSC note of a Gaia DR3 orbit.
GAIA_NOTE = re.compile(r"^(NSS|DR3)\b")


def _bibcode_url(text: str) -> str | None:
    found = BIBCODE.search(text)
    return None if found is None else ADS_URL + quote(found[1], safe="")


def work(source: str, reference: str | None) -> dict[str, str | None] | None:
    """The `short`, `title` and `url` of the work that a reference key of
    `source` names, None when the constants do not give it."""
    if not reference:
        return None
    if source == LITERATURE:
        paper = PAPERS.get(reference)
        return None if paper is None else paper._asdict()
    if source == GAIA_ORBITS or (source == MSC and GAIA_NOTE.match(reference)):
        return GAIA_ORBITS_PAPER._asdict()
    if source in (SBX, MSC) and (url := _bibcode_url(reference)):
        return {"short": None, "title": None, "url": url}
    return None


def cite(item: dict) -> dict:
    """A CITATION from a `tables.REFERENCE` item."""
    found = work(item["source"], item["reference"]) or dict.fromkeys(CITED)
    return {"source": item["source"], "reference": item["reference"], **found}
