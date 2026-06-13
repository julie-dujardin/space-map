"""Split-comet fragments, attached to object detail bundles.

A fragmenting comet (73P/Schwassmann-Wachmann 3, …) appears in SBDB as the
intact parent plus a ``<pdes>-<letters>`` row per piece. This module groups
those rows into families and, mirroring ``objects/moons.py``:

- attaches a ranked ``fragments`` list + ``fragment_count`` to the intact
  parent's bundle (the family's home page), and
- stamps each fragment's bundle with ``fragment_of`` for the "Fragment of
  <parent>" stat card + breadcrumb.

Parentless families (no intact body in the catalog) carry no parent bundle;
their ``fragment_of`` points at the synthetic family group page instead, and
the fragment list is surfaced there (see groups tier). Ranking mirrors notable
members: image availability, then Wikidata sitelinks, with an id tiebreak.
"""

import logging
import re
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy.orm import Session

from space_map_data.constants.comet_fragments import (
    COMET_PREFIXES,
    family_group_slug,
    split_fragment,
)
from space_map_data.constants.providers import LANGUAGES
from space_map_data.export.images import collect_object_images, pick_thumbnail
from space_map_data.export.notable import NotableObject, notable_entries, notable_names
from space_map_data.export.objects.writer import ChunkObjectData
from space_map_data.export.wikidata import WikidataEntityCache
from space_map_data.models.object.main import Object
from space_map_data.models.object.sbdb import SBDB, CometPrefix

logger = logging.getLogger(__name__)

# Fragments embedded in the parent/group bundle for the strip + list.
NOTABLE_FRAGMENT_COUNT = 20


@dataclass
class CometFamily:
    """A split comet: its intact parent (if catalogued) and ranked fragments."""

    parent_pdes: str
    parent_object_id: str | None  # None for parentless families (e.g. SL9)
    parent_qid: str | None
    parent_name: str  # display name for the breadcrumb / stat card
    designation: str = ""  # full IAU designation, e.g. "C/1860 D1" or "483P"
    fragments: list[NotableObject] = field(default_factory=list)  # capped display list
    member_ids: list[str] = field(default_factory=list)  # every fragment's object id
    total: int = 0


def _parent_display_name(
    obj_name: str | None,
    full_name: str | None,
    qid: str | None,
    wikidata_entities: WikidataEntityCache,
) -> str | None:
    """Wikidata English label when available, else the catalog name."""
    if qid:
        wd = wikidata_entities.get_entity(qid)
        label = wd["labels"].get("en") if wd else None
        if label:
            return label
    return obj_name or full_name


def _parentless_name(full_name: str | None, parent_pdes: str, suffix: str) -> str:
    """Reconstruct a parent label from a fragment's full name.

    Drops the ``-<suffix>`` where it sits before the parenthetical name or the
    end of the designation — covers both ``C/1882 R1-A (Great September comet)``
    → ``C/1882 R1 (Great September comet)`` and the numbered form
    ``483P/PANSTARRS-A`` → ``483P/PANSTARRS`` (where the suffix rides the name,
    not the designation). Falls back to the bare designation.
    """
    if not full_name:
        return parent_pdes
    return re.sub(rf"-{re.escape(suffix)}(?=\s*\(|$)", "", full_name, count=1)


def _iau_designation(parent_pdes: str, prefix: CometPrefix | None) -> str:
    """Full IAU designation: numbered comets stay bare (``483P``); provisional
    ones get their prefix (``1860 D1`` + ``C`` → ``C/1860 D1``)."""
    if re.match(r"^\d+[A-Z]$", parent_pdes) or prefix is None:
        return parent_pdes
    return f"{prefix.name}/{parent_pdes}"


# A Wikidata label denotes a single fragment (not the whole comet) when it ends
# in a "-<letters>" suffix before the parenthetical name or end of string —
# "C/2001 A2-B", "C/1996 J1-A (Evans-Drinkwater)".
_FRAGMENT_LABEL_RE = re.compile(r"-[A-Z]{1,2}(?=\s*\(|\s*$)")


def _resolve_parentless_qid(
    frag_rows: list[Any], wikidata_entities: WikidataEntityCache
) -> str | None:
    """Comet-level QID among the fragments' own Wikidata links, if unambiguous.

    A parentless comet has no intact body to match, but editors often attach the
    comet's page to some fragments and a per-fragment item to others. The
    comet-level QID is the one whose label carries no fragment suffix; return it
    only when exactly one such QID exists (else there's no single family page).
    """
    candidates = {r.wikidata_qid for r in frag_rows if r.wikidata_qid}
    comet_level = {
        qid
        for qid in candidates
        if not _FRAGMENT_LABEL_RE.search(
            (
                wd["labels"].get("en")
                if (wd := wikidata_entities.get_entity(qid))
                else ""
            )
            or ""
        )
    }
    return next(iter(comet_level)) if len(comet_level) == 1 else None


