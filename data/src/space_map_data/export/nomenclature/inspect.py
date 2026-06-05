"""Single-body nomenclature details preview — does not touch disk.

Run::

    python -m space_map_data.export.nomenclature.inspect naif-301

Reports per-relationship counts, source-contribution breakdown for
inside_of, sample entries, and an estimated bundle size after gzip.
"""

import argparse
import gzip
import logging
import math
import sys
from collections import defaultdict
from typing import Any

import orjson

from space_map_data.constants.providers import LANGUAGES
from space_map_data.export.nomenclature.writer import (
    K_GLOBAL,
    K_LOCALIZED,
    build_feature_details,
    feature_bucket_key,
    hash_bucket,
)
from space_map_data.export.quantities import UnitConverter
from space_map_data.export.systems import load_radii
from space_map_data.export.wikidata import WikidataEntityCache
from space_map_data.models.feature import Feature
from space_map_data.utils.db import session_scope
from space_map_data.utils.paths import DOWNLOAD_DIR


_DEFAULT_BODY = "naif-301"
_SAMPLE_LIMIT = 8


def _fid_from_bucket(key: str) -> int:
    return int(key.split(":")[1])


def _format_target(ref: dict) -> str:
    ptype = ref.get("primary_type")
    pid = ref.get("primary_id")
    sid = ref.get("secondary_id")
    if pid is None:
        return "no-focus"
    target = f"{ptype}-{pid}"
    if sid is not None:
        target += f" / feature={sid}"
    return target


