"""Build object detail dicts and write them as hash-bucketed JSON files.

Objects are grouped by `hash(id) % N`, with N picked per tier so average
members-per-bundle hits target K. K is sized so each bundle compresses to
~200 KiB, which keeps the per-deploy manifest small enough for the
Cloudflare Workers Assets upload API to process within its gateway
timeout. Bundle files live at:

  objects/__global__/{bucket}.json.gz
  objects/{lang}/{bucket}.json.gz

Each bundle file is a gzipped JSON object keyed by object id. The final N
values are published in `metadata.json` under `object_bundles` so the
frontend can reconstruct URLs from an id alone (needed for deep links).
"""

import gzip
import hashlib
import math
import orjson
import logging
from pathlib import Path

from space_map_data.constants.providers import LANGUAGES
from space_map_data.export.ephemeris import ephemeris_archive_for
from space_map_data.export.wikidata import (
    WikidataEntity,
    WikidataEntityCache,
    active_statements,
)
from space_map_data.export.objects.wikipedia import (
    WikipediaSummary,
    load_wikipedia_summaries_for_qid,
)
from space_map_data.export.images import collect_object_images
from space_map_data.export.objects.celestrak import (
    build_satcat_global,
    build_satcat_localized,
    covered_authoritative_qids,
    merge_operator_qids,
)
from space_map_data.export.objects.atmosphere import atmosphere_block
from space_map_data.export.objects.interior import interior_block
from space_map_data.export.objects.rings import (
    ring_feature_localized,
    ring_features_block,
    ring_hero_image,
    ring_sources_block,
    ring_system_localized,
)
from space_map_data.export.objects.temperature import (
    heliocentric_distance_au,
    temperature_block,
)
from space_map_data.export.objects.sbdb import build_sbdb
from space_map_data.export.small_body_color import resolve_moon_color
from space_map_data.export.quantities import UnitConverter
from space_map_data.export.systems import (
    clouds_block,
    displacement_block,
    texture_attribution,
)
from space_map_data.export.objects.wikidata_claims import (
    ENTITY_REF_CLAIMS,
    GLOBAL_CLAIMS,
    attach_country_group_link,
    attach_launch_vehicle_group_link,
    drop_covered_qids,
    extract_claims,
    resolve_entity_ref,
    resolve_unit,
)
from space_map_data.models.object import (
    ModelProvenance,
    Object,
    ObjectType,
    OrbitalSource,
)
from space_map_data.models.object.sbdb import OrbitClass

logger = logging.getLogger(__name__)

# Target average members per bundle. N = ceil(total / K) is picked at export
# time so per-bundle size stays constant as the DB grows. Frontend reads N
# back from metadata.json to compute bucket ids via `hash(id) % N`.
K_GLOBAL = 1100
K_LOCALIZED = 5500

_QID_CURRENCY = "Q8142"


def hash_bucket(obj_id: str, n_buckets: int) -> int:
    """Deterministic bucket from object id. Must mirror the frontend impl.

    Takes the first 4 bytes of sha256(id) as a big-endian uint32, then mods
    by n_buckets. sha256 is overkill for hash distribution but makes the JS
    port trivial via SubtleCrypto.
    """
    return (
        int.from_bytes(hashlib.sha256(obj_id.encode()).digest()[:4], "big") % n_buckets
    )


def _iso_currency_code(
    unit_qid: str, wikidata_entities: WikidataEntityCache
) -> str | None:
    """Return the ISO 4217 code if *unit_qid* is a currency, else None."""
    entity = wikidata_entities.get_referenced(unit_qid)
    if not entity:
        return None
    p31_qids = {
        stmt.get("mainsnak", {}).get("datavalue", {}).get("value", {}).get("id")
        for stmt in active_statements(entity["claims"], "P31")
    }
    if _QID_CURRENCY not in p31_qids:
        return None
    for stmt in active_statements(entity["claims"], "P498"):
        dv = stmt.get("mainsnak", {}).get("datavalue", {}).get("value")
        if isinstance(dv, str):
            return dv
    return None


