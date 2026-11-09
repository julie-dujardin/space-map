"""Aggregated `v1/credits.json` for the `/credits` frontend page.

Per-body credits (textures, rings, clouds, skybox) plus the static
ephemeris-archive catalog. Each body's archive id lives in its global JSON
under `ephemeris_source`.
"""

import logging
from collections.abc import Mapping
from pathlib import Path

import orjson
from sqlalchemy.orm import Session

from space_map_data.constants.activity.references import ACTIVITY_SOURCES
from space_map_data.constants.atmosphere.references import (
    ATMOSPHERE_FACT_SOURCES,
    ATMOSPHERE_REFERENCES,
)
from space_map_data.constants.interior.references import INTERIOR_SOURCES
from space_map_data.constants.measured_shapes import MEASURED_SHAPES
from space_map_data.constants.planets.families import NOMINAL_SOLAR_VALUES
from space_map_data.constants.radiation.references import RADIATION_SOURCES
from space_map_data.constants.rings.attribution import RingSource
from space_map_data.constants.rings.catalog import RING_CATALOGS
from space_map_data.constants.rings.references import RING_REFERENCES
from space_map_data.constants.spacecraft import SPACECRAFT_SOURCES
from space_map_data.constants.stars import binaries, literature
from space_map_data.constants.temperature.references import TEMPERATURE_SOURCES
from space_map_data.constants.traverses.references import TRAVERSE_SOURCES
from space_map_data.export.ephemeris import EPHEMERIS_ARCHIVES
from space_map_data.export.names import Names, ObjectNames, by_language
from space_map_data.export.objects.sources import Reference
from space_map_data.export.objects.stars import PLANET_ID
from space_map_data.export.sitemap import planet_page_names
from space_map_data.export.system_groups import (
    load_system_lookup,
    resolve_system_id,
)
from space_map_data.export.systems import (
    TextureLayers,
    load_model_metadata,
    load_ring_metadata,
    load_skybox_metadata,
    texture_attribution,
    tiles_block,
)
from space_map_data.export.wikidata import WikidataEntityCache
from space_map_data.ingest.providers.models.config import (
    MODEL_CATALOGS,
    MODEL_CONTRIBUTOR_PAGES,
)
from space_map_data.models.object import Object
from space_map_data.utils.paths import EXPORT_DIR

logger = logging.getLogger(__name__)


def _sibling_credit_entry(body_id: str, name: str, meta: dict) -> dict:
    """Shape a non-texture credit entry (rings, clouds, …).

    Mirrors a texture entry minus the ``type`` field; the array name does the
    disambiguation, so no synthetic body id like ``naif-699-rings`` is needed.
    """
    entry: dict = {
        "body_id": body_id,
        "name": name,
        "source": meta["source"],
        "organisation": meta["organisation"],
    }
    if meta.get("license") is not None:
        entry["license"] = meta["license"]
    if meta.get("attribution") is not None:
        entry["attribution"] = meta["attribution"]
    if meta.get("artist_impression"):
        entry["artist_impression"] = True
    if meta.get("description") is not None:
        entry["description"] = meta["description"]
    return entry


def _skybox_credit_entry(meta: dict) -> dict:
    """Shape the top-level skybox credit entry from the bundle metadata."""
    entry: dict = {
        "source": meta["source"],
        "organisation": meta["organisation"],
    }
    if meta.get("license") is not None:
        entry["license"] = meta["license"]
    if meta.get("attribution") is not None:
        entry["attribution"] = meta["attribution"]
    if meta.get("description") is not None:
        entry["description"] = meta["description"]
    return entry


def _bibliography_row(ref: Reference) -> dict:
    """A citation as the /credits page lists it. `note` is the object panel's
    abbreviation of `contribution` and has nothing to add next to it."""
    row = ref._asdict()
    row.pop("note", None)
    return row


def _atmosphere_references() -> list[dict]:
    """Render literature first, then the works behind the per-body facts.
    A handful back both (the Galileo helium paper, Huygens' descent) — one
    credit each, keeping the scattering-side contribution line."""
    out = [_bibliography_row(r) for r in ATMOSPHERE_REFERENCES]
    seen = {r["url"] for r in out}
    out.extend(
        _bibliography_row(r)
        for r in ATMOSPHERE_FACT_SOURCES.values()
        if r.url not in seen
    )
    return out


