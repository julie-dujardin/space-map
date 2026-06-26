"""Per-orbit-class and per-flag stats for small-body groups.

No membership inverted index ships for small bodies — orbit class is the
selector and the export already partitions positions by class under
``small_bodies/<class>/``. NEO/PHA flags ride on the per-point ``flags`` byte
of the elements tiles and are filtered render-time on the frontend. Only
aggregate stats are needed in the group bundle.

The filter mirrors ``_iter_sbdb_zone_snapshots`` so stats match the rows
that ship. Aggregations run server-side (GROUP BY) to keep the ~1.3M-row
scan out of the ORM.
"""

import gzip
import logging
import math
from dataclasses import dataclass, field
from pathlib import Path

import orjson
from sqlalchemy import func, or_
from sqlalchemy.orm import Session

from space_map_data.constants.categories import COMET_ORBIT_CLASSES
from space_map_data.export.groups.registry import (
    CLASS_SLUG_PREFIX,
    SMALL_BODY_FLAG_SLUG_PREFIX,
)
from space_map_data.export.notable import (
    NotableObject,
    pole_from_orientation,
    render_size,
)
from space_map_data.export.quantities import UnitConverter
from space_map_data.export.wikidata import WikidataEntityCache
from space_map_data.models.object.main import Object, OrbitalSource
from space_map_data.models.object.sbdb import SBDB, CometPrefix, OrbitClass

logger = logging.getLogger(__name__)

# Target sample count for the orbit-class scatter plot. Allocation is
# sqrt-weighted by population with a per-class floor so even tiny classes
# (a few dozen rows) stay visible. No upper cap — MBA dominates the chart
# the same way it dominates the real population.
SCATTER_TARGET = 1000
SCATTER_FLOOR = 5

# Statically-picked "notable members" per group, embedded in the group bundle
# so the frontend renders the strip + members list without per-object fetches.
NOTABLE_MEMBER_COUNT = 20


@dataclass
class OrbitClassSample:
    """One scatter-plot point for the orbit-class chart."""

    slug: str  # class-<OrbitClass.name>
    name: str
    a: float | None  # AU; None for parabolic comets (e = 1)
    e: float
    q: float  # AU; perihelion, always defined
    i: float | None  # deg
    neo: bool
    pha: bool


@dataclass
class LargestBody:
    """The biggest member (by ``SBDB.diameter``) of a small-body group."""

    name: str
    diameter_km: float
    spkid: str


@dataclass
class SmallBodyGroupStats:
    """Per-slug counts, histograms, scatter samples, PHA counts, largest body."""

    member_counts: dict[str, int] = field(default_factory=dict)
    # Members with an IAU name, per asteroid class slug. Comets are omitted:
    # they all carry a designation, so their named/total split is meaningless.
    named_counts: dict[str, int] = field(default_factory=dict)
    discovery_histograms: dict[str, dict[int, int]] = field(default_factory=dict)
    orbit_samples: list[OrbitClassSample] = field(default_factory=list)
    # NEO is omitted on purpose: 100 % on IEO/ATE/APO/AMO, 0 % elsewhere.
    pha_counts: dict[str, int] = field(default_factory=dict)
    largest_bodies: dict[str, LargestBody] = field(default_factory=dict)
    notable_members: dict[str, list[NotableObject]] = field(default_factory=dict)


def _exported_sbdb_filter():
    """The row-level filter shared with `_iter_sbdb_zone_snapshots`."""
    return (
        SBDB.prefix.is_distinct_from(CometPrefix.D),
        or_(
            Object.orbital_source.is_(None),
            Object.orbital_source == OrbitalSource.sbdb,
        ),
    )


def _allocate_samples(
    class_counts: dict[OrbitClass, int],
    target: int = SCATTER_TARGET,
    floor: int = SCATTER_FLOOR,
) -> dict[OrbitClass, int]:
    """sqrt-weighted allocation with a per-class floor capped by population.

    Classes with 0 members get 0. No upper cap — MBA naturally dominates.
    """
    weights = {cls: math.sqrt(n) for cls, n in class_counts.items() if n > 0}
    total_w = sum(weights.values())
    out: dict[OrbitClass, int] = {}
    for cls, n in class_counts.items():
        if n == 0:
            out[cls] = 0
            continue
        raw = round(target * weights[cls] / total_w)
        out[cls] = min(max(raw, floor), n)
    return out