_CROSS_REF_FIELDS = (
    "wikidata_qid",
    "naif_id",
    "spkid",
    "mpc_designation",
    "norad_cat_id",
    "cospar_id",
)

_ORBIT_FIELDS = ("epoch_jd", "a", "e", "i", "om", "w", "ma", "n")
_SGP4_CELESTRAK_FIELDS = (
    "BSTAR",
    "MEAN_MOTION_DOT",
    "MEAN_MOTION_DDOT",
    "ELEMENT_SET_NO",
    "REV_AT_EPOCH",
)
# Only earth-orbiting objects have CelesTrak rows (the earth zone query
# eager-loads the relationship). Gating access on `parent_id == "naif-399"`
# avoids a cross-thread lazy load when iterating non-earth-orbiting
# spacecraft (which have no CelesTrak data).
_EARTH_OBJECT_ID = "naif-399"


def _pick_attrs(obj: object, attrs: tuple[str, ...]) -> dict:
    """Extract non-None attributes from an object into a dict."""
    data: dict = {}
    for attr in attrs:
        val = getattr(obj, attr)
        if val is not None:
            data[attr] = val
    return data


_AU_KM = 149_597_870.7


def _orbit_elements(obj: Object, attrs: tuple[str, ...]) -> dict:
    """Pick unified-name kepler elements from the right sub-table.

    Dispatches on ``orbital_source``: spice rows read from the Horizons
    sub-table (which exposes unified-name properties over its native column
    names — table name is historical); SBDB rows read from the SBDB sub-table directly;
    celestrak rows read from the transient ``_daily_kepler`` overlay attached
    by the Earth-zone overlay (celestrak doesn't persist these). SBDB
    satellites store ``a`` natively in km (``a_km``); we convert to AU on
    read so the bundle ships the same units the position writer does.
    Returns an empty dict when the relevant source isn't available — same
    behaviour as the previous main-table read.
    """
    src = obj.orbital_source
    if src == OrbitalSource.celestrak:
        daily = getattr(obj, "_daily_kepler", None)
        if daily is None:
            return {}
        return {a: daily[a] for a in attrs if daily.get(a) is not None}
    if src == OrbitalSource.sbdb:
        return _pick_attrs(obj.sbdb, attrs) if obj.sbdb is not None else {}
    if src == OrbitalSource.sbdb_moon:
        if obj.sbdb_moon is None:
            return {}
        out: dict = {}
        for attr in attrs:
            if attr == "a":
                a_km = obj.sbdb_moon.a_km
                if a_km is not None:
                    out["a"] = a_km / _AU_KM
                continue
            val = getattr(obj.sbdb_moon, attr, None)
            if val is not None:
                out[attr] = val
        return out
    if src == OrbitalSource.spice:
        return _pick_attrs(obj.horizons, attrs) if obj.horizons is not None else {}
    return {}


class ChunkObjectData:
    """Per-object JSON dicts built for one chunk, ready to be bundled.

    `global_data[obj_id]` is always populated. `localized_data[lang][obj_id]`
    is only populated when the object has content in that language (absent
    when the frontend should skip the localized fetch entirely).
    `has_localized[obj_id]` is True when at least one language has data —
    the frontend gates its localized-bundle fetch on this single bit (also
    shipped per-row in the binary chunk).
    """

    __slots__ = ("global_data", "localized_data", "has_localized")

    def __init__(self):
        self.global_data: dict[str, dict] = {}
        self.localized_data: dict[str, dict[str, dict]] = {
            lang: {} for lang in LANGUAGES
        }
        self.has_localized: dict[str, bool] = {}


