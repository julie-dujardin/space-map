"""The sky-culture ingest: match each culture's objects to extrasolar IDs.

It reads the downloads of Stellarium desktop, Bucur's dataset and its SIMBAD
crosswalk, and the registry under its shared lock. It mints nothing and never
writes the registry. An export reads its output.

Writes, below derived/skycultures/:
- <dataset>/<culture>.json  the culture: its metadata, licence and sources,
  and `culture`, the published file with each object resolved (refs.py and
  resolve.py give the form)
- stellarium/common_star_names.json  Stellarium's international star names
- cultures.json  one entry per culture: name, region, licence tiers, counts
- report.txt     the counts of each culture, and every unresolved object

A file of an earlier run that this run does not write is deleted.
"""

import json
import logging
from collections import Counter
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from space_map_data.download.providers.skycultures import bucur, simbad, stellarium
from space_map_data.extrasolar.registry import Registry
from space_map_data.extrasolar.store import write_json
from space_map_data.skycultures import read
from space_map_data.skycultures.licences import read_licence
from space_map_data.skycultures.read import Culture
from space_map_data.skycultures.refs import (
    Ref,
    collect,
    map_objects,
    stellarium_name,
    stellarium_point,
)
from space_map_data.skycultures.resolve import (
    GAIA,
    HD,
    HIP,
    MATCHED,
    REASONS,
    Lookup,
    Matcher,
    SimbadCrosswalk,
    registry_ids,
    wanted,
)
from space_map_data.utils.paths import DERIVED_SKYCULTURES_DIR, REGISTRY_ROOT

logger = logging.getLogger(__name__)

INDEX_FILE = "cultures.json"
REPORT_FILE = "report.txt"
COMMON_NAMES = "common_star_names"
# The file states no licence. It is part of Stellarium, which is GPL-2.0.
COMMON_NAMES_LICENCE = "GNU GPL v2.0, the licence of Stellarium"
# The report lists the unresolved objects of a culture one by one up to this
# many, and counts them by designation beyond it.
LIST_LIMIT = 40


@dataclass
class Sources:
    stellarium: Path = stellarium.OUT_DIR
    bucur: Path = bucur.OUT_DIR
    simbad: Path = simbad.OUT_DIR


def _commit(directory: Path) -> str:
    return json.loads((directory / "metadata.json").read_text())["commit"]


def _record(culture: Culture, data: dict, matcher: Matcher, commit: str) -> dict:
    return {
        "dataset": culture.dataset,
        "key": culture.key,
        "name": culture.name,
        "region": culture.data.get("region"),
        "subregion": culture.data.get("subregion"),
        "source": {"commit": commit, "path": culture.path},
        "packaged": culture.packaged,
        "licence": culture.licence.as_dict(),
        "authors": culture.authors,
        "sources": culture.sources,
        "description": culture.description,
        "territory": culture.territory,
        "counts": matcher.summary(),
        "culture": data,
    }


def _summary(record: dict) -> dict:
    licence = record["licence"]
    return {
        "dataset": record["dataset"],
        "key": record["key"],
        "name": record["name"],
        "region": record["region"],
        "packaged": record["packaged"],
        "licence": [p["licence"] for p in licence["parts"]],
        "distribution": licence["distribution"],
        "illustrations_distribution": licence["illustrations_distribution"],
        "flags": licence["flags"],
        "file": f"{record['dataset']}/{record['key']}.json",
        "counts": {k: record["counts"][k] for k in ("refs", "matched", "unresolved")},
    }


def _report_lines(record: dict, unresolved: list[dict]) -> list[str]:
    counts = record["counts"]
    reasons = " · ".join(f"{k} {v:,}" for k, v in counts["unresolved"].items())
    lines = [
        f"{record['dataset']}/{record['key']}: {counts['refs']:,} refs,"
        f" {counts['matched']:,} matched" + (f"; {reasons}" if reasons else ""),
    ]
    if len(unresolved) <= LIST_LIMIT:
        lines += [
            f"    {u['place']}: {u['ref']!r} {u['reason']}"
            + (f" ({u['designation']})" if u.get("designation") else "")
            for u in unresolved
        ]
    else:
        by_ref = Counter((u["ref"], u["reason"]) for u in unresolved)
        lines.append(f"    {len(by_ref):,} distinct:")
        lines += [
            f"    {count:>4} × {ref!r} {reason}"
            for (ref, reason), count in sorted(by_ref.items())
        ]
    return lines