def _bundle_size_stats(data: dict[str, Any], k: int) -> dict[str, float | int]:
    if not data:
        return {"n_buckets": 0, "avg_kib": 0, "min_kib": 0, "max_kib": 0}
    n = max(1, math.ceil(len(data) / k))
    buckets: dict[int, dict[str, Any]] = defaultdict(dict)
    for key, val in data.items():
        buckets[hash_bucket(key, n)][key] = val
    sizes = [len(gzip.compress(orjson.dumps(b))) for b in buckets.values()]
    return {
        "n_buckets": n,
        "avg_kib": sum(sizes) / len(sizes) / 1024.0,
        "min_kib": min(sizes) / 1024.0,
        "max_kib": max(sizes) / 1024.0,
        "members_avg": len(data) / n,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "body_id",
        nargs="?",
        default=_DEFAULT_BODY,
        help=f"Object.id to inspect (default: {_DEFAULT_BODY})",
    )
    parser.add_argument("--lang", default="en", choices=LANGUAGES)
    parser.add_argument("--limit", type=int, default=_SAMPLE_LIMIT)
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.INFO, format="%(levelname)s %(name)s: %(message)s"
    )

    body_radii_km = {
        f"naif-{naif_id}": (r["a"] + r["b"] + r["c"]) / 3.0
        for naif_id, r in load_radii(DOWNLOAD_DIR).items()
    }

    trace_sources: dict[int, dict[str, set[int]]] = {}

    with session_scope() as session:
        body_features = (
            session.query(
                Feature.feature_id,
                Feature.name,
                Feature.unicode_name,
                Feature.feature_type_code,
                Feature.parent_feature_id,
            )
            .filter(Feature.object_id == args.body_id)
            .all()
        )
        if not body_features:
            print(f"No features found for body {args.body_id!r}", file=sys.stderr)
            return 1
        names = {r.feature_id: (r.unicode_name or r.name) for r in body_features}
        type_codes = {r.feature_id: r.feature_type_code for r in body_features}
        parent_ids = {r.feature_id: r.parent_feature_id for r in body_features}

        wikidata = WikidataEntityCache()
        units = UnitConverter(wikidata)
        details = build_feature_details(
            session,
            wikidata,
            units,
            body_filter=args.body_id,
            body_radii_km=body_radii_km,
            trace_sources=trace_sources,
        )

    global_data = details.global_data
    lang_data = details.localized_data.get(args.lang, {})

    counts = {
        "has_parent_feature": 0,
        "has_satellite_features": 0,
        "has_contains": 0,
        "has_inside_of": 0,
        "has_quadrangle": 0,
    }
    inside_of_total = 0
    inside_of_resolved = 0
    inside_of_unresolved_samples: list[tuple[int, dict]] = []
    samples_inside_of: list[tuple[int, dict]] = []

    for entry in global_data.values():
        if entry.get("parent_feature"):
            counts["has_parent_feature"] += 1
        if entry.get("satellite_features"):
            counts["has_satellite_features"] += 1
        if entry.get("contains"):
            counts["has_contains"] += 1
        if entry.get("quadrangle"):
            counts["has_quadrangle"] += 1

    for bucket_key, localized in lang_data.items():
        inside = localized.get("inside_of", [])
        if inside:
            counts["has_inside_of"] += 1
        for ref in inside:
            inside_of_total += 1
            fid = _fid_from_bucket(bucket_key)
            if ref.get("primary_id") is not None:
                inside_of_resolved += 1
                if len(samples_inside_of) < args.limit:
                    samples_inside_of.append((fid, ref))
            elif len(inside_of_unresolved_samples) < args.limit:
                inside_of_unresolved_samples.append((fid, ref))

    # Source attribution (only same-body feature edges, i.e. focus-resolved ones).
    source_totals: dict[str, int] = defaultdict(int)
    source_unique: dict[str, int] = defaultdict(int)
    for sources in trace_sources.values():
        if not sources:
            continue
        all_targets: set[int] = set()
        for tgts in sources.values():
            all_targets.update(tgts)
        for src, tgts in sources.items():
            source_totals[src] += len(tgts)
            other: set[int] = set()
            for s2, t2 in sources.items():
                if s2 != src:
                    other |= t2
            source_unique[src] += len(tgts - other)

    print(f"=== {args.body_id} — lang={args.lang} ===")
    print(f"features with details (global tier): {len(global_data)}")
    print(f"features with localized data:        {len(lang_data)}")
    print()
    print("-- field presence (counts) --")
    for key, n in counts.items():
        print(f"  {key:24s}: {n}")
    pct = (100 * inside_of_resolved / inside_of_total) if inside_of_total else 0.0
    print(f"  inside_of refs total       : {inside_of_total}")
    print(f"  inside_of focus-resolved   : {inside_of_resolved} ({pct:.1f}%)")
    print()

    print("-- inside_of source contributions (same-body feature edges) --")
    for src in sorted(source_totals.keys()):
        print(
            f"  {src:30s}: {source_totals[src]:6d} edges  "
            f"({source_unique[src]:6d} unique to source)"
        )
    print()

    # Bundle size estimate
    gstats = _bundle_size_stats(global_data, K_GLOBAL)
    lstats = _bundle_size_stats(lang_data, K_LOCALIZED)
    print(
        f"-- bundle size estimate (K_GLOBAL={K_GLOBAL}, K_LOCALIZED={K_LOCALIZED}) --"
    )
    print(
        f"  global  : {gstats['n_buckets']} bucket(s), "
        f"avg {gstats['avg_kib']:.1f} KiB / "
        f"min {gstats['min_kib']:.1f} / max {gstats['max_kib']:.1f} "
        f"(avg members: {gstats.get('members_avg', 0):.0f})"
    )
    print(
        f"  {args.lang}      : {lstats['n_buckets']} bucket(s), "
        f"avg {lstats['avg_kib']:.1f} KiB / "
        f"min {lstats['min_kib']:.1f} / max {lstats['max_kib']:.1f} "
        f"(avg members: {lstats.get('members_avg', 0):.0f})"
    )
    print()

    print(
        f"-- sample parent_feature ({min(args.limit, counts['has_parent_feature'])}) --"
    )
    shown = 0
    for bucket_key, entry in global_data.items():
        pf = entry.get("parent_feature")
        if not pf:
            continue
        fid = _fid_from_bucket(bucket_key)
        print(
            f"  {names.get(fid, '?')!r} parent_feature → "
            f"{pf['name']!r} ({_format_target(pf)})"
        )
        shown += 1
        if shown >= args.limit:
            break
    print()

    print("-- sample satellite_features --")
    shown = 0
    for bucket_key, entry in global_data.items():
        sf = entry.get("satellite_features")
        if not sf:
            continue
        fid = _fid_from_bucket(bucket_key)
        sample = ", ".join(f"{r['name']}" for r in sf[:5])
        more = "" if len(sf) <= 5 else f", … (+{len(sf) - 5})"
        print(f"  {names.get(fid, '?')!r} [{len(sf)}]: {sample}{more}")
        shown += 1
        if shown >= args.limit:
            break
    print()

    print("-- sample contains --")
    shown = 0
    for bucket_key, entry in global_data.items():
        contains = entry.get("contains")
        if not contains:
            continue
        fid = _fid_from_bucket(bucket_key)
        sample = ", ".join(f"{r['name']}" for r in contains[:5])
        more = "" if len(contains) <= 5 else f", … (+{len(contains) - 5})"
        print(f"  {names.get(fid, '?')!r} [{len(contains)}]: {sample}{more}")
        shown += 1
        if shown >= args.limit:
            break
    print()

    print(f"-- sample quadrangle ({min(args.limit, counts['has_quadrangle'])}) --")
    shown = 0
    for bucket_key, entry in global_data.items():
        q = entry.get("quadrangle")
        if not q:
            continue
        fid = _fid_from_bucket(bucket_key)
        print(f"  {names.get(fid, '?')!r} → {q['name']!r} ({q.get('short_name', '?')})")
        shown += 1
        if shown >= args.limit:
            break
    print()

    print(f"-- sample inside_of (focus-resolved, {len(samples_inside_of)}) --")
    for fid, ref in samples_inside_of:
        print(
            f"  {names.get(fid, '?')!r} inside_of → "
            f"{ref['name']!r} ({_format_target(ref)})"
        )
    print()

    print(f"-- sample inside_of (UNresolved, {len(inside_of_unresolved_samples)}) --")
    for fid, ref in inside_of_unresolved_samples:
        wiki = " [wiki]" if ref.get("wikipedia") else ""
        print(f"  {names.get(fid, '?')!r} inside_of → {ref['name']!r}{wiki}")
    print()

    # Linear-feature container audit: do Rupes/Vallis/Catena/Dorsum types
    # ever appear as inside_of targets? Small audit on demand.
    linear_codes = {
        "RU",
        "VA",
        "CA",
        "DO",
        "FO",
        "FT",
    }  # rupes/vallis/catena/dorsa/fossa/fluctus
    linear_targets_as_containers: dict[str, int] = defaultdict(int)
    for sources in trace_sources.values():
        for src, tgts in sources.items():
            if src not in {"bbox", "radius"}:
                continue
            for tgt in tgts:
                code = type_codes.get(tgt) or ""
                if code in linear_codes:
                    linear_targets_as_containers[code] += 1
    if linear_targets_as_containers:
        print("-- linear-feature types acting as bbox/radius containers --")
        for code, n in sorted(linear_targets_as_containers.items()):
            print(f"  {code}: {n} edges")
    else:
        print("-- no linear-feature types appear as bbox/radius containers --")
    print()

    # Sanity check
    assert feature_bucket_key(args.body_id, 1) == f"{args.body_id}:1"
    # SF-children-skip-bbox invariant
    sf_in_contains = 0
    for entry in global_data.values():
        for ref in entry.get("contains", []):
            sid = ref.get("secondary_id")
            if sid and parent_ids.get(int(sid)) is not None:
                # A contains target that has parent_feature_id set could
                # only come via Wikidata edges (bbox/radius are skipped
                # for SF children).
                sf_in_contains += 1
    print(f"contains entries that are SF children (Wikidata-only): {sf_in_contains}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