def build_chunk_object_data(
    objects: list[Object],
    wikidata_entities: WikidataEntityCache,
    chunk_entities: dict[str, WikidataEntity | None],
    units: UnitConverter,
    nasa_science_urls: dict[str, str],
    orientation: dict[int, dict],
    radii: dict[int, dict],
    gms: dict[int, float],
    nut_prec: dict[int, dict[str, list[float]]],
    texture_metadata: dict[str, dict],
    clouds_metadata: dict[str, dict],
    displacement_metadata: dict[str, dict],
    model_sources: dict[str, dict],
    probe_kernel_sources: dict[int, str | None],
    nomenclature_body_ids: set[str],
    parent_names: dict[str, str],
    taxonomy: dict,
    ring_moon_ids: dict[str, str],
) -> ChunkObjectData:
    """Build per-object global and localized JSON dicts (no I/O).

    `has_localized[obj_id]` is True iff at least one language ended up with
    a non-empty localized entry. The frontend uses this bit (shipped in the
    binary chunk) to gate its localized-bundle fetch on click.
    """
    out = ChunkObjectData()

    for obj in objects:
        qid = obj.wikidata_qid or (
            obj.satcat.wikidata_qid
            if obj.norad_cat_id is not None and obj.satcat
            else None
        )
        wd = chunk_entities.get(qid) if qid else None
        try:
            extracted = (
                extract_claims(
                    wd["claims"], qid=qid, wikidata_entities=wikidata_entities
                )
                if qid and wd
                else {}
            )
        except Exception as exc:
            logger.error("Error extracting claims for %s (%s): %s", obj.id, qid, exc)
            extracted = {}

        sat = obj.satcat if obj.norad_cat_id is not None else None
        drop_covered_qids(extracted, covered_authoritative_qids(sat), obj.id)
        merge_operator_qids(extracted, sat)

        out.global_data[obj.id] = _build_global(
            obj,
            extracted,
            wikidata_entities,
            units,
            nasa_science_urls,
            orientation,
            radii,
            gms,
            nut_prec,
            texture_metadata,
            clouds_metadata,
            displacement_metadata,
            model_sources,
            probe_kernel_sources,
            nomenclature_body_ids,
            parent_names,
            taxonomy,
            ring_moon_ids,
        )

        wiki_summaries = load_wikipedia_summaries_for_qid(qid) if qid else {}

        any_localized = False
        for lang in LANGUAGES:
            wiki_summary = wiki_summaries.get(lang)
            lang_data = _build_localized(
                obj, lang, wikidata_entities, wd, extracted, wiki_summary
            )
            if lang_data:
                out.localized_data[lang][obj.id] = lang_data
                any_localized = True
        out.has_localized[obj.id] = any_localized

    return out


def write_object_bundles(
    out_dir: Path,
    global_data: dict[str, dict],
    localized_data: dict[str, dict[str, dict]],
) -> dict[str, int]:
    """Hash-bucket per-object dicts and write one gzipped JSON per bucket.

    Returns `{"global": N_global, lang: N_lang, ...}` for publication in
    metadata.json so the frontend can reproduce the bucket math from an id.
    A tier with zero entries gets N=0 and no directory.
    """
    bundle_ns: dict[str, int] = {}

    n_global = max(1, math.ceil(len(global_data) / K_GLOBAL)) if global_data else 0
    bundle_ns["global"] = n_global
    if n_global:
        _write_hashed_bundles(out_dir / "objects" / "__global__", global_data, n_global)

    for lang in LANGUAGES:
        by_id = localized_data.get(lang, {})
        n_lang = max(1, math.ceil(len(by_id) / K_LOCALIZED)) if by_id else 0
        bundle_ns[lang] = n_lang
        if n_lang:
            _write_hashed_bundles(out_dir / "objects" / lang, by_id, n_lang)

    logger.info(
        "Wrote object bundles: global N=%d (%d objects), langs: %s",
        n_global,
        len(global_data),
        ", ".join(
            f"{lang}={bundle_ns[lang]}({len(localized_data.get(lang, {}))})"
            for lang in LANGUAGES
        ),
    )
    return bundle_ns