def _sample_orbit_class(
    session: Session, cls: OrbitClass, n: int
) -> list[OrbitClassSample]:
    """Pick ``n`` deterministic samples from one orbit class.

    Ordered by ``Object.random_int`` — that's a hash of the PK populated at
    insert, so the same rows come back across export runs as long as the DB
    is the same. Skips rows missing the elements we plot.
    """
    rows = (
        session.query(
            SBDB.full_name,
            SBDB.name,
            SBDB.pdes,
            SBDB.a,
            SBDB.e,
            SBDB.q,
            SBDB.i,
            SBDB.neo,
            SBDB.pha,
        )
        .join(Object, Object.id == SBDB.object_id)
        .filter(*_exported_sbdb_filter())
        .filter(SBDB.class_ == cls)
        .filter(SBDB.e.is_not(None), SBDB.q.is_not(None))
        .order_by(Object.random_int)
        .limit(n)
        .all()
    )
    slug = f"{CLASS_SLUG_PREFIX}{cls.name}"
    return [
        OrbitClassSample(
            slug=slug,
            name=full_name or name or pdes or "",
            a=a,
            e=e,
            q=q,
            i=i,
            neo=bool(neo),
            pha=bool(pha),
        )
        for (full_name, name, pdes, a, e, q, i, neo, pha) in rows
    ]


def build_orbit_class_samples(
    session: Session, class_counts: dict[OrbitClass, int]
) -> list[OrbitClassSample]:
    """Pick a representative scatter sample for every non-empty orbit class."""
    allocation = _allocate_samples(class_counts)
    samples: list[OrbitClassSample] = []
    short_falls: list[tuple[str, int, int]] = []
    for cls, n in allocation.items():
        if n == 0:
            continue
        class_samples = _sample_orbit_class(session, cls, n)
        samples.extend(class_samples)
        if len(class_samples) < n:
            short_falls.append((cls.name, n, len(class_samples)))
    if short_falls:
        logger.info(
            "Orbit class sampling shortfall (missing a/e/q in DB): %s",
            ", ".join(f"{c}: {got}/{want}" for c, want, got in short_falls),
        )
    logger.info(
        "Built %d orbit-class scatter samples across %d classes (target=%d, floor=%d)",
        len(samples),
        sum(1 for n in allocation.values() if n > 0),
        SCATTER_TARGET,
        SCATTER_FLOOR,
    )
    return samples


def _largest_body(session: Session, *filter_clauses) -> LargestBody | None:
    """Largest ``diameter`` matching the filters; ``None`` if nothing has one.

    Skips the orbital-source clause so SPICE-routed dwarf planets (Ceres,
    Pluto, …) still count.
    """
    row = (
        session.query(SBDB.full_name, SBDB.name, SBDB.pdes, SBDB.spkid, SBDB.diameter)
        .join(Object, Object.id == SBDB.object_id)
        .filter(SBDB.prefix.is_distinct_from(CometPrefix.D))
        .filter(SBDB.diameter.is_not(None))
        .filter(*filter_clauses)
        .order_by(SBDB.diameter.desc())
        .limit(1)
        .one_or_none()
    )
    if row is None:
        return None
    full_name, name, pdes, spkid, diameter = row
    if spkid is None:
        return None
    return LargestBody(
        name=full_name or name or pdes or spkid,
        diameter_km=diameter,
        spkid=spkid,
    )


def _notable_members(
    session: Session,
    *filter_clauses,
    radii: dict[int, dict] | None = None,
    units: UnitConverter | None = None,
    wikidata_entities: WikidataEntityCache | None = None,
    orientation: dict[int, dict] | None = None,
) -> list[NotableObject]:
    """Top members by (has image, sitelinks, diameter, brightness).

    Sitelinks dominate in practice — image availability mostly promotes the
    photogenic famous few into the strip's leading slots. Diameter then H
    degrade gracefully for groups with no Wikidata coverage at all. Like
    ``_largest_body``, skips the orbital-source clause so SPICE-routed dwarf
    planets (Ceres, Pluto, …) still rank. spkid tiebreak keeps the selection
    deterministic across exports.

    ``radii``/``units``/``wikidata_entities`` resolve each member's render size
    (PCK triaxial radii or the Wikidata-radius override) so the lineup hero
    sizes dwarf planets the same way the 3D scene does. ``orientation`` gives the
    PCK dwarfs (Ceres in MBA, Pluto in TNO) the same axial tilt they get on the
    dwarf-planet page.
    """
    rows = (
        session.query(
            Object.id,
            Object.naif_id,
            Object.wikidata_qid,
            Object.name,
            SBDB.full_name,
            SBDB.name,
            SBDB.pdes,
            SBDB.spkid,
            SBDB.diameter,
            SBDB.first_obs,
            SBDB.albedo,
            SBDB.spec_B,
            SBDB.spec_T,
        )
        .join(Object, Object.id == SBDB.object_id)
        .filter(SBDB.prefix.is_distinct_from(CometPrefix.D))
        .filter(SBDB.spkid.is_not(None))
        .filter(*filter_clauses)
        .order_by(
            Object.image_available.desc(),
            Object.sitelinks_count.desc(),
            SBDB.diameter.desc().nullslast(),
            SBDB.H.asc().nullslast(),
            SBDB.spkid,
        )
        .limit(NOTABLE_MEMBER_COUNT)
        .all()
    )
    radii = radii or {}
    orientation = orientation or {}
    members: list[NotableObject] = []
    for row in rows:
        (
            object_id,
            naif_id,
            qid,
            obj_name,
            full_name,
            sbdb_name,
            pdes,
            spkid,
            diameter,
            first_obs,
            albedo,
            spec_b,
            spec_t,
        ) = row
        triaxial, radius_km = render_size(naif_id, qid, radii, units, wikidata_entities)
        members.append(
            NotableObject(
                object_id=object_id,
                wikidata_qid=qid,
                fallback_name=obj_name or full_name or sbdb_name or pdes or str(spkid),
                diameter_km=diameter,
                first_obs=first_obs,
                radii=triaxial,
                radius_km=radius_km,
                pole=pole_from_orientation(orientation, naif_id),
                albedo=albedo,
                # SMASS (spec_B) preferred over Tholen (spec_T); the frontend maps
                # the taxonomic class to a representative surface tint.
                spec=spec_b or spec_t,
            )
        )
    return members


