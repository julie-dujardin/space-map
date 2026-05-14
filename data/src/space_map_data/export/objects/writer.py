"""Build object detail dicts and write them as hash-bucketed JSON files.

Objects are grouped by `hash(id) % N`, with N picked per tier so average
members-per-bundle hits target K: `K_GLOBAL=100` for `__global__`,
`K_LOCALIZED=200` for per-language. Bundle files live at:

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
    merge_operator_qids,
)
from space_map_data.export.objects.sbdb import build_sbdb
from space_map_data.export.quantities import UnitConverter
from space_map_data.export.systems import clouds_block, texture_attribution
from space_map_data.export.objects.wikidata_claims import (
    ENTITY_REF_CLAIMS,
    GLOBAL_CLAIMS,
    extract_claims,
    resolve_entity_ref,
    resolve_unit,
)
from space_map_data.models.object import Object, OrbitalSource
from space_map_data.models.object.sbdb import OrbitClass

logger = logging.getLogger(__name__)

# Target average members per bundle. N = ceil(total / K) is picked at export
# time so per-bundle size stays constant as the DB grows. Frontend reads N
# back from metadata.json to compute bucket ids via `hash(id) % N`.
K_GLOBAL = 100
K_LOCALIZED = 200

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

    Dispatches on ``orbital_source``: horizons/spice rows read from the
    Horizons sub-table (which exposes unified-name properties over its
    native column names); SBDB rows read from the SBDB sub-table directly;
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
    if src in (OrbitalSource.horizons, OrbitalSource.spice):
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
    clouds_meta = clouds_metadata.get(obj.id)
    if clouds_meta is not None:
        data["clouds"] = clouds_block(clouds_meta)
    if obj.has_rings:
        data["has_rings"] = True
    if obj.name is not None:
        data["name"] = obj.name
    if obj.mpc_designation is not None:
        data["sbdb_primary_designation"] = obj.mpc_designation
    if obj.provisional_designation is not None:
        data["provisional_designation"] = obj.provisional_designation

    # Cross-references
    cross_refs = _pick_attrs(obj, _CROSS_REF_FIELDS)
    if cross_refs:
        data["cross_refs"] = cross_refs

    nasa_url = nasa_science_urls.get(obj.id)
    if nasa_url:
        data["nasa_science_url"] = nasa_url

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
        # Keys from GLOBAL_CLAIMS + "temperature" (routed from P2076, not a GlobalClaim)
        wikidata_keys = [c.key for c in GLOBAL_CLAIMS] + ["temperature"]
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
            if claim.key in extracted:
                if claim.multiple:
                    ref = [
                        r
                        for qid in extracted[claim.key]
                        if (r := resolve_entity_ref(qid, lang, wikidata_entities))
                    ]
                else:
                    ref = resolve_entity_ref(
                        extracted[claim.key], lang, wikidata_entities
                    )

                if ref:
                    data[claim.key] = ref

    if obj.norad_cat_id is not None and obj.satcat is not None:
        # SATCAT-derived refs overwrite Wikidata-derived ones (e.g. launch_site)
        # since SATCAT is the authoritative source for satellite metadata.
        data.update(build_satcat_localized(obj.satcat, lang, wikidata_entities))

    if wiki_summary:
        data["wikipedia"] = wiki_summary.to_dict()

    return data