def _write_hashed_bundles(
    dir_path: Path, by_id: dict[str, dict], n_buckets: int
) -> None:
    """Group by `hash(id) % n_buckets` and write one gzipped JSON per bucket."""
    buckets: dict[int, dict[str, dict]] = {}
    for obj_id, data in by_id.items():
        buckets.setdefault(hash_bucket(obj_id, n_buckets), {})[obj_id] = data
    dir_path.mkdir(parents=True, exist_ok=True)
    for bucket, entries in buckets.items():
        (dir_path / f"{bucket}.json.gz").write_bytes(
            gzip.compress(orjson.dumps(entries))
        )


_IMAGE_KEYS = {"image", "logo_image"}

# Readings inside a `temperatures` entry, normalized to canonical kelvin so
# every body plots on one scale regardless of the source unit.
_TEMPERATURE_READINGS = ("min", "mean", "max")


def render_quality(obj: Object, radii: dict[int, dict]) -> str | None:
    """Best-available-asset render tier for an object.

    high   — faithful 3D model (spacecraft / mission / radar), a map texture,
             or a procedural star surface
    medium — lightcurve-inversion convex hull only
    low    — size only: sphere/ellipsoid from PCK radii or SBDB diameter
    None   — no physical extent known; renders as halo/point at best
    """
    has_model = obj.model_name is not None
    if has_model and obj.model_provenance != ModelProvenance.lightcurve:
        return "high"
    if obj.map_texture_available:
        return "high"
    # Stars ship no texture asset — the frontend's star-surface shader is a
    # faithful surface, not a size-only sphere.
    if obj.object_type == ObjectType.star:
        return "high"
    if has_model:
        return "medium"
    if obj.naif_id is not None and obj.naif_id in radii:
        return "low"
    # FK guard before the relationship read — writer runs in worker threads.
    sbdb = obj.sbdb if obj.spkid is not None else None
    if sbdb is not None and sbdb.diameter is not None:
        return "low"
    return None


def build_model_sources(
    model_metadata: dict[str, dict],
    probe_names: dict[int, str],
) -> dict[str, dict]:
    """Map shape-model slug → compact provenance block for the detail drawer.

    Denormalized from the per-slug bundles so the sources section can name the
    model's technique (mission/radar/lightcurve), credit its archive, and — for
    mission shapes — link to the observing spacecraft. Keyed by slug to match
    the ``model_name`` the object actually references; spacecraft bundles
    (``kind != shape_model``) are excluded — natural bodies only.
    """
    out: dict[str, dict] = {}
    for slug, meta in model_metadata.items():
        if meta.get("kind") != "shape_model":
            continue
        block: dict = {"provenance": meta.get("provenance")}
        if meta.get("archive"):
            block["archive"] = meta["archive"]
        if meta.get("archive_url"):
            block["archive_url"] = meta["archive_url"]
        probe_id = meta.get("probe_id")
        if probe_id is not None:
            name = probe_names.get(int(probe_id))
            if name:
                block["mission"] = {
                    "name": name,
                    "primary_type": "object",
                    "primary_id": f"probe-{int(probe_id)}",
                }
            else:
                logger.warning(
                    "model %s: probe_id %s absent from registry — no mission link",
                    slug,
                    probe_id,
                )
        out[slug] = block
    return out


def _wikidata_readings(
    extracted: dict, units: UnitConverter, obj_id: str
) -> list[dict]:
    """Flatten Wikidata's temperature claims to kelvin readings.

    Kelvin because the frontend positions readings on a shared scale, and only
    a ratio scale survives the log segment used for stellar temperatures.
    """
    result = []
    for entry in extracted.get("temperatures", []):
        for reading in _TEMPERATURE_READINGS:
            val = entry.get(reading)
            if val is None:
                continue
            kelvin = units.convert_temperature(float(val["value"]), val["unit"])
            if kelvin is None:
                logger.warning(
                    "Dropping %s %s temperature on %s: unknown unit %s",
                    entry["part"],
                    reading,
                    obj_id,
                    val["unit"],
                )
                continue
            result.append(
                {
                    "part": entry["part"],
                    "kind": reading,
                    "k": kelvin["value"],
                }
            )
    return result


