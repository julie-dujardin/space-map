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

from space_map_data.constants.earth_sats.operators import OPERATOR_BY_CONSTELLATION
from space_map_data.constants.providers import LANGUAGES
from space_map_data.export.groups.registry import GROUPS, Group, GroupType
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


def _build_global(
    group: Group,
    member_count: int,
    extracted: dict | None,
    earliest_launch: str | None,
    image_url: str | None,
    thumbnail_url: str | None,
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
    if earliest_launch:
        data["earliest_launch"] = earliest_launch
    if extracted:
        websites = extracted.get("website")
        if websites:
            data["website"] = websites[0]
    if image_url or thumbnail_url:
        data["image"] = {
            k: v
            for k, v in {"url": image_url, "thumbnail_url": thumbnail_url}.items()
            if v
        }
    return data


def _build_localized(
    group: Group,
    lang: str,
    wikidata_entities: WikidataEntityCache,
    wiki_summaries: dict[str, WikipediaSummary],
    extracted: dict | None,
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
    return data


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
    earliest_launches: dict[str, str] | None = None,
) -> dict[str, int]:
    """Write groups/__global__/ + groups/{lang}/ bundles and __index__.json.

    Returns ``{global: N, lang: N, ...}`` for publication in metadata.json.
    """
    earliest_launches = earliest_launches or {}
    global_by_slug: dict[str, dict] = {}
    localized_by_slug: dict[str, dict[str, dict]] = {lang: {} for lang in LANGUAGES}

    for group in GROUPS:
        wiki_summaries = (
            load_wikipedia_summaries_for_qid(group.wikidata_qid)
            if group.wikidata_qid
            else {}
        )
        extracted = _extract_group_claims(group, wikidata_entities)
        # Prefer the English thumbnail/original; fall back to anything we have.
        en_summary = wiki_summaries.get("en")
        fallback = next(iter(wiki_summaries.values()), None)
        image_url = (en_summary.image_url if en_summary else None) or (
            fallback.image_url if fallback else None
        )
        thumbnail_url = (en_summary.thumbnail_url if en_summary else None) or (
            fallback.thumbnail_url if fallback else None
        )
        global_by_slug[group.slug] = _build_global(
            group,
            member_counts.get(group.slug, 0),
            extracted,
            earliest_launches.get(group.slug),
            image_url,
            thumbnail_url,
        )
        for lang in LANGUAGES:
            lang_data = _build_localized(
                group, lang, wikidata_entities, wiki_summaries, extracted
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
