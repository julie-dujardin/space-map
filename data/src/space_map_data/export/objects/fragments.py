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
from space_map_data.models.object.sbdb import SBDB

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
    fragments: list[NotableObject] = field(default_factory=list)
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

    ``C/1882 R1-A (Great September comet)`` → ``C/1882 R1 (Great September comet)``;
    falls back to the bare designation when the full name is missing.
    """
    if full_name:
        return full_name.replace(f"{parent_pdes}-{suffix}", parent_pdes, 1)
    return parent_pdes


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
                fragments=fragments,
                total=len(frag_rows),
            )
        else:
            rep = top[0]
            family = CometFamily(
                parent_pdes=parent_pdes,
                parent_object_id=None,
                parent_qid=None,
                parent_name=_parentless_name(
                    rep.full_name, parent_pdes, frag_suffix[rep.object_id]
                ),
                fragments=fragments,
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
        for fragment in family.fragments:
            global_data = chunk.global_data.get(fragment.object_id)
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
