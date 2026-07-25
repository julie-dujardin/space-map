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

from space_map_data.constants.categories import (
    CATEGORY_BY_SLUG,
    DEBRIS_SLUG,
    SATELLITES_SLUG,
)
from space_map_data.constants.earth_sats.constellations import (
    CONSTELLATION_BY_SLUG,
    CONSTELLATION_SLUG_PREFIX,
    DEBRIS_CONSTELLATION_SLUGS,
)
from space_map_data.constants.earth_sats.launch_sites import (
    LAUNCH_SITE_BY_CODE,
    LAUNCH_SITE_BY_SLUG,
)
from space_map_data.constants.earth_sats.launch_vehicles import (
    GCAT_LV_TYPE_TO_QID,
    LAUNCH_VEHICLE_BY_CONSTELLATION,
)
from space_map_data.constants.earth_sats.manufacturers import (
    MANUFACTURER_BY_CONSTELLATION,
)
from space_map_data.constants.earth_sats.operators import OPERATOR_BY_CONSTELLATION
from space_map_data.constants.earth_sats.organizations import (
    ORGANIZATION_BY_SLUG,
    ORGANIZATION_SLUG_PREFIX,
)
from space_map_data.constants.earth_sats.satellite_models import BUS_BY_SLUG
from space_map_data.constants.nomenclature.feature_types import (
    FEATURE_TYPE_CODE_BY_SLUG,
    FEATURE_TYPES,
)
from space_map_data.constants.providers import LANGUAGES
from space_map_data.export.groups.feature_type import FeatureTypeStats
from space_map_data.export.groups.launch_vehicle import LaunchVehicleStats
from space_map_data.export.groups.membership import GroupSatcatStats
from space_map_data.export.groups.registry import (
    BUS_SLUG_PREFIX,
    CLASS_SLUG_PREFIX,
    LAUNCH_SITE_SLUG_PREFIX,
    LAUNCH_VEHICLE_SLUG_PREFIX,
    SMALL_BODY_FLAG_SLUG_PREFIX,
    GROUP_BY_SLUG,
    GROUPS,
    Group,
    GroupCategory,
    GroupType,
)
from space_map_data.export.groups.small_body import LargestBody
from space_map_data.export.images import collect_group_images
from space_map_data.export.notable import (
    NotableObject,
    notable_descriptions,
    notable_entries,
    notable_names,
)
from space_map_data.export.objects.wikidata_claims import (
    attach_country_group_link,
    extract_claims,
    resolve_entity_ref,
)
from space_map_data.constants.earth_sats.orbit_class import LAGRANGE_CLASSES
from space_map_data.export.objects.wikipedia import (
    WikipediaSummary,
    load_wikipedia_sections_for_qid,
    load_wikipedia_summaries_for_qid,
)
from space_map_data.export.objects.writer import hash_bucket
from space_map_data.export.wikidata import WikidataEntityCache

logger = logging.getLogger(__name__)

K_GLOBAL = 1000
K_LOCALIZED = 600
_TOP_LAUNCH_SITES = 5
_TOP_CONSTELLATIONS = 5
# The Satellites category page devotes a whole section to constellations, so it
# lists more than the per-group breakdown does.
_CATEGORY_TOP_CONSTELLATIONS = 10


_FLAG_PHA_SLUG = f"{SMALL_BODY_FLAG_SLUG_PREFIX}pha"

# Lagrange classes name from frontend i18n (Wikidata label is the bare "L1"/"L2").
_LAGRANGE_CLASS_SLUGS = frozenset(
    f"{CLASS_SLUG_PREFIX}{cls.name}" for cls in LAGRANGE_CLASSES
)


