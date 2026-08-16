"""Post-ingest invariants that span providers.

Run after `ingest_objects` completes. Hard-raise on violation — these are
the contracts that downstream consumers (export, frontend URLs, model
assignment) silently depend on.
"""

import logging
from collections import defaultdict

from sqlalchemy import select
from sqlalchemy.orm import Session

from space_map_data.models.object import Object

logger = logging.getLogger(__name__)


class NamespaceCollisionError(RuntimeError):
    """Probe-* and norad_satcat-* namespaces overlap on NORAD or COSPAR."""


def assert_no_namespace_collision(session: Session) -> None:
    """Probe and norad_satcat namespaces must be disjoint by NORAD + COSPAR.

    A spacecraft lives in exactly one namespace; cross-namespace duplication
    would split its metadata, models, and URL identity for every consumer
    that joins by NORAD or COSPAR. Checks: no shared NORAD across the two
    namespaces; no shared COSPAR for a *NORAD-less* probe (COSPAR isn't
    unique across NORADs, e.g. Apollo 8 spans satcat 3626/3627, so only
    NORAD-less probes — which rely on COSPAR for identity — count); and the
    `satcat_norad_cat_id` FK must agree with the denormalized `norad_cat_id`.

    Joint-launch siblings sharing a NORAD within the probe namespace (e.g.
    Cassini + Huygens) are fine — the invariant is cross-namespace only.
    """
    probe_norads = _column_values(
        session, Object.norad_cat_id, prefix="probe-", non_null=True
    )
    sat_norads = _column_values(
        session, Object.norad_cat_id, prefix="norad_satcat-", non_null=True
    )
    norad_overlap = probe_norads & sat_norads

    # Only NORAD-less probes rely on COSPAR for identity (see docstring).
    probe_cospars = _column_values(
        session,
        Object.cospar_id,
        prefix="probe-",
        non_null=True,
        extra_where=(Object.norad_cat_id.is_(None),),
    )
    sat_cospars = _column_values(
        session, Object.cospar_id, prefix="norad_satcat-", non_null=True
    )
    cospar_overlap = probe_cospars & sat_cospars

    inconsistent = session.execute(
        select(Object.id, Object.norad_cat_id, Object.satcat_norad_cat_id).where(
            Object.satcat_norad_cat_id.is_not(None),
            Object.norad_cat_id != Object.satcat_norad_cat_id,
        )
    ).all()

    if not (norad_overlap or cospar_overlap or inconsistent):
        n_probes = session.scalar(
            select(Object.id).where(Object.id.like("probe-%")).limit(1)
        )
        n_sats = session.scalar(
            select(Object.id).where(Object.id.like("norad_satcat-%")).limit(1)
        )
        logger.info(
            "namespace check: OK (probes present=%s, norad_satcat present=%s)",
            bool(n_probes),
            bool(n_sats),
        )
        return

    diag: list[str] = []
    if norad_overlap:
        diag.append(_format_norad_overlap(session, norad_overlap))
    if cospar_overlap:
        diag.append(_format_cospar_overlap(session, cospar_overlap))
    if inconsistent:
        diag.append(_format_fk_inconsistency(inconsistent))

    raise NamespaceCollisionError(
        "namespace invariant violated:\n  " + "\n  ".join(diag)
    )


def _column_values(
    session: Session, column, *, prefix: str, non_null: bool, extra_where=()
) -> set:
    stmt = select(column).where(Object.id.like(f"{prefix}%"))
    if non_null:
        stmt = stmt.where(column.is_not(None))
    for cond in extra_where:
        stmt = stmt.where(cond)
    return {v for (v,) in session.execute(stmt).all()}


def _format_norad_overlap(session: Session, norads: set[int]) -> str:
    grouped = _group_by_norad(session, norads)
    lines = [f"NORAD overlap probe ↔ norad_satcat ({len(norads)}):"]
    for norad in sorted(norads):
        lines.append(f"    NORAD {norad}: " + ", ".join(grouped.get(norad, [])))
    return "\n  ".join(lines)


def _format_cospar_overlap(session: Session, cospars: set[str]) -> str:
    grouped = _group_by_cospar(session, cospars)
    lines = [f"COSPAR overlap probe ↔ norad_satcat ({len(cospars)}):"]
    for cospar in sorted(cospars):
        lines.append(f"    COSPAR {cospar}: " + ", ".join(grouped.get(cospar, [])))
    return "\n  ".join(lines)


def _format_fk_inconsistency(rows) -> str:
    lines = [f"FK ↔ norad_cat_id mismatch ({len(rows)}):"]
    for oid, denorm, fk in rows[:20]:
        lines.append(f"    {oid}: norad_cat_id={denorm} satcat_norad_cat_id={fk}")
    if len(rows) > 20:
        lines.append(f"    ... ({len(rows) - 20} more)")
    return "\n  ".join(lines)


def _group_by_norad(session: Session, norads: set[int]) -> dict[int, list[str]]:
    out: dict[int, list[str]] = defaultdict(list)
    for oid, norad in session.execute(
        select(Object.id, Object.norad_cat_id).where(Object.norad_cat_id.in_(norads))
    ).all():
        out[norad].append(oid)
    return out


def _group_by_cospar(session: Session, cospars: set[str]) -> dict[str, list[str]]:
    out: dict[str, list[str]] = defaultdict(list)
    for oid, cospar in session.execute(
        select(Object.id, Object.cospar_id).where(Object.cospar_id.in_(cospars))
    ).all():
        out[cospar].append(oid)
    return out