def _build_global(
    obj: Object,
    extracted: dict,
    wikidata_entities: WikidataEntityCache,
    units: UnitConverter,
    nasa_science_urls: dict[str, str],
    orientation: dict[int, dict],
    radii: dict[int, dict],
    gms: dict[int, float],
    nut_prec: dict[int, dict[str, list[float]]],
    texture_metadata: dict[str, dict],
    clouds_metadata: dict[str, dict],
    displacement_metadata: dict[str, dict],
    model_sources: dict[str, dict],
    probe_kernel_sources: dict[int, str | None],
    nomenclature_body_ids: set[str],
    parent_names: dict[str, str],
    taxonomy: dict,
    ring_moon_ids: dict[str, str],
) -> dict:
    """Build the language-independent JSON dict for an object."""
    data: dict = {
        "id": obj.id,
        "type": obj.object_type,
    }
    if obj.map_texture_available:
        data["map_texture_available"] = True
        meta = texture_metadata.get(obj.id)
        if meta is not None:
            data["texture"] = texture_attribution(meta)
        else:
            logger.warning(
                "Texture metadata missing for %s; skipping attribution", obj.id
            )
    if obj.model_name is not None:
        data["model_name"] = obj.model_name
        model_source = model_sources.get(obj.model_name)
        if model_source:
            data["model_source"] = model_source
    quality = render_quality(obj, radii)
    if quality is not None:
        data["render_quality"] = quality
    clouds_meta = clouds_metadata.get(obj.id)
    if clouds_meta is not None:
        data["clouds"] = clouds_block(clouds_meta)
    disp_meta = displacement_metadata.get(obj.id)
    if disp_meta is not None:
        data["displacement"] = displacement_block(disp_meta)
    if obj.has_rings:
        data["has_rings"] = True
    if obj.id in nomenclature_body_ids:
        data["has_nomenclature"] = True
    if obj.name is not None:
        data["name"] = obj.name
    # Host name for moons — top-level (not in `orbit`) so position-less
    # publication-placeholder moonlets carry it too. Lets the frontend
    # breadcrumb label the parent even when its body isn't resident in the
    # scene (small-body hosts get culled once focus moves on).
    if obj.object_type == ObjectType.moon and obj.parent_id is not None:
        parent_name = parent_names.get(obj.parent_id)
        if parent_name:
            data["parent_name"] = parent_name
    # Physically-derived TCT surface colour for moons (mirrors sbdb.py for small
    # bodies). Drives the flat sphere where no texture loads; absent for moons
    # TCT hasn't measured.
    if obj.object_type == ObjectType.moon:
        color, method = resolve_moon_color(obj.naif_id)
        if color is not None:
            data["color"] = color
            data["color_method"] = method
    if obj.mpc_designation is not None:
        data["sbdb_primary_designation"] = obj.mpc_designation
    if obj.provisional_designation is not None:
        data["provisional_designation"] = obj.provisional_designation

    # Wikidata notability signal — search ranks "show all group members" by it.
    if obj.sitelinks_count:
        data["sitelinks_count"] = obj.sitelinks_count

    if obj.discovery_year is not None:
        data["discovery_year"] = obj.discovery_year

    # Cross-references
    cross_refs = _pick_attrs(obj, _CROSS_REF_FIELDS)
    if cross_refs:
        data["cross_refs"] = cross_refs

    nasa_url = nasa_science_urls.get(obj.id)
    if nasa_url:
        data["nasa_science_url"] = nasa_url

    # Top-level rather than inside `orbit` so probes (which ship no Kepler
    # block) still carry their archive credit.
    archive = ephemeris_archive_for(obj, probe_kernel_sources)
    if archive is not None:
        data["ephemeris_source"] = archive

    # Orbital elements — parabolic comets use q/tp instead of a/ma/n
    sbdb = obj.sbdb if obj.spkid is not None else None
    if sbdb is not None and sbdb.class_ == OrbitClass.PAR:
        orbit = _orbit_elements(obj, ("epoch_jd", "e", "i", "om", "w"))
        if sbdb.q is not None:
            orbit["q"] = sbdb.q
        if sbdb.tp is not None:
            orbit["tp"] = sbdb.tp
    else:
        orbit = _orbit_elements(obj, _ORBIT_FIELDS)
    if orbit:
        orbit["scale"] = obj.scale
        if obj.parent_id is not None:
            orbit["parent_id"] = obj.parent_id
        if obj.orbital_source is not None:
            orbit["source"] = obj.orbital_source
        # SGP4 init fields for CelesTrak-sourced earth sats — the frontend uses
        # these to build a satellite.js satrec at load time, avoiding a Kepler
        # fallback while the element chunk is still in flight.
        if (
            obj.parent_id == _EARTH_OBJECT_ID
            and obj.norad_cat_id is not None
            and obj.celestrak is not None
        ):
            for attr in _SGP4_CELESTRAK_FIELDS:
                val = getattr(obj.celestrak, attr)
                if val is not None:
                    orbit[attr.lower()] = val
        data["orbit"] = orbit

    # Orientation data (from SPICE PCK)
    if obj.naif_id is not None and obj.naif_id in orientation:
        data["orientation"] = orientation[obj.naif_id]

    # Nutation/precession coefficients (paired with global nut_prec_angles.json)
    if obj.naif_id is not None and obj.naif_id in nut_prec:
        data["nut_prec"] = nut_prec[obj.naif_id]

    # Triaxial radii (km, along body-fixed X, Y, Z) from SPICE PCK
    if obj.naif_id is not None and obj.naif_id in radii:
        data["radii"] = radii[obj.naif_id]

    # Gravitational parameter (km^3/s^2) from SPICE PCK
    if obj.naif_id is not None and obj.naif_id in gms:
        data["gm"] = gms[obj.naif_id]

    # Cited atmospheric facts — only the two dozen bodies with a measured
    # envelope have one.
    atmosphere = atmosphere_block(obj.id)
    if atmosphere is not None:
        data["atmosphere"] = atmosphere

    # Cited interior facts: a layer model for the bodies a mission reached,
    # a spectral estimate for the asteroids that only have a class.
    interior = interior_block(obj.id, taxonomy)
    if interior is not None:
        data["interior"] = interior

    # Named rings, gaps and ringlets: what the ring system *is*, next to the
    # render bundles in systems/{bary}.json that say what it looks like.
    ring_features = ring_features_block(obj.id, ring_moon_ids)
    if ring_features:
        data["ring_features"] = ring_features
        data["ring_sources"] = ring_sources_block(obj.id)
        hero = ring_hero_image(obj.id)
        if hero:
            data["ring_hero"] = hero

    # SBDB extras
    if sbdb is not None:
        sbdb_data = build_sbdb(sbdb, units)
        if sbdb_data:
            data["sbdb"] = sbdb_data

    # CelesTrak enrichment
    if obj.norad_cat_id is not None and obj.satcat is not None:
        celestrak_data = build_satcat_global(obj.satcat)
        if celestrak_data:
            data["celestrak"] = celestrak_data

    # Images: pre-selected at ingest time (best per derivative tree).
    images = collect_object_images(obj.id)
    if images:
        data["images"] = images

    # Wikidata claims (non-localized, excluding image fields handled above)
    if extracted:
        wikidata_section: dict = {}
        wikidata_keys = [c.key for c in GLOBAL_CLAIMS]
        # SPICE PCK radii supersede the Wikidata radius — skip it when present.
        if "radii" in data:
            wikidata_keys = [k for k in wikidata_keys if k != "radius"]
        for key in wikidata_keys:
            if key in _IMAGE_KEYS:
                continue
            if key in extracted:
                val = extracted[key]
                if isinstance(val, dict) and "unit" in val:
                    iso = _iso_currency_code(val["unit"], wikidata_entities)
                    if iso:
                        val = {"value": val["value"], "currency": iso}
                    else:
                        converted = units.convert(float(val["value"]), val["unit"])
                        if converted is not None:
                            val = converted
                        else:
                            resolved = resolve_unit(val["unit"], wikidata_entities)
                            if resolved:
                                units.used_units.add(resolved)
                                val = {**val, "unit": resolved}
                wikidata_section[key] = val
        if wikidata_section:
            data["wikidata"] = wikidata_section

    # Top-level rather than under `wikidata`: a cited constant or a computed
    # estimate outranks Wikidata here, so most bodies' temperature no longer
    # comes from there at all.
    temperatures = temperature_block(
        obj.id,
        _wikidata_readings(extracted, units, obj.id),
        heliocentric_distance_au(orbit.get("a"), obj.parent_id),
        sbdb.albedo if sbdb else None,
    )
    if temperatures is not None:
        data["temperatures"] = temperatures
        units.used_units.add("kelvin")

    return data