def _build_global(
    group: Group,
    member_count: int,
    sitelinks_count: int,
    extracted: dict | None,
    stats: GroupSatcatStats | None,
    discovery_histogram: dict[int, int] | None,
    launch_histogram_override: dict[int, int] | None,
    images: list[dict] | None,
    largest_body: LargestBody | None,
    pha_count: int,
    named_count: int,
    notable_members: list[dict] | None,
    moon_counts: list[dict] | None,
    primary_id: str | None,
    lv_stats: LaunchVehicleStats | None,
    orbit_classes: list[str] | None,
    ft_stats: FeatureTypeStats | None,
) -> dict:
    data: dict = {
        "slug": group.slug,
        "type": str(group.type),
        "applies_to": str(group.applies_to),
        "member_count": member_count,
    }
    if parent_category := _category_parent(group):
        data["parent_category"] = parent_category
    if group.wikidata_qid:
        data["wikidata_qid"] = group.wikidata_qid
    # Wikidata prominence — the catalog index's cross-kind ranking tiebreaker,
    # so collection results order by notability rather than ingest order.
    if sitelinks_count:
        data["sitelinks_count"] = sitelinks_count
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
    # The orbit zone(s) this constellation calls home, so it lists among its
    # zone's members in the catalog index.
    if orbit_classes:
        data["orbit_classes"] = orbit_classes
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
    # Launch vehicles: the launchlog is the authoritative launch history (the
    # satcat stats above only see spent stages still catalogued in orbit), so
    # it overrides the histogram + first launch and adds launch-level facts.
    if lv_stats is not None:
        data["launch_count"] = lv_stats.launch_count
        data["payload_count"] = lv_stats.payload_count
        if lv_stats.success_count:
            data["success_count"] = lv_stats.success_count
        if lv_stats.failure_count:
            data["failure_count"] = lv_stats.failure_count
        if lv_stats.last_launch_date:
            data["last_launch_date"] = lv_stats.last_launch_date
        if lv_stats.first_launch_date:
            data["first_launch_date"] = lv_stats.first_launch_date
        if lv_stats.launch_histogram:
            data["launch_histogram"] = {
                str(year): n for year, n in sorted(lv_stats.launch_histogram.items())
            }
        if lv_stats.variants:
            data["variants"] = lv_stats.variants
        if lv_stats.reusable_vehicles:
            data["reusable_vehicles"] = lv_stats.reusable_vehicles
    # Feature types: the IAU gazetteer roll-up behind an ft- page. member_count
    # already carries the feature tally, so only the extras land here. The
    # Surface Features meta node fills only the two counts.
    if ft_stats is not None:
        data["body_count"] = ft_stats.body_count
        if ft_stats.type_count:
            data["feature_type_count"] = ft_stats.type_count
        if ft_stats.families:
            data["feature_families"] = ft_stats.families
        if ft_stats.naming_origins:
            data["naming_origins"] = ft_stats.naming_origins
        if ft_stats.bodies:
            data["feature_bodies"] = ft_stats.bodies
        if ft_stats.largest:
            data["largest_feature"] = ft_stats.largest
        if ft_stats.first_approval:
            data["first_approval_date"] = ft_stats.first_approval
        if ft_stats.last_approval:
            data["last_approval_date"] = ft_stats.last_approval
        if ft_stats.approval_histogram:
            data["approval_histogram"] = {
                str(year): n for year, n in ft_stats.approval_histogram.items()
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
    # Moons category: per-planet/dwarf moon tallies driving its bar chart.
    if moon_counts:
        data["moon_counts"] = moon_counts
    # Focus redirect for mission pages (fly to the primary probe, not a filter).
    if primary_id:
        data["primary"] = {"primary_type": "object", "primary_id": primary_id}
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


def _group_entity(group: Group, wikidata_entities: WikidataEntityCache):
    """The group's own Wikidata entity.

    Feature types are preloaded in their own tier for the nomenclature popover,
    so a ft- page renders even before the group-QID download pass has seeded
    ``referenced/``.
    """
    if group.type is GroupType.FEATURE_TYPE:
        wd = wikidata_entities.get_feature_type(group.wikidata_qid)
        if wd is not None:
            return wd
    return wikidata_entities.get_referenced(group.wikidata_qid)


def _prettify_slug(slug: str, prefix: str) -> str:
    """Title-cased fallback label from a kebab slug ("const-tianqi" → "Tianqi")."""
    return slug.removeprefix(prefix).replace("-", " ").title()


def _fallback_group_name(group: Group) -> str | None:
    """Display name for a QID-less group, from the static constants.

    Orbit classes (frontend `orbit_class_*` i18n) and countries (browser-
    localized from the ISO code) are intentionally left nameless here — the
    frontend resolves them — so this returns None for those types.
    """
    if group.type is GroupType.CONSTELLATION:
        spec = CONSTELLATION_BY_SLUG.get(
            group.slug.removeprefix(CONSTELLATION_SLUG_PREFIX)
        )
        # The TLE name prefix ("SITRO-AIS", "TIANQI-") is the best label; drop
        # any trailing separator left from the prefix match.
        if spec and isinstance(spec.prefix, str) and (p := spec.prefix.strip(" -_")):
            return p
        return _prettify_slug(group.slug, CONSTELLATION_SLUG_PREFIX)
    if group.type is GroupType.ORGANIZATION:
        org = ORGANIZATION_BY_SLUG.get(
            group.slug.removeprefix(ORGANIZATION_SLUG_PREFIX)
        )
        if org:
            return org.name
    if group.type is GroupType.BUS:
        bus = BUS_BY_SLUG.get(group.slug.removeprefix(BUS_SLUG_PREFIX))
        if bus and bus.also_known_as:
            return bus.also_known_as[0]
    if group.type is GroupType.LAUNCH_SITE:
        site = LAUNCH_SITE_BY_SLUG.get(group.slug.removeprefix(LAUNCH_SITE_SLUG_PREFIX))
        if site:
            return site.name
    if group.type is GroupType.FEATURE_TYPE:
        # Four codes have no Wikidata entry (CL, LF, LO, ST); the IAU singular
        # is the only name they'll ever have.
        code = FEATURE_TYPE_CODE_BY_SLUG.get(group.slug)
        if code:
            return FEATURE_TYPES[code].singular
    return None


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
    lv_stats: LaunchVehicleStats | None = None,
    constellation_counts: dict[str, int] | None = None,
    ft_stats: FeatureTypeStats | None = None,
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
        wd = _group_entity(group, wikidata_entities)
        if wd:
            # Orbit classes name from frontend i18n, not the Wikidata label
            # (IMB/MBA/OMB → "asteroid belt"; EL1/EL2 → bare "L1"/"L2").
            if (
                group.type not in (GroupType.CATEGORY, GroupType.ORBIT_CLASS)
                and group.slug not in _LAGRANGE_CLASS_SLUGS
            ):
                name = wd["labels"].get(lang) or wd["labels"].get("en")
                if name:
                    # Wikidata labels orbit zones and landforms sentence-case
                    # ("low Earth orbit", "crater"); the UI wants a capitalized
                    # leading letter.
                    if group.type in (
                        GroupType.EARTH_ORBIT_CLASS,
                        GroupType.FEATURE_TYPE,
                    ):
                        name = name[:1].upper() + name[1:]
                    data["name"] = name
            desc = wd["descriptions"].get(lang)
            if desc:
                data["description"] = desc
    # No Wikidata label (QID-less or entity not downloaded) — fall back to the
    # curated constant name so search/drawer never show the raw slug.
    if "name" not in data:
        fallback = _fallback_group_name(group)
        if fallback:
            data["name"] = fallback
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
    # Categories carry no GroupSatcatStats; the Satellites page's constellation
    # counts arrive separately and show a longer list than a per-group breakdown.
    elif constellation_counts:
        constellations = _constellation_refs(
            constellation_counts, lang, wikidata_entities, _CATEGORY_TOP_CONSTELLATIONS
        )
        if constellations:
            data["constellations"] = constellations
    if child_slugs:
        child_groups = _child_group_refs(
            child_slugs, lang, wikidata_entities, member_counts, child_counts
        )
        if child_groups:
            data["child_groups"] = child_groups
    # Localized labels for the feature-type page's per-body bar chart; the
    # global rows carry English body names.
    if ft_stats is not None and ft_stats.body_qids:
        body_names = {
            object_id: label
            for object_id, qid in ft_stats.body_qids.items()
            if (wd := wikidata_entities.get_entity(qid))
            and (label := wd["labels"].get(lang))
        }
        if body_names:
            data["body_names"] = body_names
    if lv_stats and lv_stats.variants:
        variant_refs = _variant_refs(lv_stats.variants, lang, wikidata_entities)
        if variant_refs:
            data["variant_refs"] = variant_refs
    if lv_stats and lv_stats.reusable_vehicle_qids:
        reusable_refs = {
            name: ref.to_dict()
            for name, qid in lv_stats.reusable_vehicle_qids.items()
            if (ref := resolve_entity_ref(qid, lang, wikidata_entities))
            and ref.wikipedia
        }
        if reusable_refs:
            data["reusable_vehicle_refs"] = reusable_refs
    return data


def _variant_refs(
    variants: list[dict], lang: str, wikidata_entities: WikidataEntityCache
) -> dict[str, dict]:
    """Localized Wikipedia ref per breakdown variant, keyed by GCAT name.

    Only variants matched to a more-specific QID with a sitelink; the breakdown
    keeps the GCAT string as its label and uses this just for the link.
    """
    out: dict[str, dict] = {}
    for entry in variants:
        qid = GCAT_LV_TYPE_TO_QID.get(entry["name"])
        if not qid:
            continue
        ref = resolve_entity_ref(qid, lang, wikidata_entities)
        if ref and ref.wikipedia:
            out[entry["name"]] = ref.to_dict()
    return out


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
                    # Wikidata labels these sentence-case ("low Earth orbit",
                    # "impact crater"); chips read as titles, same as the page.
                    if child.type in (
                        GroupType.ORBIT_CLASS,
                        GroupType.EARTH_ORBIT_CLASS,
                        GroupType.FEATURE_TYPE,
                    ):
                        name = name[:1].upper() + name[1:]
            else:
                # QID-less children (7 buses, 4 feature types) carry no Wikidata
                # label; the curated constant beats the raw slug.
                name = _fallback_group_name(child) or slug
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


def _category_parent(group: Group) -> str | None:
    """Category page an Earth-orbiter group breadcrumbs to.

    Spent stages (``lv-``) and breakup clouds are debris; every other earth-sat
    group — fleets, operators, launch sites, orbit zones — sits under Satellites.
    None for group types whose parent the frontend derives from the slug prefix.
    """
    if group.applies_to is not GroupCategory.EARTH_SAT:
        return None
    if group.type is GroupType.LAUNCH_VEHICLE:
        return DEBRIS_SLUG
    if (
        group.type is GroupType.CONSTELLATION
        and group.slug.removeprefix(CONSTELLATION_SLUG_PREFIX)
        in DEBRIS_CONSTELLATION_SLUGS
    ):
        return DEBRIS_SLUG
    return SATELLITES_SLUG


def _constellation_refs(
    counts: dict[str, int],
    lang: str,
    wikidata_entities: WikidataEntityCache,
    limit: int = _TOP_CONSTELLATIONS,
) -> list[dict]:
    """Top constellations with localized ref + count; unknown slugs dropped.

    ROCKET constellations emit no ``const-`` page — they surface as ``lv-``
    launch vehicles — so they're rewritten to that slug here rather than
    pointing at a group that doesn't exist.
    """
    top = sorted(counts.items(), key=lambda kv: kv[1], reverse=True)[:limit]
    out: list[dict] = []
    for slug, n in top:
        spec = CONSTELLATION_BY_SLUG.get(slug)
        if not spec:
            continue
        lv = LAUNCH_VEHICLE_BY_CONSTELLATION.get(spec.slug)
        if lv is not None:
            primary_id = f"{LAUNCH_VEHICLE_SLUG_PREFIX}{lv.slug}"
            name, qid = lv.name or lv.slug, lv.qid
        else:
            primary_id = f"{CONSTELLATION_SLUG_PREFIX}{spec.slug}"
            name, qid = spec.slug, spec.wikidata_qid
        if qid:
            ref = resolve_entity_ref(qid, lang, wikidata_entities)
            if ref is not None and ref.name:
                name = ref.name
        out.append(
            {
                "n": n,
                "name": name,
                "primary_type": "group",
                "primary_id": primary_id,
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
    extra_moon_counts: dict[str, list[dict]] | None = None,
    extra_primary_ids: dict[str, str] | None = None,
    child_slugs_by_group: dict[str, list[str]] | None = None,
    child_counts_by_group: dict[str, dict[str, int]] | None = None,
    extra_groups: tuple[Group, ...] = (),
    extra_group_names: dict[str, str] | None = None,
    launch_vehicle_stats: dict[str, LaunchVehicleStats] | None = None,
    feature_type_stats: dict[str, FeatureTypeStats] | None = None,
    constellation_orbit_classes: dict[str, list[str]] | None = None,
    extra_constellation_counts: dict[str, dict[str, int]] | None = None,
    displacement_metadata: dict[str, dict] | None = None,
    model_slugs: dict[str, str] | None = None,
    textured_ids: set[str] | None = None,
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
        if group.wikidata_qid:
            # A curated article-section extract overrides the sparse sitelink summary.
            wiki_summaries.update(load_wikipedia_sections_for_qid(group.wikidata_qid))
        extracted = _extract_group_claims(group, wikidata_entities)
        wd = _group_entity(group, wikidata_entities) if group.wikidata_qid else None
        sitelinks_count = len(wd["sitelinks"]) if wd else 0
        images = collect_group_images(group.slug)
        stats = satcat_stats.get(group.slug)
        discovery_histogram = (extra_histograms or {}).get(group.slug)
        launch_histogram_override = (extra_launch_histograms or {}).get(group.slug)
        largest_body = (extra_largest_bodies or {}).get(group.slug)
        pha_count = (extra_pha_counts or {}).get(group.slug, 0)
        named_count = (extra_named_counts or {}).get(group.slug, 0)
        members = (extra_notable_members or {}).get(group.slug)
        member_entries = (
            notable_entries(
                members,
                wikidata_entities,
                displacement_metadata,
                model_slugs,
                textured_ids,
            )
            if members
            else None
        )
        moon_counts = (extra_moon_counts or {}).get(group.slug)
        lv_stats = (launch_vehicle_stats or {}).get(group.slug)
        ft_stats = (feature_type_stats or {}).get(group.slug)
        global_by_slug[group.slug] = _build_global(
            group,
            member_counts.get(group.slug, 0),
            sitelinks_count,
            extracted,
            stats,
            discovery_histogram,
            launch_histogram_override,
            images,
            largest_body,
            pha_count,
            named_count,
            member_entries,
            moon_counts,
            (extra_primary_ids or {}).get(group.slug),
            lv_stats,
            (constellation_orbit_classes or {}).get(group.slug),
            ft_stats,
        )
        child_slugs = (child_slugs_by_group or {}).get(group.slug)
        child_counts = (child_counts_by_group or {}).get(group.slug)
        display_name = (extra_group_names or {}).get(group.slug)
        constellation_counts = (extra_constellation_counts or {}).get(group.slug)
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
                lv_stats,
                constellation_counts,
                ft_stats,
            )
            if members and member_entries:
                member_names = notable_names(
                    members, member_entries, lang, wikidata_entities
                )
                if member_names:
                    lang_data["notable_member_names"] = member_names
                member_descriptions = notable_descriptions(
                    members, lang, wikidata_entities
                )
                if member_descriptions:
                    lang_data["notable_member_descriptions"] = member_descriptions
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
            # Feature types only: the IAU code, so the frontend maps slug ↔ code
            # (member search filter, feature → type link) off the index it
            # already loads instead of duplicating the 57-entry table.
            **({"code": code} if (code := FEATURE_TYPE_CODE_BY_SLUG.get(slug)) else {}),
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
    # Drop bucket files from a previous run with a higher bucket count (e.g. an
    # additive --only groups run after a merge shrank the group set). Consumers
    # that glob the directory would otherwise ingest the stale orphans.
    for stale in dir_path.glob("*.json.gz"):
        stale.unlink()
    for b, entries in buckets.items():
        (dir_path / f"{b}.json.gz").write_bytes(gzip.compress(orjson.dumps(entries)))