def build_small_body_group_stats(
    session: Session,
    radii: dict[int, dict] | None = None,
    units: UnitConverter | None = None,
    wikidata_entities: WikidataEntityCache | None = None,
    orientation: dict[int, dict] | None = None,
) -> SmallBodyGroupStats:
    """Return member counts and discovery-year histograms per small-body group.

    All aggregation runs in SQL — the function pulls only summary rows
    (~5k for class×year histograms, ~200 each for NEO/PHA). Rows lacking a
    parseable year are excluded from histograms but still count toward
    ``member_counts``. ``radii``/``units``/``wikidata_entities``/``orientation``
    give notable members their render size + tilt for the lineup hero.
    """
    base = (
        session.query(SBDB)
        .join(Object, Object.id == SBDB.object_id)
        .filter(*_exported_sbdb_filter())
    )

    class_counts_rows = (
        base.with_entities(SBDB.class_, func.count(SBDB.spkid))
        .group_by(SBDB.class_)
        .all()
    )
    class_counts: dict[OrbitClass, int] = {cls: n for cls, n in class_counts_rows}
    member_counts: dict[str, int] = {
        f"{CLASS_SLUG_PREFIX}{cls.name}": n for cls, n in class_counts.items()
    }
    neo_count = base.filter(SBDB.neo.is_(True)).count()
    pha_count = base.filter(SBDB.pha.is_(True)).count()
    member_counts[f"{SMALL_BODY_FLAG_SLUG_PREFIX}neo"] = neo_count
    member_counts[f"{SMALL_BODY_FLAG_SLUG_PREFIX}pha"] = pha_count

    # Named (IAU-named) counts per asteroid class. Asteroids are overwhelmingly
    # designation-only (~1.7 % named), so the frontend pairs this with the total.
    # Comet classes are excluded — every comet shows a designation regardless.
    named_counts_rows = (
        base.with_entities(SBDB.class_, func.count(SBDB.spkid))
        .filter(SBDB.name.is_not(None), SBDB.name != "")
        .filter(SBDB.class_.not_in(COMET_ORBIT_CLASSES))
        .group_by(SBDB.class_)
        .all()
    )
    named_counts = {
        f"{CLASS_SLUG_PREFIX}{cls.name}": n for cls, n in named_counts_rows if n
    }

    year_expr = func.substr(SBDB.first_obs, 1, 4)
    discovery_histograms: dict[str, dict[int, int]] = {}
    malformed_years: set[str] = set()

    def _add(slug: str, year_str: str | None, n: int) -> None:
        if year_str is None:
            return
        try:
            year = int(year_str)
        except ValueError:
            malformed_years.add(year_str)
            return
        hist = discovery_histograms.setdefault(slug, {})
        hist[year] = hist.get(year, 0) + n

    class_year_rows = (
        base.with_entities(SBDB.class_, year_expr, func.count(SBDB.spkid))
        .filter(SBDB.first_obs.is_not(None))
        .group_by(SBDB.class_, year_expr)
        .all()
    )
    for cls, year_str, n in class_year_rows:
        _add(f"{CLASS_SLUG_PREFIX}{cls.name}", year_str, n)

    neo_year_rows = (
        base.with_entities(year_expr, func.count(SBDB.spkid))
        .filter(SBDB.neo.is_(True), SBDB.first_obs.is_not(None))
        .group_by(year_expr)
        .all()
    )
    for year_str, n in neo_year_rows:
        _add(f"{SMALL_BODY_FLAG_SLUG_PREFIX}neo", year_str, n)

    pha_year_rows = (
        base.with_entities(year_expr, func.count(SBDB.spkid))
        .filter(SBDB.pha.is_(True), SBDB.first_obs.is_not(None))
        .group_by(year_expr)
        .all()
    )
    for year_str, n in pha_year_rows:
        _add(f"{SMALL_BODY_FLAG_SLUG_PREFIX}pha", year_str, n)

    missing_first_obs = (
        base.with_entities(func.count(SBDB.spkid))
        .filter(SBDB.first_obs.is_(None))
        .scalar()
        or 0
    )
    if missing_first_obs or malformed_years:
        logger.info(
            "Small-body discovery histograms: %d rows without first_obs, "
            "%d malformed year value(s) excluded: %s",
            missing_first_obs,
            len(malformed_years),
            sorted(malformed_years) if malformed_years else "[]",
        )

    pha_per_class_rows = (
        base.with_entities(SBDB.class_, func.count(SBDB.spkid))
        .filter(SBDB.pha.is_(True))
        .group_by(SBDB.class_)
        .all()
    )
    pha_counts = {
        f"{CLASS_SLUG_PREFIX}{cls.name}": n for cls, n in pha_per_class_rows if n
    }

    largest_bodies: dict[str, LargestBody] = {}
    for cls in class_counts:
        body = _largest_body(session, SBDB.class_ == cls)
        if body is not None:
            largest_bodies[f"{CLASS_SLUG_PREFIX}{cls.name}"] = body
    neo_largest = _largest_body(session, SBDB.neo.is_(True))
    if neo_largest is not None:
        largest_bodies[f"{SMALL_BODY_FLAG_SLUG_PREFIX}neo"] = neo_largest
    pha_largest = _largest_body(session, SBDB.pha.is_(True))
    if pha_largest is not None:
        largest_bodies[f"{SMALL_BODY_FLAG_SLUG_PREFIX}pha"] = pha_largest

    notable_members: dict[str, list[NotableObject]] = {}
    for cls in class_counts:
        members = _notable_members(
            session,
            SBDB.class_ == cls,
            radii=radii,
            units=units,
            wikidata_entities=wikidata_entities,
            orientation=orientation,
        )
        if members:
            notable_members[f"{CLASS_SLUG_PREFIX}{cls.name}"] = members
    neo_notable = _notable_members(
        session,
        SBDB.neo.is_(True),
        radii=radii,
        units=units,
        wikidata_entities=wikidata_entities,
        orientation=orientation,
    )
    if neo_notable:
        notable_members[f"{SMALL_BODY_FLAG_SLUG_PREFIX}neo"] = neo_notable
    pha_notable = _notable_members(
        session,
        SBDB.pha.is_(True),
        radii=radii,
        units=units,
        wikidata_entities=wikidata_entities,
        orientation=orientation,
    )
    if pha_notable:
        notable_members[f"{SMALL_BODY_FLAG_SLUG_PREFIX}pha"] = pha_notable

    logger.info(
        "Built small-body group stats: %d classes, NEO=%d, PHA=%d, "
        "%d named (asteroid classes only), histograms for %d slugs, "
        "largest body for %d slugs, notable members for %d slugs",
        len(class_counts),
        neo_count,
        pha_count,
        sum(named_counts.values()),
        len(discovery_histograms),
        len(largest_bodies),
        len(notable_members),
    )
    orbit_samples = build_orbit_class_samples(session, class_counts)
    return SmallBodyGroupStats(
        member_counts=member_counts,
        named_counts=named_counts,
        discovery_histograms=discovery_histograms,
        orbit_samples=orbit_samples,
        pha_counts=pha_counts,
        largest_bodies=largest_bodies,
        notable_members=notable_members,
    )


def write_orbit_samples(out_dir: Path, samples: list[OrbitClassSample]) -> None:
    """Write the shared scatter-plot sample file at groups/__orbit_samples__.json.gz.

    Shape: ``{"samples": [...]}``. Per-class real counts live in the existing
    groups __index__.json — no need to duplicate them here.
    """
    payload = {
        "samples": [
            {
                "slug": s.slug,
                "name": s.name,
                "a": s.a,
                "e": s.e,
                "q": s.q,
                "i": s.i,
                "neo": s.neo,
                "pha": s.pha,
            }
            for s in samples
        ],
    }
    path = out_dir / "groups" / "__orbit_samples__.json.gz"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(gzip.compress(orjson.dumps(payload)))
    logger.info(
        "Wrote orbit-class scatter samples: %d points → %s",
        len(samples),
        path.name,
    )