def _orientation_references() -> list[dict]:
    """The papers behind the poles and ellipsoids of the small bodies, which
    name no archive the page could credit instead."""
    out = []
    for shape in MEASURED_SHAPES:
        ref = shape.shape_reference
        out.append({"title": ref.title, "url": ref.url, "contribution": "ellipsoid"})
        if ref := shape.pole_reference:
            out.append(
                {"title": ref.title, "url": ref.url, "contribution": "spin pole"}
            )
    return out


def _star_references() -> list[dict]:
    """The papers behind the hand-curated star values, and the work of the
    Sun's luminosity. `title` is the name a star's page gives the work, so
    the page reads like the catalogue papers."""
    papers = {**literature.REFERENCES, **binaries.REFERENCES}
    return [
        *(
            {"title": ref.short, "url": ref.url, "contribution": ref.title}
            for ref in papers.values()
        ),
        {**NOMINAL_SOLAR_VALUES, "contribution": "nominal solar luminosity"},
    ]


# Shortest list first: a shared work stays in whichever list would most
# notice losing it, so a small bibliography isn't stripped of an entry a
# larger one can spare.
_REFERENCE_SECTIONS = (
    "spacecraft",
    "ring",
    "traverse",
    "temperature",
    "orientation",
    "star",
    "radiation",
    "activity",
    "interior",
    "atmosphere",
)


def _merge_references(sections: dict[str, list[dict]]) -> dict[str, list[dict]]:
    """Collapse the bibliography to one row per work, across every list.

    A work cited in two constants packages (e.g. Huygens' descent, for both
    Titan's pressure and temperature) appears once here, carrying every
    contribution — the page is a bibliography, not a per-topic index.
    """
    kept: dict[str, dict] = {}
    out: dict[str, list[dict]] = {}
    merged: list[str] = []
    for name in _REFERENCE_SECTIONS:
        rows: list[dict] = []
        for row in sections[name]:
            first = kept.get(row["url"])
            if first is None:
                kept[row["url"]] = row
                rows.append(row)
                continue
            if row["contribution"] not in first["contribution"]:
                first["contribution"] += f"; {row['contribution']}"
            merged.append(f"{name}/{row['title']}")
        out[name] = rows
    if merged:
        logger.info(
            "Merged %d duplicate reference row%s into an earlier section: %s",
            len(merged),
            "" if len(merged) == 1 else "s",
            ", ".join(merged),
        )
    return out


def _build_models_credits(model_metadata: dict[str, dict]) -> list[dict]:
    """Emit one entry per 3D-model source catalog that has at least one bundle.

    Per-body model lists aren't worth the noise on the credits page — only the
    catalog license matters. One-off sources (NASA resource pages, Google
    rehosts, …) omit ``catalog`` and credit via the bundle's own metadata.json
    instead of rolling up here.
    """
    matched: set[str] = set()
    for meta in model_metadata.values():
        for tier in (meta.get("exports") or {}).values():
            if not isinstance(tier, dict):
                continue
            name = tier.get("catalog")
            if isinstance(name, str) and name in MODEL_CATALOGS:
                matched.add(name)
    return [
        {"name": name, "url": catalog["url"]}
        | ({"license": catalog["license"]} if catalog.get("license") else {})
        for name, catalog in MODEL_CATALOGS.items()
        if name in matched
    ]


def _contributor(attribution: str) -> str:
    """Name the author without the note on what was changed.

    A model from a hosting site is credited as "author / site, what changed";
    the note differs per model, and one author must share one line.
    """
    author, site, rest = attribution.partition(" / ")
    return author + site + rest.split(", ")[0]


