"""Family-aware Wikidata QID assignment for split-comet parents.

The strict 1:1 matcher (objects.py) drops any QID that maps to several of our
objects into conflicts/. For a fragmenting comet that QID — the comet's own
Wikidata item — matches both the intact parent and one or more fragments
(they share the comet number: ``73P`` matches parent 73P/Schwassmann-Wachmann 3
and fragment 73P-C), so it never gets assigned. This step resolves that
family-internal ambiguity by giving the QID to the intact parent body, leaving
each fragment's own distinct QID (where one exists) untouched.

The QID is read straight from the downloaded P5736/P490 match CSVs keyed on the
parent designation — never guessed. Parentless families (no intact body in the
catalog, e.g. Shoemaker-Levy 9) have no parent designation in the match data,
so they're logged and skipped here; their group page is anchored downstream.
"""

import logging
from collections import defaultdict
from pathlib import Path

from sqlalchemy import update

from space_map_data.constants.comet_fragments import COMET_PREFIXES, split_fragment
from space_map_data.ingest.providers.wikidata.csv_io import read_ids_csv
from space_map_data.models.object import Object
from space_map_data.models.object.sbdb import SBDB
from space_map_data.utils.db import get_session

logger = logging.getLogger(__name__)

# Designation properties whose match CSVs key on a comet's primary/provisional
# designation (the same columns objects.py feeds into mpc/provisional).
_DESIGNATION_PIDS = ("P5736", "P490")


def _parent_designation_qids(ids_dir: Path) -> dict[str, set[str]]:
    """Map each designation in the P5736/P490 match CSVs to its QID set."""
    by_designation: dict[str, set[str]] = defaultdict(set)
    matches_dir = ids_dir / "matches"
    for pid in _DESIGNATION_PIDS:
        csv_path = matches_dir / f"{pid}.csv"
        if not csv_path.exists():
            continue
        for designation, qids in read_ids_csv(csv_path).items():
            if qids:
                by_designation[designation].update(qids)
    return by_designation


def ingest(download_dir: Path) -> None:
    ids_dir = download_dir / "sources" / "metadata" / "wikidata" / "ids"
    if not ids_dir.exists():
        logger.warning("Wikidata ids/ not found at %s, skipping fragments", ids_dir)
        return

    session = get_session()
    designation_qids = _parent_designation_qids(ids_dir)

    # All comet rows, joined to their Object for the current QID.
    rows = (
        session.query(SBDB.object_id, SBDB.pdes, SBDB.prefix, Object.wikidata_qid)
        .join(Object, Object.id == SBDB.object_id)
        .filter(SBDB.prefix.in_(COMET_PREFIXES))
        .all()
    )

    parent_by_pdes: dict[str, tuple[str, str | None]] = {}  # pdes -> (obj_id, qid)
    fragment_parents: set[str] = set()
    for object_id, pdes, prefix, qid in rows:
        fragment = split_fragment(pdes, prefix)
        if fragment is not None:
            fragment_parents.add(fragment.parent_pdes)
        elif pdes is not None:
            parent_by_pdes[pdes] = (object_id, qid)

    # QIDs already claimed by some object — never reassign onto a parent.
    used_qids = {
        qid
        for (qid,) in session.query(Object.wikidata_qid)
        .filter(Object.wikidata_qid.is_not(None))
        .all()
    }

    assigned = 0
    parentless: list[str] = []
    no_qid: list[str] = []
    ambiguous: list[str] = []
    for parent_pdes in sorted(fragment_parents):
        parent = parent_by_pdes.get(parent_pdes)
        if parent is None:
            parentless.append(parent_pdes)
            continue
        object_id, existing_qid = parent
        if existing_qid is not None:
            continue  # already matched — nothing to do
        candidates = designation_qids.get(parent_pdes, set())
        if not candidates:
            no_qid.append(parent_pdes)
            continue
        if len(candidates) > 1:
            ambiguous.append(parent_pdes)
            continue
        (qid,) = tuple(candidates)
        if qid in used_qids:
            # The comet's QID is already on another object; don't duplicate it.
            ambiguous.append(parent_pdes)
            continue
        session.execute(
            update(Object).where(Object.id == object_id).values(wikidata_qid=qid)
        )
        used_qids.add(qid)
        assigned += 1
        logger.info("Split-comet parent %s matched to %s", parent_pdes, qid)

    session.commit()
    logger.info(
        "Split-comet QID assignment: %d families, %d parents matched, "
        "%d parentless (no intact body), %d parents without a designation QID, "
        "%d ambiguous/taken",
        len(fragment_parents),
        assigned,
        len(parentless),
        len(no_qid),
        len(ambiguous),
    )
    if parentless:
        logger.info("Parentless split-comet families: %s", ", ".join(parentless))
