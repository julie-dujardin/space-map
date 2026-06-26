"""Notable moons per host body, attached to the object detail bundle.

A body's moons are its child Objects of type ``moon``. Planets carry their
moons under their *barycenter* (Jupiter naif-599 → barycenter naif-5 →
naif-50x), so a barycenter's moons are attached to its planet/dwarf-planet
host — the body the user actually focuses. Asteroid moons hang directly off
the asteroid Object, which is its own host.

Ranking mirrors notable group members: image availability, then Wikidata
sitelinks, then diameter (from SPICE PCK radii — the only diameter source
common to major moons). Discovery date isn't carried: SPICE major moons have
none in the DB and SBDB moonlets only encode it in their provisional
designation, so the moon list shows diameter alone.
"""

import logging
from collections import defaultdict
from dataclasses import dataclass

from sqlalchemy.orm import Session

from space_map_data.constants.providers import LANGUAGES
from space_map_data.export.notable import (
    NotableObject,
    notable_descriptions,
    notable_entries,
    notable_names,
    render_geometry,
)
from space_map_data.export.objects.writer import ChunkObjectData
from space_map_data.export.wikidata import WikidataEntityCache
from space_map_data.models.object.main import Object, ObjectType

logger = logging.getLogger(__name__)

# Statically-picked moons embedded in the host's global object bundle so the
# frontend renders the strip + list without per-moon fetches.
NOTABLE_MOON_COUNT = 20

_PLANET_TYPES = (ObjectType.planet, ObjectType.dwarf_planet)


@dataclass
class HostMoons:
    """Top moons of a host body plus the host's full and named moon counts."""

    moons: list[NotableObject]
    total: int
    named: int  # moons with an IAU name (asteroid moonlets are mostly unnamed)


def _mean_diameter_km(naif_id: int | None, radii: dict[int, dict]) -> float | None:
    """Mean triaxial diameter (km) from PCK radii, or None when unavailable."""
    if naif_id is None:
        return None
    r = radii.get(naif_id)
    if not r:
        return None
    vals = [v for v in (r.get("a"), r.get("b"), r.get("c")) if v is not None]
    if not vals:
        return None
    return sum(vals) / len(vals) * 2.0


def _resolve_host(session: Session, parent_id: str) -> str:
    """Map a moon's parent to the body that should display it.

    Barycenters defer to their planet/dwarf-planet child; everything else
    (asteroids) is its own host.
    """
    parent = session.get(Object, parent_id)
    if parent is None:
        return parent_id
    if parent.object_type != ObjectType.barycenter:
        return parent_id
    planet = (
        session.query(Object.id)
        .filter(Object.parent_id == parent_id, Object.object_type.in_(_PLANET_TYPES))
        .first()
    )
    if planet is not None:
        return planet[0]
    logger.warning(
        "Barycenter %s has moons but no planet/dwarf child; "
        "attaching moons to the barycenter itself",
        parent_id,
    )
    return parent_id


def notable_moons_by_host(
    session: Session, radii: dict[int, dict], orientation: dict[int, dict]
) -> dict[str, HostMoons]:
    """Top moons per host body, keyed by the host's Object.id.

    Moons are grouped by ``parent_id``, each parent resolved to its display
    host. Within a host, ranked by (has image, sitelinks, diameter) with an
    id tiebreak for deterministic selection across exports.
    """
    rows = (
        session.query(
            Object.id,
            Object.parent_id,
            Object.wikidata_qid,
            Object.name,
            Object.provisional_designation,
            Object.naif_id,
            Object.image_available,
            Object.sitelinks_count,
        )
        .filter(Object.object_type == ObjectType.moon)
        .all()
    )

    by_parent: dict[str, list] = defaultdict(list)
    orphans = 0
    for row in rows:
        if row.parent_id is None:
            orphans += 1
            continue
        by_parent[row.parent_id].append(row)
    if orphans:
        logger.warning(
            "%d moon(s) have no parent_id; excluded from moon lists", orphans
        )

    result: dict[str, HostMoons] = {}
    for parent_id, children in by_parent.items():
        host_id = _resolve_host(session, parent_id)
        # Stable id pre-sort so equal-ranked moons keep a deterministic order.
        children.sort(key=lambda r: r.id)
        children.sort(
            key=lambda r: (
                r.image_available,
                r.sitelinks_count,
                _mean_diameter_km(r.naif_id, radii) or 0.0,
            ),
            reverse=True,
        )
        top = children[:NOTABLE_MOON_COUNT]
        moons = []
        for r in top:
            # Triaxial radii + pole give the lineup its true oblate shape and tilt
            # (the same geometry as the 3D scene); diameter_km stays for the list.
            geo = render_geometry(
                r.naif_id, r.wikidata_qid, radii, orientation=orientation
            )
            moons.append(
                NotableObject(
                    object_id=r.id,
                    wikidata_qid=r.wikidata_qid,
                    fallback_name=r.name or r.provisional_designation or r.id,
                    diameter_km=_mean_diameter_km(r.naif_id, radii),
                    first_obs=None,
                    radii=geo.radii,
                    pole=geo.pole,
                )
            )
        named = sum(1 for r in children if r.name)
        # A host may already be present from another parent (shouldn't happen —
        # one parent per host — but merge defensively rather than overwrite).
        existing = result.get(host_id)
        if existing is None:
            result[host_id] = HostMoons(moons=moons, total=len(children), named=named)
        else:
            existing.moons.extend(moons)
            existing.total += len(children)
            existing.named += named

    logger.info(
        "Built notable moons for %d host bodies (%d moons total across %d parents)",
        len(result),
        len(rows) - orphans,
        len(by_parent),
    )
    return result


def attach_notable_moons(
    session: Session,
    chunk: ChunkObjectData,
    wikidata_entities: WikidataEntityCache,
    radii: dict[int, dict],
    orientation: dict[int, dict],
) -> None:
    """Inject ``notable_moons`` + ``moon_count`` + ``named_moon_count`` into
    each host's global bundle.

    Mutates ``chunk`` in place (mirrors ``write_attitude``). Localized moon
    names are added only where the host already has a localized entry for the
    language, so the per-row ``has_localized`` bit shipped in the binary chunk
    stays consistent (it's written during the zone pass and can't be flipped
    here).
    """
    hosts = notable_moons_by_host(session, radii, orientation)
    attached = 0
    for host_id, host_moons in hosts.items():
        global_data = chunk.global_data.get(host_id)
        if global_data is None:
            logger.warning(
                "Notable moons computed for %s but it has no object bundle; skipping",
                host_id,
            )
            continue
        entries = notable_entries(host_moons.moons, wikidata_entities)
        global_data["notable_moons"] = entries
        global_data["moon_count"] = host_moons.total
        if host_moons.named:
            global_data["named_moon_count"] = host_moons.named
        for lang in LANGUAGES:
            localized = chunk.localized_data.get(lang, {}).get(host_id)
            if localized is None:
                continue
            names = notable_names(host_moons.moons, entries, lang, wikidata_entities)
            if names:
                localized["notable_moon_names"] = names
            # Short descriptions feed the planet-page moon lineup hover tooltip.
            descriptions = notable_descriptions(
                host_moons.moons, lang, wikidata_entities
            )
            if descriptions:
                localized["notable_moon_descriptions"] = descriptions
        attached += 1
    logger.info("Attached notable moons to %d host bodies", attached)
