from space_map_data.constants.earth_sats.constellations import CONSTELLATIONS
from space_map_data.constants.earth_sats.gcat_qids import (
    GCAT_PAD_QIDS,
    GCAT_SITE_QIDS,
)
from space_map_data.constants.earth_sats.launch_sites import LAUNCH_SITES
from space_map_data.constants.earth_sats.operators import OPERATORS
from space_map_data.constants.earth_sats.satellite_models import SATELLITE_BUSES


def all_wikidata_qids() -> set[str]:
    """All Wikidata QIDs referenced by earth-sat constant catalogs."""
    qids: set[str] = set()
    for spec in CONSTELLATIONS:
        if spec.wikidata_qid is not None:
            qids.add(spec.wikidata_qid)
    for spec in OPERATORS:
        if spec.wikidata_qid is not None:
            qids.add(spec.wikidata_qid)
    for spec in LAUNCH_SITES:
        if spec.wikidata_qid is not None:
            qids.add(spec.wikidata_qid)
    for spec in SATELLITE_BUSES:
        if spec.wikidata_qid is not None:
            qids.add(spec.wikidata_qid)
    # GCAT places inside those sites: the individual cosmodromes and pads,
    # which no satellite claim reaches.
    qids.update(GCAT_SITE_QIDS.values())
    qids.update(qid for pads in GCAT_PAD_QIDS.values() for qid in pads.values())
    return qids