def _build_localized(
    obj: Object,
    lang: str,
    wikidata_entities: WikidataEntityCache,
    wd: WikidataEntity | None,
    extracted: dict,
    wiki_summary: WikipediaSummary | None,
) -> dict:
    """Build the per-language JSON dict for an object."""
    data: dict = {}

    if wd:
        labels = wd["labels"]
        # Match resolve_name's fallback chain (used by the element label file):
        # target lang → English → omit. Falling back to obj.name is skipped here
        # since that's already in the global file — a localized `name` is only
        # meaningful when it's a Wikidata-sourced long form.
        if lang in labels:
            data["name"] = labels[lang]
        elif "en" in labels:
            data["name"] = labels["en"]

        desc = wd["descriptions"].get(lang)
        if desc:
            data["description"] = desc
        aliases = wd["aliases"].get(lang)
        if aliases:
            data["aliases"] = aliases

    if extracted:
        for claim in ENTITY_REF_CLAIMS:
            if claim.key not in extracted:
                continue
            if claim.multiple:
                refs: list[dict] = []
                for qid in extracted[claim.key]:
                    ref = resolve_entity_ref(qid, lang, wikidata_entities)
                    if ref is None:
                        continue
                    attach_country_group_link(ref, qid)
                    attach_launch_vehicle_group_link(ref, qid)
                    refs.append(ref.to_dict())
                if refs:
                    data[claim.key] = refs
            else:
                qid = extracted[claim.key]
                ref = resolve_entity_ref(qid, lang, wikidata_entities)
                if ref:
                    attach_country_group_link(ref, qid)
                    attach_launch_vehicle_group_link(ref, qid)
                    data[claim.key] = ref.to_dict()

    if obj.norad_cat_id is not None and obj.satcat is not None:
        # SATCAT-derived refs overwrite Wikidata-derived ones (e.g. launch_site)
        # since SATCAT is the authoritative source for satellite metadata.
        data.update(build_satcat_localized(obj.satcat, lang, wikidata_entities))

    if wiki_summary:
        data["wikipedia"] = wiki_summary.to_dict()

    # Only the locales with an article for a given ring get an entry; the panel
    # falls back to the global name and PDS note for the rest.
    ring_features = ring_feature_localized(obj.id, lang, wikidata_entities)
    if ring_features:
        data["ring_features"] = ring_features
    ring_system = ring_system_localized(obj.id, lang, wikidata_entities)
    if ring_system:
        data["ring_system"] = ring_system

    return data
