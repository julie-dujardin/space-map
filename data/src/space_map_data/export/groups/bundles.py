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

from space_map_data.constants.categories import CATEGORY_BY_SLUG
from space_map_data.constants.earth_sats.constellations import (
    CONSTELLATION_BY_SLUG,
    CONSTELLATION_SLUG_PREFIX,
)
from space_map_data.constants.earth_sats.launch_sites import LAUNCH_SITE_BY_CODE
from space_map_data.constants.earth_sats.manufacturers import (
    MANUFACTURER_BY_CONSTELLATION,
)
from space_map_data.constants.earth_sats.operators import OPERATOR_BY_CONSTELLATION
from space_map_data.constants.earth_sats.organizations import (
    ORGANIZATION_BY_SLUG,
    ORGANIZATION_SLUG_PREFIX,
)
from space_map_data.constants.earth_sats.satellite_models import BUS_BY_SLUG
from space_map_data.constants.providers import LANGUAGES
from space_map_data.export.groups.membership import GroupSatcatStats
from space_map_data.export.groups.registry import (
    BUS_SLUG_PREFIX,
    LAUNCH_SITE_SLUG_PREFIX,
    SMALL_BODY_FLAG_SLUG_PREFIX,
    GROUP_BY_SLUG,
    GROUPS,
    Group,
    GroupType,
)
from space_map_data.export.groups.small_body import LargestBody
from space_map_data.export.images import collect_group_images
from space_map_data.export.notable import NotableObject, notable_entries, notable_names
from space_map_data.export.objects.wikidata_claims import (
    attach_country_group_link,
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

K_GLOBAL = 1000
K_LOCALIZED = 600
_TOP_LAUNCH_SITES = 5
_TOP_CONSTELLATIONS = 5


_FLAG_PHA_SLUG = f"{SMALL_BODY_FLAG_SLUG_PREFIX}pha"


def _build_global(
    group: Group,
    member_count: int,
    extracted: dict | None,
    stats: GroupSatcatStats | None,
    discovery_histogram: dict[int, int] | None,
    launch_histogram_override: dict[int, int] | None,
    images: list[dict] | None,
    largest_body: LargestBody | None,
    pha_count: int,
    named_count: int,
    notable_members: list[dict] | None,
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
    if group.type is GroupType.ORGANIZATION:
        org = ORGANIZATION_BY_SLUG.get(
            group.slug.removeprefix(ORGANIZATION_SLUG_PREFIX)
        )
        if org:
            data["roles"] = list(org.roles)
    if group.type is GroupType.CONSTELLATION:
        spec = CONSTELLATION_BY_SLUG.get(
            group.slug.removeprefix(CONSTELLATION_SLUG_PREFIX)
        )
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
    # Categories carry no GroupSatcatStats; their satellite launch chart comes
    # in via the override instead of the per-group stats above.
    if "launch_histogram" not in data and launch_histogram_override:
        data["launch_histogram"] = {
            str(year): n for year, n in sorted(launch_histogram_override.items())
        }
    if discovery_histogram:
        data["discovery_histogram"] = {
            str(year): n for year, n in sorted(discovery_histogram.items())
        }
    if largest_body is not None:
        data["largest_body"] = {
            "name": largest_body.name,
            "diameter_km": largest_body.diameter_km,
            "primary_type": "spkid",
            "primary_id": largest_body.spkid,
        }
    # Only asteroid classes + the Asteroids category carry a named count.
    if named_count:
        data["named_count"] = named_count
    if pha_count and group.slug != _FLAG_PHA_SLUG:
        data["pha"] = {
            "n": pha_count,
            "primary_type": "group",
            "primary_id": _FLAG_PHA_SLUG,
        }
    if notable_members:
        data["notable_members"] = notable_members
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
    child_slugs: list[str] | None,
    member_counts: dict[str, int],
    child_counts: dict[str, int] | None = None,
    display_name: str | None = None,
) -> dict:
    data: dict = {}
    # Categories carry a hand-set plural name (the Wikidata label is singular
    # and lower-case, e.g. "planet"); the description still comes from Wikidata.
    if group.type is GroupType.CATEGORY:
        spec = CATEGORY_BY_SLUG.get(group.slug)
        if spec:
            data["name"] = spec.name
    # Split-comet families have no Wikidata label of their own — the catalog
    # name of the comet (passed in) is the reliable display name.
    elif group.type is GroupType.SPLIT_COMET and display_name:
        data["name"] = display_name
    if group.wikidata_qid:
        wd = wikidata_entities.get_referenced(group.wikidata_qid)
        if wd:
            # Orbit classes name from the frontend `orbit_class_<NAME>` i18n
            # keys, not the shared Wikidata label (IMB/MBA/OMB → "asteroid belt").
            if group.type not in (GroupType.CATEGORY, GroupType.ORBIT_CLASS):
                name = wd["labels"].get(lang) or wd["labels"].get("en")
                if name:
                    # Wikidata labels orbit zones sentence-case ("low Earth
                    # orbit"); the UI wants a capitalized leading letter.
                    if group.type is GroupType.EARTH_ORBIT_CLASS:
                        name = name[:1].upper() + name[1:]
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
    manufacturers = _manufacturer_refs_for_group(group, lang, wikidata_entities)
    if manufacturers:
        data["manufacturers"] = manufacturers
    if extracted:
        # Country pages don't show their own country of origin (it's themselves).
        if group.type is not GroupType.COUNTRY:
            country_qids = extracted.get("country_of_origin")
            if country_qids:
                country_refs: list[dict] = []
                for qid in country_qids:
                    ref = resolve_entity_ref(qid, lang, wikidata_entities)
                    if ref is None:
                        continue
                    attach_country_group_link(ref, qid)
                    country_refs.append(ref.to_dict())
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
    # Skip self-breakdown (a launch-site page can't list itself as a top site).
    if stats and stats.launch_sites and group.type is not GroupType.LAUNCH_SITE:
        sites = _launch_site_refs(stats.launch_sites, lang, wikidata_entities)
        if sites:
            data["launch_sites"] = sites
    if stats and stats.constellations and group.type is not GroupType.CONSTELLATION:
        constellations = _constellation_refs(
            stats.constellations, lang, wikidata_entities
        )
        if constellations:
            data["constellations"] = constellations
    if child_slugs:
        child_groups = _child_group_refs(
            child_slugs, lang, wikidata_entities, member_counts, child_counts
        )
        if child_groups:
            data["child_groups"] = child_groups
    return data


def _child_group_refs(
    child_slugs: list[str],
    lang: str,
    wikidata_entities: WikidataEntityCache,
    member_counts: dict[str, int],
    child_counts: dict[str, int] | None = None,
) -> list[dict]:
    """Child-group links for a parent page, with localized names + counts.

    ``child_counts`` overrides the displayed count per child slug — used by
    constellations, whose bus chips show the within-constellation tally rather
    than the bus group's global total. Falls back to ``member_counts``.
    """
    refs: list[dict] = []
    for slug in child_slugs:
        child = GROUP_BY_SLUG.get(slug)
        if child is None:
            continue
        if child.type is GroupType.CATEGORY:
            spec = CATEGORY_BY_SLUG.get(slug)
            name = spec.name if spec else slug
        else:
            name = slug
            if child.wikidata_qid:
                ref = resolve_entity_ref(child.wikidata_qid, lang, wikidata_entities)
                if ref is not None and ref.name:
                    name = ref.name
                    if child.type in (
                        GroupType.ORBIT_CLASS,
                        GroupType.EARTH_ORBIT_CLASS,
                    ):
                        name = name[:1].upper() + name[1:]
            elif child.type is GroupType.BUS:
                # QID-less buses (7 of them) carry no Wikidata label; fall back
                # to the first alias rather than the raw "bus-…" slug.
                bus = BUS_BY_SLUG.get(slug.removeprefix(BUS_SLUG_PREFIX))
                if bus is not None and bus.also_known_as:
                    name = bus.also_known_as[0]
        n = member_counts.get(slug, 0)
        if child_counts is not None and slug in child_counts:
            n = child_counts[slug]
        refs.append(
            {
                "name": name,
                "n": n,
                "primary_type": "group",
                "primary_id": slug,
                "role": str(child.type),
            }
        )
    return refs


def _launch_site_refs(
    counts: dict[str, int],
    lang: str,
    wikidata_entities: WikidataEntityCache,
) -> list[dict]:
    """Top sites with localized ref + count; unknown codes dropped."""
    top = sorted(counts.items(), key=lambda kv: kv[1], reverse=True)[:_TOP_LAUNCH_SITES]
    out: list[dict] = []
    for code, n in top:
        spec = LAUNCH_SITE_BY_CODE.get(code)
        if not spec:
            continue
        name = spec.name
        if spec.wikidata_qid:
            ref = resolve_entity_ref(spec.wikidata_qid, lang, wikidata_entities)
            if ref is not None and ref.name:
                name = ref.name
        out.append(
            {
                "n": n,
                "name": name,
                "primary_type": "group",
                "primary_id": f"{LAUNCH_SITE_SLUG_PREFIX}{spec.slug}",
            }
        )
    return out


def _constellation_refs(
    counts: dict[str, int],
    lang: str,
    wikidata_entities: WikidataEntityCache,
) -> list[dict]:
    """Top constellations with localized ref + count; unknown slugs dropped."""
    top = sorted(counts.items(), key=lambda kv: kv[1], reverse=True)[
        :_TOP_CONSTELLATIONS
    ]
    out: list[dict] = []
    for slug, n in top:
        spec = CONSTELLATION_BY_SLUG.get(slug)
        if not spec:
            continue
        name = spec.slug
        if spec.wikidata_qid:
            ref = resolve_entity_ref(spec.wikidata_qid, lang, wikidata_entities)
            if ref is not None and ref.name:
                name = ref.name
        out.append(
            {
                "n": n,
                "name": name,
                "primary_type": "group",
                "primary_id": f"{CONSTELLATION_SLUG_PREFIX}{spec.slug}",
            }
        )
    return out


def _extract_group_claims(
    group: Group, wikidata_entities: WikidataEntityCache
) -> dict | None:
    """Run the shared object-claim extractor on the group's Wikidata entity."""
    # Country entities carry many object-style claims (population, area, …)
    # that the shared extractor can't disambiguate; none are surfaced on the
    # country-page UI anyway. Orbit-class entities point to encyclopedic
    # concept pages whose claims (e.g. discoverer, named after) describe the
    # category, not its members.
    if group.type in (
        GroupType.COUNTRY,
        GroupType.ORBIT_CLASS,
        GroupType.EARTH_ORBIT_CLASS,
        GroupType.CATEGORY,
    ):
        return None
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
    """Operators of a constellation, resolved as EntityRefs (constants, not P137)."""
    if group.type is not GroupType.CONSTELLATION:
        return []
    operators = OPERATOR_BY_CONSTELLATION.get(
        group.slug.removeprefix(CONSTELLATION_SLUG_PREFIX), []
    )
    refs: list[dict] = []
    for op in operators:
        org_group_slug = f"{ORGANIZATION_SLUG_PREFIX}{op.slug}"
        name = op.name
        if op.wikidata_qid:
            ref = resolve_entity_ref(op.wikidata_qid, lang, wikidata_entities)
            if ref is not None and ref.name:
                name = ref.name
        refs.append(
            {
                "name": name,
                "primary_type": "group",
                "primary_id": org_group_slug,
            }
        )
    return refs


def _manufacturer_refs_for_group(
    group: Group,
    lang: str,
    wikidata_entities: WikidataEntityCache,
) -> list[dict]:
    """Manufacturers of a constellation or bus, resolved as EntityRefs."""
    if group.type is GroupType.CONSTELLATION:
        manufacturers = MANUFACTURER_BY_CONSTELLATION.get(
            group.slug.removeprefix(CONSTELLATION_SLUG_PREFIX), []
        )
    elif group.type is GroupType.BUS:
        bus = BUS_BY_SLUG.get(group.slug.removeprefix(BUS_SLUG_PREFIX))
        manufacturers = [bus.manufacturer] if bus is not None else []
    else:
        return []
    refs: list[dict] = []
    for mfr in manufacturers:
        org_group_slug = f"{ORGANIZATION_SLUG_PREFIX}{mfr.slug}"
        name = mfr.name
        if mfr.wikidata_qid:
            ref = resolve_entity_ref(mfr.wikidata_qid, lang, wikidata_entities)
            if ref is not None and ref.name:
                name = ref.name
        refs.append(
            {
                "name": name,
                "primary_type": "group",
                "primary_id": org_group_slug,
            }
        )
    return refs


def _flatten_membership(
    membership_by_type: dict[GroupType, dict[str, list[str]]],
) -> dict[str, int]:
    """Collapse per-type membership into a single {slug: count} map."""
    return {
        slug: len(ids)
        for mem in membership_by_type.values()
        for slug, ids in mem.items()
    }


def _flatten_stats(
    stats_by_type: dict[GroupType, dict[str, GroupSatcatStats]],
) -> dict[str, GroupSatcatStats]:
    return {
        slug: stats
        for per_type in stats_by_type.values()
        for slug, stats in per_type.items()
    }


def write_group_bundles(
    out_dir: Path,
    wikidata_entities: WikidataEntityCache,
    membership_by_type: dict[GroupType, dict[str, list[str]]],
    stats_by_type: dict[GroupType, dict[str, GroupSatcatStats]],
    extra_member_counts: dict[str, int] | None = None,
    extra_histograms: dict[str, dict[int, int]] | None = None,
    extra_launch_histograms: dict[str, dict[int, int]] | None = None,
    extra_largest_bodies: dict[str, LargestBody] | None = None,
    extra_pha_counts: dict[str, int] | None = None,
    extra_named_counts: dict[str, int] | None = None,
    extra_notable_members: dict[str, list[NotableObject]] | None = None,
    child_slugs_by_group: dict[str, list[str]] | None = None,
    child_counts_by_group: dict[str, dict[str, int]] | None = None,
    extra_groups: tuple[Group, ...] = (),
    extra_group_names: dict[str, str] | None = None,
) -> dict[str, int]:
    """Write groups/__global__/ + groups/{lang}/ bundles and __index__.json.

    The ``extra_*`` dicts carry per-slug stats for group types that ship no
    membership inverted index (orbit classes, small-body flags).
    ``extra_groups`` are DB-derived groups (split-comet families) appended to
    the static registry; ``extra_group_names`` gives their localized display
    name (they carry no Wikidata label of their own). Returns
    ``{global: N, lang: N, ...}`` for publication in metadata.json.
    """
    member_counts = _flatten_membership(membership_by_type)
    if extra_member_counts:
        member_counts.update(extra_member_counts)
    satcat_stats = _flatten_stats(stats_by_type)
    global_by_slug: dict[str, dict] = {}
    localized_by_slug: dict[str, dict[str, dict]] = {lang: {} for lang in LANGUAGES}

    for group in (*GROUPS, *extra_groups):
        wiki_summaries = (
            load_wikipedia_summaries_for_qid(group.wikidata_qid)
            if group.wikidata_qid
            else {}
        )
        extracted = _extract_group_claims(group, wikidata_entities)
        images = collect_group_images(group.slug)
        stats = satcat_stats.get(group.slug)
        discovery_histogram = (extra_histograms or {}).get(group.slug)
        launch_histogram_override = (extra_launch_histograms or {}).get(group.slug)
        largest_body = (extra_largest_bodies or {}).get(group.slug)
        pha_count = (extra_pha_counts or {}).get(group.slug, 0)
        named_count = (extra_named_counts or {}).get(group.slug, 0)
        members = (extra_notable_members or {}).get(group.slug)
        member_entries = (
            notable_entries(members, wikidata_entities) if members else None
        )
        global_by_slug[group.slug] = _build_global(
            group,
            member_counts.get(group.slug, 0),
            extracted,
            stats,
            discovery_histogram,
            launch_histogram_override,
            images,
            largest_body,
            pha_count,
            named_count,
            member_entries,
        )
        child_slugs = (child_slugs_by_group or {}).get(group.slug)
        child_counts = (child_counts_by_group or {}).get(group.slug)
        display_name = (extra_group_names or {}).get(group.slug)
        for lang in LANGUAGES:
            lang_data = _build_localized(
                group,
                lang,
                wikidata_entities,
                wiki_summaries,
                extracted,
                stats,
                child_slugs,
                member_counts,
                child_counts,
                display_name,
            )
            if members and member_entries:
                member_names = notable_names(
                    members, member_entries, lang, wikidata_entities
                )
                if member_names:
                    lang_data["notable_member_names"] = member_names
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