def _remove_stale(out_dir: Path, written: set[Path]) -> None:
    for path in sorted(out_dir.glob("*/*.json")):
        if path not in written:
            logger.info("removing %s, which this run does not write", path)
            path.unlink()


def ingest(
    registry_root: Path = REGISTRY_ROOT,
    out_dir: Path = DERIVED_SKYCULTURES_DIR,
    sources: Sources | None = None,
) -> str:
    """Match every culture and write the output; returns the report."""
    sources = sources or Sources()
    commits = {
        read.STELLARIUM: _commit(sources.stellarium),
        read.BUCUR: _commit(sources.bucur),
    }
    crosswalk_of = json.loads((sources.simbad / "metadata.json").read_text())
    if crosswalk_of["bucur_commit"] != commits[read.BUCUR]:
        raise ValueError(
            f"the SIMBAD crosswalk is for Bucur {crosswalk_of['bucur_commit']}, the"
            f" download is {commits[read.BUCUR]}: run skyculture_simbad again"
        )
    common = Culture(
        dataset=read.STELLARIUM,
        key=COMMON_NAMES,
        data=read.read_common_names(sources.stellarium),
        path=f"{stellarium.CULTURES_DIR}/{read.COMMON_NAMES_FILE}",
        name="International star names",
        licence=read_licence(COMMON_NAMES_LICENCE),
        sources=[],
        point=stellarium_point,
        name_ref=stellarium_name,
    )
    cultures = [
        *read.read_stellarium(sources.stellarium),
        *read.read_bucur(sources.bucur),
    ]
    crosswalk = SimbadCrosswalk.read(sources.simbad)
    refs: list[Ref] = [
        ref
        for culture in [common, *cultures]
        for ref, _ in collect(culture.data, culture.point, culture.name_ref)
    ]
    hips, gaias, hds = wanted(refs, crosswalk)
    registry = Registry(registry_root)
    with registry.reader():
        logger.info(
            "looking up %d HIP, %d Gaia DR3 and %d HD numbers",
            len(hips),
            len(gaias),
            len(hds),
        )
        lookup = Lookup(
            registry_ids(registry, HIP, hips),
            registry_ids(registry, GAIA, gaias),
            registry_ids(registry, HD, hds),
            crosswalk,
        )
        registry_ingest = registry.last_ingest
    logger.info(
        "registry ingest %d: IDs for %d of %d HIP, %d of %d Gaia DR3 and %d of %d"
        " HD numbers",
        registry_ingest,
        len(lookup.hip),
        len(hips),
        len(lookup.gaia),
        len(gaias),
        len(lookup.hd),
        len(hds),
    )

    written: set[Path] = set()
    index = []
    lines: list[str] = []
    totals: Counter = Counter()
    for culture in [common, *cultures]:
        matcher = Matcher(lookup)
        data = map_objects(culture.data, culture.point, culture.name_ref, matcher)
        record = _record(culture, data, matcher, commits[culture.dataset])
        path = out_dir / culture.dataset / f"{culture.key}.json"
        write_json(path, record)
        written.add(path)
        if culture is not common:
            index.append(_summary(record))
        culture_lines = _report_lines(record, matcher.unresolved)
        logger.info("%s", culture_lines[0])
        lines += culture_lines
        for (_, outcome), count in matcher.counts.items():
            totals[outcome] += count
    _remove_stale(out_dir, written)

    disagreements = lookup.disagreements()
    for line in disagreements:
        logger.warning("IDs disagree for %s", line)
    total = sum(totals.values())
    reasons = " · ".join(
        f"{k} {v:,}" for k, v in sorted(totals.items()) if k != MATCHED
    )
    report = [
        "Sky cultures",
        (
            f"registry ingest {registry_ingest}; Stellarium"
            f" {commits[read.STELLARIUM]}; Bucur {commits[read.BUCUR]}"
        ),
        (
            f"{len(cultures)} cultures and the international star names:"
            f" {total:,} refs, {totals[MATCHED]:,} matched; {reasons}"
        ),
        "",
        "reasons:",
        *(f"  {k}: {v}" for k, v in REASONS.items()),
        "",
        f"SIMBAD stars whose numbers give different IDs: {len(disagreements)}",
        *(f"  {line}" for line in disagreements),
        "",
        *lines,
    ]
    write_json(
        out_dir / INDEX_FILE,
        {
            "built_at": datetime.now(UTC).isoformat(),
            "registry_ingest": registry_ingest,
            "commits": commits,
            "reasons": REASONS,
            "cultures": index,
        },
    )
    text = "\n".join(report) + "\n"
    (out_dir / REPORT_FILE).write_text(text)
    return text
