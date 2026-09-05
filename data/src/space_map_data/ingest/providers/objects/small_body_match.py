"""Matching published asteroid-moon labels to Object rows.

Catalogues name these bodies the way their authors write them, not the way we
store them: spacing and diacritics differ (``S/2001(107)1`` for
``S/2001 (107) 1``, ``Ilmare`` for ``Ilmarë``), a moon we hold by designation
may be named, and a system may be given by number or by designation. Every
provider of asteroid-moon data needs the same three lookups, so they live here
rather than once per ingestor.
"""

import re
import unicodedata

from sqlalchemy import select
from sqlalchemy.orm import Session

from space_map_data.ingest.providers.objects.ssodnet import SPKID_OFFSET
from space_map_data.models.object import Object, ObjectType

# SBDB numbers asteroids from ``SPKID_OFFSET + 1`` upward; a million entries
# is well past the numbered catalogue and keeps comets and probes out.
_MAX_ASTEROID_SPKID = SPKID_OFFSET + 1_000_000


def fold(text: str) -> str:
    """Reduce a name or designation to comparable ASCII alphanumerics.

    Drops spacing, punctuation and diacritics, so ``S/2001 (107) 1`` and
    ``S/2001(107)1`` collapse together, as do ``Ilmarë`` and ``Ilmare``.
    """
    decomposed = unicodedata.normalize("NFKD", text)
    return "".join(c for c in decomposed.lower() if c.isascii() and c.isalnum())


def small_body_index(session: Session) -> dict[str, str]:
    """Map catalogue number and folded designation/name -> Object.id.

    Streamed rather than materialised: every small body carries an SPK-ID, so
    the query walks ~1.5M rows to build an index a caller reads a few hundred
    keys out of.
    """
    rows = session.execute(
        select(
            Object.id,
            Object.spkid,
            Object.name,
            Object.mpc_designation,
            Object.provisional_designation,
        ).where(Object.spkid.is_not(None))
    ).yield_per(10_000)
    index: dict[str, str] = {}
    for oid, spkid, name, mpc, prov in rows:
        if spkid is not None and SPKID_OFFSET < spkid <= _MAX_ASTEROID_SPKID:
            index.setdefault(str(spkid - SPKID_OFFSET), oid)
        for token in (mpc, prov, name):
            if token:
                index.setdefault(fold(token), oid)
    return index


def moons_by_parent(
    session: Session,
) -> dict[str, list[tuple[str, str | None, str | None]]]:
    """Map parent Object.id -> its moons as ``(id, name, designation)``."""
    rows = session.execute(
        select(
            Object.id,
            Object.parent_id,
            Object.name,
            Object.provisional_designation,
        ).where(Object.object_type == ObjectType.moon, Object.parent_id.is_not(None))
    ).all()
    out: dict[str, list[tuple[str, str | None, str | None]]] = {}
    for oid, parent_id, name, prov in rows:
        out.setdefault(parent_id, []).append((oid, name, prov))
    return out


def strip_tags(html: str) -> str:
    """Markup to plain text, whitespace collapsed."""
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", html)).strip()
