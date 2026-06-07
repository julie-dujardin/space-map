"""Per-group bundle files: __global__ + per-locale, hash-bucketed by slug.

Same bucketing scheme as object bundles (sha256 first-4-bytes-be % N) so
the frontend reuses ``hashBucket``. Bucket counts ship in metadata.json
under ``group_bundles`` for slug→bundle resolution.
"""

import gzip
import logging
import math
from pathlib import Path

import orjson

from space_map_data.constants.earth_sats.constellations import CONSTELLATION_BY_SLUG
from space_map_data.constants.earth_sats.launch_sites import LAUNCH_SITE_BY_CODE
from space_map_data.constants.earth_sats.operators import OPERATOR_BY_CONSTELLATION
from space_map_data.constants.providers import LANGUAGES
from space_map_data.export.groups.membership import GroupSatcatStats
from space_map_data.export.groups.registry import GROUPS, Group, GroupType
from space_map_data.export.images import collect_group_images
from space_map_data.export.objects.wikidata_claims import (
    extract_claims,
    resolve_entity_ref,
)
from space_map_data.export.objects.wikipedia import (
    WikipediaSummary,
    load_wikipedia_summaries_for_qid,
)
from space_map_data.export.objects.writer import hash_bucket
from space_map_data.export.wikidata import WikidataEntityCache

logger = logging.getLogger(__name__)

K_GLOBAL = 100
K_LOCALIZED = 200
_TOP_LAUNCH_SITES = 5


def _build_global(
    group: Group,
    member_count: int,
    extracted: dict | None,
    stats: GroupSatcatStats | None,
    images: list[dict] | None,
) -> dict:
    data: dict = {
        "slug": group.slug,
        "type": str(group.type),
        "applies_to": str(group.applies_to),
        "member_count": member_count,
    }
    if group.wikidata_qid:
        data["wikidata_qid"] = group.wikidata_qid
    if group.fallback_url:
        data["url"] = group.fallback_url
    if group.type is GroupType.CONSTELLATION:
        spec = CONSTELLATION_BY_SLUG.get(group.slug)
        if spec and spec.category:
            data["categories"] = [str(c) for c in spec.category]
    if stats:
        if stats.launch_histogram:
            data["launch_histogram"] = {
                str(year): n for year, n in sorted(stats.launch_histogram.items())
            }
        if stats.first_launch_date:
            data["first_launch_date"] = stats.first_launch_date
        if stats.active:
            data["active_count"] = stats.active
        if stats.decayed:
            data["decayed_count"] = stats.decayed
    if extracted:
        websites = extracted.get("website")
        if websites:
            data["website"] = websites[0]
        if inception := extracted.get("inception"):
            data["inception"] = inception
        if dissolved := extracted.get("dissolved"):
            data["dissolved"] = dissolved
    if images:
        data["images"] = images
    return data


def _build_localized(
    group: Group,
    lang: str,
    wikidata_entities: WikidataEntityCache,
    wiki_summaries: dict[str, WikipediaSummary],
    extracted: dict | None,
    stats: GroupSatcatStats | None,
) -> dict:
    data: dict = {}
    if group.wikidata_qid:
        wd = wikidata_entities.get_referenced(group.wikidata_qid)
        if wd:
            name = wd["labels"].get(lang) or wd["labels"].get("en")
            if name:
                data["name"] = name
            desc = wd["descriptions"].get(lang)
            if desc:
                data["description"] = desc
    summary = wiki_summaries.get(lang)
    if summary:
        data["wikipedia"] = summary.to_dict()
    operators = _operator_refs_for_group(group, lang, wikidata_entities)
    if operators:
        data["operators"] = operators
    if extracted:
        country_qids = extracted.get("country_of_origin")
        if country_qids:
            country_refs = [
                r.to_dict()
                for qid in country_qids
                if (r := resolve_entity_ref(qid, lang, wikidata_entities))
            ]
            if country_refs:
                data["country_of_origin"] = country_refs
        instance_qids = extracted.get("instance_of")
        if instance_qids:
            instance_refs = [
                r.to_dict()
                for qid in instance_qids
                if (r := resolve_entity_ref(qid, lang, wikidata_entities))
            ]
            if instance_refs:
                data["instance_of"] = instance_refs
    if stats and stats.launch_sites:
        sites = _launch_site_refs(stats.launch_sites, lang, wikidata_entities)
        if sites:
            data["launch_sites"] = sites
    return data


def _launch_site_refs(
    counts: dict[str, int],
    lang: str,
    wikidata_entities: WikidataEntityCache,
) -> list[dict]:
    """Top ``_TOP_LAUNCH_SITES`` sites with localized ref + count.

    Unknown codes (not in ``LAUNCH_SITE_BY_CODE``) are dropped; codes
    without a QID fall back to the CelesTrak short name.
    """
    top = sorted(counts.items(), key=lambda kv: kv[1], reverse=True)[:_TOP_LAUNCH_SITES]
    out: list[dict] = []
    for code, n in top:
        spec = LAUNCH_SITE_BY_CODE.get(code)
        if not spec:
            continue
        entry: dict = {"n": n}
        if spec.wikidata_qid:
            ref = resolve_entity_ref(spec.wikidata_qid, lang, wikidata_entities)
            if ref is not None:
                entry.update(ref.to_dict())
        entry.setdefault("name", spec.name)
        out.append(entry)
    return out


