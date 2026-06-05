"""Single-body nomenclature details preview — does not touch disk.

Run::

    python -m space_map_data.export.nomenclature.inspect naif-301

Prints a sample of resolved entity refs (with their focus targets, if any)
and parents that gained a ``children`` list. Useful for eyeballing the
shape of the new export fields without rebuilding every body.
"""

import argparse
import logging
import sys
from collections.abc import Iterable

from space_map_data.constants.providers import LANGUAGES
from space_map_data.export.nomenclature.writer import (
    FOCUS_RESOLVE_CLAIM_KEYS,
    build_feature_details,
    feature_bucket_key,
)
from space_map_data.export.quantities import UnitConverter
from space_map_data.export.wikidata import WikidataEntityCache
from space_map_data.models.feature import Feature
from space_map_data.utils.db import session_scope


_DEFAULT_BODY = "naif-301"  # Moon — many SF parents + Wikidata located_on
_SAMPLE_LIMIT = 8


def _iter_focus_refs(
    detail: dict, claim_keys: Iterable[str]
) -> Iterable[tuple[str, dict]]:
    for key in claim_keys:
        for ref in detail.get(key, []):
            if ref.get("primary_id") is not None:
                yield key, ref


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

    with session_scope() as session:
        body_features = (
            session.query(Feature.feature_id, Feature.name, Feature.unicode_name)
            .filter(Feature.object_id == args.body_id)
            .all()
        )
        if not body_features:
            print(f"No features found for body {args.body_id!r}", file=sys.stderr)
            return 1
        names = {fid: (uname or name) for fid, name, uname in body_features}

        wikidata = WikidataEntityCache()
        units = UnitConverter(wikidata)
        details = build_feature_details(
            session, wikidata, units, body_filter=args.body_id
        )

    global_data = details.global_data
    lang_data = details.localized_data.get(args.lang, {})

    parents_with_children = [
        (k, v["children"]) for k, v in global_data.items() if v.get("children")
    ]

    # Per-claim totals and resolution rates
    claim_totals: dict[str, int] = dict.fromkeys(FOCUS_RESOLVE_CLAIM_KEYS, 0)
    claim_resolved: dict[str, int] = dict.fromkeys(FOCUS_RESOLVE_CLAIM_KEYS, 0)
    focus_examples: list[tuple[str, str, str, dict]] = []
    unresolved_examples: dict[str, list[tuple[str, str]]] = {
        k: [] for k in FOCUS_RESOLVE_CLAIM_KEYS
    }
    for bucket_key, localized in lang_data.items():
        for claim_key in FOCUS_RESOLVE_CLAIM_KEYS:
            for ref in localized.get(claim_key, []):
                claim_totals[claim_key] += 1
                if ref.get("primary_id") is not None:
                    claim_resolved[claim_key] += 1
                    if len(focus_examples) < args.limit:
                        focus_examples.append((bucket_key, claim_key, ref["name"], ref))
                elif len(unresolved_examples[claim_key]) < args.limit:
                    unresolved_examples[claim_key].append((bucket_key, ref["name"]))

    print(f"=== {args.body_id} — lang={args.lang} ===")
    print(f"features with details (global tier): {len(global_data)}")
    print(f"features with localized data:        {len(lang_data)}")
    print(f"parents with children list:          {len(parents_with_children)}")
    print()

    print("-- entity-ref resolution rates --")
    for claim_key in sorted(FOCUS_RESOLVE_CLAIM_KEYS):
        total = claim_totals[claim_key]
        resolved = claim_resolved[claim_key]
        pct = (100 * resolved / total) if total else 0.0
        print(f"  {claim_key:30s}: {resolved}/{total} resolved ({pct:.1f}%)")
    print()

    print(f"-- sample focus-resolved entity refs ({len(focus_examples)}) --")
    for bucket_key, claim_key, name, ref in focus_examples:
        feature_name = names.get(int(bucket_key.split(":")[1]), "?")
        pid = ref.get("primary_id")
        ptype = ref.get("primary_type")
        sid = ref.get("secondary_id")
        stype = ref.get("secondary_type")
        target = f"{ptype}-{pid}" + (f" / {stype}={sid}" if sid else "")
        print(f"  {feature_name!r} {claim_key} → {name!r} (target: {target})")
    print()

    for claim_key in sorted(FOCUS_RESOLVE_CLAIM_KEYS):
        examples = unresolved_examples[claim_key]
        print(f"-- sample UNresolved {claim_key} refs ({len(examples)}) --")
        for bucket_key, name in examples:
            feature_name = names.get(int(bucket_key.split(":")[1]), "?")
            print(f"  {feature_name!r} → {name!r} (no map target)")
        print()

    print()
    print(
        f"-- sample parents with children ({min(args.limit, len(parents_with_children))}) --"
    )
    for bucket_key, child_ids in parents_with_children[: args.limit]:
        parent_fid = int(bucket_key.split(":")[1])
        parent_name = names.get(parent_fid, "?")
        sample_children = ", ".join(
            f"{names.get(cid, '?')} ({cid})" for cid in child_ids[:5]
        )
        more = "" if len(child_ids) <= 5 else f", … (+{len(child_ids) - 5})"
        print(
            f"  {parent_name!r} ({parent_fid}) [{len(child_ids)} children]: {sample_children}{more}"
        )

    # Reproducible-key sanity check: drawer fetch key is `bodyId:featureId`.
    assert feature_bucket_key(args.body_id, 1) == f"{args.body_id}:1"
    return 0


if __name__ == "__main__":
    sys.exit(main())