def _build_model_contributors(model_metadata: dict[str, dict]) -> list[dict]:
    """Emit one entry per author of a model that no catalog covers.

    These models come under per-model terms, so the catalog roll-up cannot
    credit them. ``url`` is the source page of an author with one, else the
    author's own page from ``MODEL_CONTRIBUTOR_PAGES``.
    """
    urls: dict[str, set[str]] = {}
    licenses: dict[str, set[str]] = {}
    for meta in model_metadata.values():
        for tier in (meta.get("exports") or {}).values():
            if not isinstance(tier, dict) or tier.get("catalog") in MODEL_CATALOGS:
                continue
            credit = tier.get("credit") or {}
            if not isinstance(credit.get("name"), str):
                continue
            name = _contributor(credit["name"])
            urls.setdefault(name, set()).update(filter(None, [credit.get("url")]))
            licenses.setdefault(name, set()).update(
                filter(None, [credit.get("license")])
            )
    out: list[dict] = []
    for name in sorted(urls, key=str.casefold):
        url = (
            next(iter(urls[name]))
            if len(urls[name]) == 1
            else MODEL_CONTRIBUTOR_PAGES.get(name)
        )
        if url is None:
            logger.warning(
                "Model author %r has %d source pages and no entry in "
                "MODEL_CONTRIBUTOR_PAGES; credited without a link",
                name,
                len(urls[name]),
            )
        out.append(
            {"name": name}
            | ({"url": url} if url else {})
            | {"licenses": sorted(licenses[name])}
        )
    return out


# Appended once to a merged attribution when any contributing bundle rebuilt
# its profiles from the work's tabulated numbers rather than shipping the
# work's own measurements.
_SYNTHESISED_NOTE = (
    " The radial profiles here are reconstructed from those numbers for "
    "rendering, not measured photometry."
)


def _catalog_source(source: RingSource) -> dict:
    """A catalogue citation in the shape the bundle metadata uses (`source`,
    not `url`), so both feed one merge."""
    row = source._asdict()
    row["source"] = row.pop("url")
    return row


def _merge_ring_sources(body_id: str, name: str, metas: list[dict]) -> list[dict]:
    """Collapse a body's ring bundles into one credit row per cited work.

    A body's bundles routinely cite the same work for different things (e.g.
    Saturn's D-ring, main-ring and outer bundles all draw on one fact sheet),
    so rows are merged by (url, organisation) with contributions joined.
    """
    merged: dict[tuple[str, str], dict] = {}
    contributions: dict[tuple[str, str], list[str]] = {}
    synthesised: set[tuple[str, str]] = set()
    for meta in metas:
        for src in meta["sources"]:
            key = (src["source"], src["organisation"])
            merged.setdefault(
                key,
                {
                    "body_id": body_id,
                    "name": name,
                    "source": src["source"],
                    "organisation": src["organisation"],
                    **({"license": src["license"]} if src.get("license") else {}),
                    "work": src["work"],
                },
            )
            parts = contributions.setdefault(key, [])
            if src["contribution"] not in parts:
                parts.append(src["contribution"])
            if src.get("synthesised"):
                synthesised.add(key)

    out: list[dict] = []
    for key, entry in merged.items():
        entry["attribution"] = (
            f"{entry.pop('work')}: {'; '.join(contributions[key])}."
            + (_SYNTHESISED_NOTE if key in synthesised else "")
        )
        out.append(entry)
    return out


# The credited layers of a body, in the order of the page.
_CREDITED_LAYERS = ("textures", *TextureLayers.SIBLINGS)


def _layer_entry(layer: str, body_id: str, name: str, meta: dict) -> dict:
    """The credit of one map of a body."""
    if layer == "textures":
        return {"body_id": body_id, "name": name, **texture_attribution(meta)}
    entry = _sibling_credit_entry(body_id, name, meta)
    if layer == "displacement" and meta.get("tiles") is not None:
        entry["tiles"] = tiles_block(meta["tiles"])
    return entry


def _place_planet(
    planet_id: str,
    host_id: str,
    pages: Mapping[str, Names | None],
    named: dict[str, Names],
) -> tuple[str, str] | None:
    """The name of an exoplanet with a map and its host's page id, which is
    the bucket of its credits. Adds both names to ``named``. None for a planet
    with no page. A page with no name takes a name that exists: the planet
    page's, else the page id."""
    if planet_id not in pages:
        logger.warning(
            "Texture metadata for %s is of no served planet; skipping", planet_id
        )
        return None
    planet = pages[planet_id]
    if planet is None:
        logger.warning("Planet page %s has no name; credited by its id", planet_id)
        planet = Names(planet_id)
    if host_id not in named:
        host = pages.get(host_id)
        if host is None:
            logger.warning(
                "Host page %s has no name; its credits take the name of %s",
                host_id,
                planet_id,
            )
            host = planet
        named[host_id] = host
    named[planet_id] = planet
    return planet.name, host_id