def _extract_group_claims(
    group: Group, wikidata_entities: WikidataEntityCache
) -> dict | None:
    """Run the shared object-claim extractor against the group's Wikidata entity.

    We only consume ``website`` (P856) and ``country_of_origin`` (P495) for the
    bundle today, but going through ``extract_claims`` keeps unit/currency
    handling consistent if we surface more fields later.
    """
    if not group.wikidata_qid:
        return None
    wd = wikidata_entities.get_referenced(group.wikidata_qid)
    if not wd:
        return None
    return extract_claims(
        wd["claims"], group.wikidata_qid, wikidata_entities, route_temperature=False
    )


def _operator_refs_for_group(
    group: Group,
    lang: str,
    wikidata_entities: WikidataEntityCache,
) -> list[dict]:
    """Operators sourced from constants (not Wikidata P137) and resolved as
    EntityRefs. Only constellation groups have an operator table entry today."""
    if group.type is not GroupType.CONSTELLATION:
        return []
    operators = OPERATOR_BY_CONSTELLATION.get(group.slug, [])
    refs: list[dict] = []
    for op in operators:
        if op.wikidata_qid:
            ref = resolve_entity_ref(op.wikidata_qid, lang, wikidata_entities)
            if ref is not None:
                refs.append(ref.to_dict())
                continue
        refs.append({"name": op.name})
    return refs


def write_group_bundles(
    out_dir: Path,
    wikidata_entities: WikidataEntityCache,
    member_counts: dict[str, int],
    satcat_stats: dict[str, GroupSatcatStats] | None = None,
) -> dict[str, int]:
    """Write groups/__global__/ + groups/{lang}/ bundles and __index__.json.

    Returns ``{global: N, lang: N, ...}`` for publication in metadata.json.
    """
    satcat_stats = satcat_stats or {}
    global_by_slug: dict[str, dict] = {}
    localized_by_slug: dict[str, dict[str, dict]] = {lang: {} for lang in LANGUAGES}

    for group in GROUPS:
        wiki_summaries = (
            load_wikipedia_summaries_for_qid(group.wikidata_qid)
            if group.wikidata_qid
            else {}
        )
        extracted = _extract_group_claims(group, wikidata_entities)
        images = collect_group_images(group.slug)
        stats = satcat_stats.get(group.slug)
        global_by_slug[group.slug] = _build_global(
            group,
            member_counts.get(group.slug, 0),
            extracted,
            stats,
            images,
        )
        for lang in LANGUAGES:
            lang_data = _build_localized(
                group, lang, wikidata_entities, wiki_summaries, extracted, stats
            )
            if lang_data:
                localized_by_slug[lang][group.slug] = lang_data

    bundle_ns: dict[str, int] = {}
    n_global = (
        max(1, math.ceil(len(global_by_slug) / K_GLOBAL)) if global_by_slug else 0
    )
    bundle_ns["global"] = n_global
    if n_global:
        _write_buckets(out_dir / "groups" / "__global__", global_by_slug, n_global)

    for lang in LANGUAGES:
        by_slug = localized_by_slug[lang]
        n_lang = max(1, math.ceil(len(by_slug) / K_LOCALIZED)) if by_slug else 0
        bundle_ns[lang] = n_lang
        if n_lang:
            _write_buckets(out_dir / "groups" / lang, by_slug, n_lang)

    # __index__.json: small, ungzipped, slug→{type, applies_to, n}. Loaded
    # once to validate /g/<slug> URLs and to render listings without bundle
    # fetches. Member-count "n" lets the chip show "12,062 members" instantly.
    index = {
        slug: {
            "type": data["type"],
            "applies_to": data["applies_to"],
            "n": data["member_count"],
        }
        for slug, data in global_by_slug.items()
    }
    (out_dir / "groups" / "__index__.json").write_bytes(orjson.dumps(index))

    logger.info(
        "Wrote group bundles: %d groups, global N=%d, langs: %s",
        len(global_by_slug),
        n_global,
        ", ".join(
            f"{lang}={bundle_ns[lang]}({len(localized_by_slug[lang])})"
            for lang in LANGUAGES
        ),
    )
    return bundle_ns


def _write_buckets(dir_path: Path, by_slug: dict[str, dict], n: int) -> None:
    buckets: dict[int, dict[str, dict]] = {}
    for slug, data in by_slug.items():
        buckets.setdefault(hash_bucket(slug, n), {})[slug] = data
    dir_path.mkdir(parents=True, exist_ok=True)
    for b, entries in buckets.items():
        (dir_path / f"{b}.json.gz").write_bytes(gzip.compress(orjson.dumps(entries)))
