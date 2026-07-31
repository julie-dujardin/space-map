"""Every Wikidata topic page the constants declare, in one set.

The download tiers need the QIDs and nothing else; keeping the union here
means adding a page to any one table is enough to have it fetched.
"""

from space_map_data.constants.atmosphere.wikidata import (
    ATMOSPHERE_CONCEPT_PAGES,
    ATMOSPHERE_FEATURE_PAGES,
    ATMOSPHERE_LAYER_PAGES,
    ATMOSPHERE_PAGES,
    GAS_PAGES,
)
from space_map_data.constants.interior.wikidata import (
    ANALOGUE_PAGES,
    INTERIOR_CONCEPT_PAGES,
    INTERIOR_PAGES,
    MATERIAL_PAGES,
)
from space_map_data.constants.rings.wikidata import (
    RING_CONCEPT_PAGES,
    RING_EXTRA_PAGES,
    RING_FEATURE_PAGES,
    RING_SYSTEM_PAGES,
)
from space_map_data.constants.wikidata_misc import MISC_PAGES

TOPIC_PAGE_TABLES: tuple[dict[str, tuple[str, ...]], ...] = (
    ATMOSPHERE_PAGES,
    ATMOSPHERE_LAYER_PAGES,
    ATMOSPHERE_CONCEPT_PAGES,
    ATMOSPHERE_FEATURE_PAGES,
    GAS_PAGES,
    INTERIOR_PAGES,
    MATERIAL_PAGES,
    ANALOGUE_PAGES,
    INTERIOR_CONCEPT_PAGES,
    RING_SYSTEM_PAGES,
    RING_FEATURE_PAGES,
    RING_EXTRA_PAGES,
    RING_CONCEPT_PAGES,
    MISC_PAGES,
)


def topic_page_qids() -> set[str]:
    """Deduplicated QIDs across every topic table.

    Several tables share entities on purpose — tholin is both an aerosol and
    an interior material, and Jupiter's gossamer rings answer to three feature
    rows — so the union is smaller than the row count.
    """
    return {
        qid for table in TOPIC_PAGE_TABLES for qids in table.values() for qid in qids
    }