def write_credits(
    session: Session,
    names: ObjectNames,
    out_dir: Path,
    layers: TextureLayers,
    planet_pages: Mapping[str, Names | None],
    ring_metadata: dict[str, list[dict]],
    skybox_metadata: dict | None,
    model_metadata: dict[str, dict],
) -> None:
    """Emit `v1/credits.json` summarising every credit-worthy data source.

    Groups bodies by host planetary system so the frontend renders sections
    instead of a flat list. The exoplanets with a map follow, one section per
    host star (`x-<host>`), and a final null-id group collects standalones
    (sun-orbiting asteroids and dwarf planets). The skybox has no host body,
    so it rides at the top level alongside `systems`. The entries have the
    English names of the pages (`export.names`, and ``planet_pages`` for the
    exoplanets and their hosts, None for a page with no name), and `names`
    holds the other languages.
    """
    # Model metadata is keyed by slug, not object_id, so it's excluded from
    # the body_ids set (it would just produce empty rows on the DB lookup).
    body_ids = {
        body_id
        for body_id in layers.body_ids().union(ring_metadata, RING_CATALOGS)
        if not PLANET_ID.match(body_id)
    }
    objects = session.query(Object).filter(Object.id.in_(body_ids)).all()
    by_id = {obj.id: obj for obj in objects}
    named: dict[str, Names] = {obj.id: names.of(obj) for obj in objects}

    bary_by_id, child_to_bary, system_name_by_id, system_order_by_id = (
        load_system_lookup(session, names)
    )

    planets: dict[str, tuple[str, str] | None] = {}

    def placed(body_id: str, kind: str) -> tuple[str, str | None] | None:
        """The name of a body and the id of its bucket: its system, or the
        host page of an exoplanet. None for a body that is not shown."""
        if (match := PLANET_ID.match(body_id)) is not None:
            if body_id not in planets:
                planets[body_id] = _place_planet(
                    body_id, match["host_id"], planet_pages, named
                )
            return planets[body_id]
        obj = by_id.get(body_id)
        if obj is None:
            logger.warning(
                "%s metadata for %s has no matching Object row; skipping",
                kind,
                body_id,
            )
            return None
        return named[body_id].name, resolve_system_id(obj, bary_by_id, child_to_bary)

    # By layer, then by bucket id.
    grouped: dict[str, dict[str | None, list[dict]]] = {
        layer: {} for layer in ("textures", "rings", *TextureLayers.SIBLINGS)
    }
    for layer in _CREDITED_LAYERS:
        # Sorted, so that a host page with no name takes the same name each run.
        for body_id, meta in sorted(getattr(layers, layer).items()):
            if (found := placed(body_id, layer.capitalize())) is not None:
                name, bucket_id = found
                grouped[layer].setdefault(bucket_id, []).append(
                    _layer_entry(layer, body_id, name, meta)
                )

    # A body may appear here for its render bundles, its catalogue, or both:
    # Saturn's Phoebe ring is catalogued and never drawn.
    for body_id in sorted(set(ring_metadata) | set(RING_CATALOGS)):
        metas = ring_metadata.get(body_id, [])
        if catalog := RING_CATALOGS.get(body_id):
            metas = [
                *metas,
                {"sources": [_catalog_source(s) for s in catalog.sources]},
            ]
        if (found := placed(body_id, "Ring")) is not None:
            name, bucket_id = found
            grouped["rings"].setdefault(bucket_id, []).extend(
                _merge_ring_sources(body_id, name, metas)
            )

    for by_bucket in grouped.values():
        for entries in by_bucket.values():
            entries.sort(key=lambda e: e["name"].lower())

    def bucket(bucket_id: str | None, name: str | None) -> dict:
        out: dict = {"id": bucket_id, "name": name}
        for layer, by_bucket in grouped.items():
            if bucket_id in by_bucket:
                out[layer] = by_bucket[bucket_id]
        return out

    # Systems first, in Mercury → Pluto order; the exoplanets by host name,
    # then the standalones last.
    bucket_ids: set[str | None] = set().union(*grouped.values())
    hosts = {found[1] for found in planets.values() if found is not None}
    systems_out: list[dict] = []
    for sys_id in sorted(
        (s for s in bucket_ids - hosts if s is not None),
        key=lambda s: system_order_by_id.get(s, 9999),
    ):
        named[sys_id] = system_name_by_id[sys_id]
        systems_out.append(bucket(sys_id, named[sys_id].name))
    for host_id in sorted(hosts, key=lambda h: named[h].name.lower()):
        systems_out.append(bucket(host_id, named[host_id].name))
    if None in bucket_ids:
        systems_out.append(bucket(None, None))

    models_out = _build_models_credits(model_metadata)
    model_contributors_out = _build_model_contributors(model_metadata)

    # Each list is the whole bibliography behind one constants package; the
    # per-body panels credit only the works their own numbers come from.
    references = _merge_references(
        {
            "atmosphere": _atmosphere_references(),
            "spacecraft": [_bibliography_row(r) for r in SPACECRAFT_SOURCES.values()],
            "ring": [r._asdict() for r in RING_REFERENCES],
            "activity": [_bibliography_row(r) for r in ACTIVITY_SOURCES.values()],
            "interior": [_bibliography_row(r) for r in INTERIOR_SOURCES.values()],
            "temperature": [_bibliography_row(r) for r in TEMPERATURE_SOURCES.values()],
            "radiation": [_bibliography_row(r) for r in RADIATION_SOURCES.values()],
            "traverse": [_bibliography_row(r) for r in TRAVERSE_SOURCES.values()],
            "orientation": _orientation_references(),
            "star": _star_references(),
        }
    )

    payload: dict = {
        "systems": systems_out,
        "names": by_language(named),
        "ephemeris_archives": EPHEMERIS_ARCHIVES,
        "atmosphere_references": references["atmosphere"],
        "spacecraft_references": references["spacecraft"],
        "ring_references": references["ring"],
        "temperature_references": references["temperature"],
        "interior_references": references["interior"],
        "activity_references": references["activity"],
        "radiation_references": references["radiation"],
        "traverse_references": references["traverse"],
        "orientation_references": references["orientation"],
        "star_references": references["star"],
    }
    if models_out:
        payload["models"] = models_out
    if model_contributors_out:
        payload["model_contributors"] = model_contributors_out
    if skybox_metadata is not None:
        payload["skybox"] = _skybox_credit_entry(skybox_metadata)
    (out_dir / "credits.json").write_bytes(
        orjson.dumps(payload, option=orjson.OPT_INDENT_2)
    )
    counts = {
        layer: sum(len(bucket.get(layer, [])) for bucket in systems_out)
        for layer in grouped
    }
    logger.info(
        "Wrote credits.json (%d systems, %d textured / %d ringed / %d clouded / %d night-lit / %d glowing / %d topo bodies, %d model source%s%s)",
        len(systems_out),
        counts["textures"],
        counts["rings"],
        counts["clouds"],
        counts["night"],
        counts["glow"],
        counts["displacement"],
        len(models_out),
        "" if len(models_out) == 1 else "s",
        ", + skybox" if skybox_metadata is not None else "",
    )


def export_credits_only(engine) -> None:
    """`space-map-export --only credits` — rewrites credits.json alone.

    The file restates what the bundles and the reference constants already
    say, so a credit edit reaches the page without re-running the whole export.
    """
    out_dir = EXPORT_DIR / "v1"
    layers = TextureLayers.load(out_dir)
    hosts = {
        int(match["host"])
        for body_id in layers.body_ids()
        if (match := PLANET_ID.match(body_id)) is not None
    }
    with Session(engine) as session:
        write_credits(
            session,
            ObjectNames(WikidataEntityCache(), session),
            out_dir,
            layers,
            planet_page_names(hosts),
            load_ring_metadata(out_dir),
            load_skybox_metadata(out_dir),
            load_model_metadata(out_dir),
        )