def build_comet_families(
    session: Session, wikidata_entities: WikidataEntityCache
) -> dict[str, CometFamily]:
    """Group comet rows into split-comet families, keyed by parent designation.

    Only families with at least one fragment are returned. Within a family,
    fragments are ranked (image, sitelinks, id) and capped for display, but
    ``total`` reflects the full count.
    """
    rows = (
        session.query(
            SBDB.object_id,
            SBDB.pdes,
            SBDB.prefix,
            SBDB.full_name,
            Object.name,
            Object.wikidata_qid,
            Object.image_available,
            Object.sitelinks_count,
        )
        .join(Object, Object.id == SBDB.object_id)
        .filter(SBDB.prefix.in_(COMET_PREFIXES))
        .all()
    )

    parents: dict[str, Any] = {}  # pdes -> intact-parent SBDB/Object row
    frags_by_parent: dict[str, list] = defaultdict(list)
    frag_suffix: dict[str, str] = {}  # object_id -> suffix
    for row in rows:
        fragment = split_fragment(row.pdes, row.prefix)
        if fragment is not None:
            frags_by_parent[fragment.parent_pdes].append(row)
            frag_suffix[row.object_id] = fragment.suffix
        elif row.pdes is not None:
            parents[row.pdes] = row

    families: dict[str, CometFamily] = {}
    for parent_pdes, frag_rows in frags_by_parent.items():
        frag_rows.sort(key=lambda r: r.object_id)
        frag_rows.sort(
            key=lambda r: (r.image_available, r.sitelinks_count), reverse=True
        )
        top = frag_rows[:NOTABLE_FRAGMENT_COUNT]
        fragments = [
            NotableObject(
                object_id=r.object_id,
                wikidata_qid=r.wikidata_qid,
                fallback_name=r.pdes or r.full_name or r.object_id,
                diameter_km=None,
                first_obs=None,
            )
            for r in top
        ]
        member_ids = [r.object_id for r in frag_rows]

        designation = _iau_designation(parent_pdes, frag_rows[0].prefix)
        parent = parents.get(parent_pdes)
        if parent is not None:
            parent_name = _parent_display_name(
                parent.name, parent.full_name, parent.wikidata_qid, wikidata_entities
            )
            family = CometFamily(
                parent_pdes=parent_pdes,
                parent_object_id=parent.object_id,
                parent_qid=parent.wikidata_qid,
                parent_name=parent_name or parent_pdes,
                designation=designation,
                fragments=fragments,
                member_ids=member_ids,
                total=len(frag_rows),
            )
        else:
            rep = top[0]
            reconstructed = _parentless_name(
                rep.full_name, parent_pdes, frag_suffix[rep.object_id]
            )
            qid = _resolve_parentless_qid(frag_rows, wikidata_entities)
            family = CometFamily(
                parent_pdes=parent_pdes,
                parent_object_id=None,
                parent_qid=qid,
                parent_name=_parent_display_name(
                    reconstructed, None, qid, wikidata_entities
                )
                or reconstructed,
                designation=designation,
                fragments=fragments,
                member_ids=member_ids,
                total=len(frag_rows),
            )
        families[parent_pdes] = family

    parentless = sum(1 for f in families.values() if f.parent_object_id is None)
    logger.info(
        "Built %d split-comet families (%d parentless), %d fragments total",
        len(families),
        parentless,
        sum(f.total for f in families.values()),
    )
    return families


def _fragment_of(family: CometFamily) -> dict:
    """The ``fragment_of`` block a fragment carries: parent name + route + image."""
    out: dict = {"name": family.parent_name}
    if family.parent_object_id is not None:
        out["primary_type"] = "object"
        out["primary_id"] = family.parent_object_id
        thumbnail = pick_thumbnail(collect_object_images(family.parent_object_id))
        if thumbnail:
            out["thumbnail"] = thumbnail
    else:
        out["primary_type"] = "group"
        out["primary_id"] = family_group_slug(family.parent_pdes)
    return out


def attach_comet_fragments(
    session: Session,
    chunk: ChunkObjectData,
    wikidata_entities: WikidataEntityCache,
) -> None:
    """Inject ``fragments``/``fragment_count`` onto parents and ``fragment_of``
    onto each fragment. Mutates ``chunk`` in place (mirrors notable moons)."""
    families = build_comet_families(session, wikidata_entities)
    parents_done = 0
    frags_done = 0
    for family in families.values():
        fragment_of = _fragment_of(family)
        # Stamp every fragment, not just the capped display list — otherwise the
        # 53rd piece of 73P would carry no parent link.
        for object_id in family.member_ids:
            global_data = chunk.global_data.get(object_id)
            if global_data is not None:
                global_data["fragment_of"] = fragment_of
                frags_done += 1

        if family.parent_object_id is None:
            continue
        parent_global = chunk.global_data.get(family.parent_object_id)
        if parent_global is None:
            logger.warning(
                "Split-comet parent %s has fragments but no object bundle; skipping",
                family.parent_pdes,
            )
            continue
        entries = notable_entries(family.fragments, wikidata_entities)
        parent_global["fragments"] = entries
        parent_global["fragment_count"] = family.total
        for lang in LANGUAGES:
            localized = chunk.localized_data.get(lang, {}).get(family.parent_object_id)
            if localized is None:
                continue
            names = notable_names(family.fragments, entries, lang, wikidata_entities)
            if names:
                localized["fragment_names"] = names
        parents_done += 1

    logger.info(
        "Attached fragments to %d parents and fragment_of to %d fragments",
        parents_done,
        frags_done,
    )
