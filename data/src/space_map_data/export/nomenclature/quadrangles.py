"""Per-body IAU quadrangle index: ``v1/nomenclature/quadrangles.json.gz``.

One small file covering every mapped body (Mercury, Venus, Mars, the Moon) —
the Surface tab's hero draws these boxes over the body's map texture and uses
them to narrow the feature list.

Boxes come from ``constants.nomenclature.quadrangle_grid``; names and counts
come from the gazetteer. Where the IAU's own ``quad_code`` disagrees with the
grid — a handful of classical Mars albedo features centred exactly on a cell
edge — the gazetteer wins and the feature rides in ``overrides`` so the search
index can reproduce the same assignment.

Per-language Wikipedia extracts for the mapped charts sit beside the geometry
as ``{lang}.json.gz``, fetched only once a chart is picked.
"""

import gzip
import logging
from collections import defaultdict
from pathlib import Path

import orjson
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from space_map_data.constants.nomenclature.quadrangle_grid import (
    QUADRANGLES,
    quadrangle_for,
)
from space_map_data.constants.nomenclature.quadrangles import QUADRANGLE_QIDS
from space_map_data.export.objects.wikipedia import load_wikipedia_summaries_for_qid
from space_map_data.export.nomenclature.writer import renderable_feature_filter
from space_map_data.models.feature import Feature
from space_map_data.utils.paths import EXPORT_DIR

logger = logging.getLogger(__name__)

QUADRANGLE_DIR = "quadrangles"
GLOBAL_FILE = "__global__.json.gz"


def build_quadrangles(session: Session) -> dict[str, dict]:
    """Assemble the per-body quadrangle payload from the features table."""
    rows = (
        session.query(
            Feature.feature_id,
            Feature.object_id,
            Feature.quad_code,
            Feature.quad_name,
            Feature.center_lat,
            Feature.center_lon,
        )
        .filter(*renderable_feature_filter())
        .filter(Feature.object_id.in_(list(QUADRANGLES)))
        .all()
    )

    names: dict[str, dict[str, str]] = defaultdict(dict)
    counts: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    overrides: dict[str, dict[str, str]] = defaultdict(dict)
    unmapped = 0
    for feature_id, body_id, code, name, lat, lon in rows:
        derived = quadrangle_for(body_id, lat, lon)
        if not code:
            # No gazetteer assignment — the grid still places it, so the hero's
            # counts stay complete.
            if derived:
                counts[body_id][derived] += 1
            else:
                unmapped += 1
            continue
        counts[body_id][code] += 1
        if name:
            names[body_id][code] = name
        if derived != code:
            overrides[body_id][str(feature_id)] = code

    if unmapped:
        logger.warning(
            "%d feature(s) on quadrangle-mapped bodies fell outside every cell "
            "— excluded from the quadrangle index",
            unmapped,
        )
    diverged = sum(len(v) for v in overrides.values())
    if diverged:
        logger.info(
            "%d feature(s) sit exactly on a quadrangle edge — gazetteer "
            "assignment kept as an override",
            diverged,
        )

    out: dict[str, dict] = {}
    for body_id, quads in QUADRANGLES.items():
        body_counts = counts.get(body_id, {})
        if not body_counts:
            logger.warning("No quadrangle features for %s — body skipped", body_id)
            continue
        out[body_id] = {
            "quads": [
                {
                    "code": q.code,
                    "name": names.get(body_id, {}).get(q.code, q.code),
                    "n": body_counts.get(q.code, 0),
                    "lat_min": q.lat_min,
                    "lat_max": q.lat_max,
                    "lon_min": round(q.lon_min, 4),
                    "lon_span": round(q.lon_span, 4),
                }
                for q in quads
            ],
            "overrides": overrides.get(body_id, {}),
        }
    return out


def build_quadrangle_texts() -> dict[str, dict[str, dict]]:
    """``{lang: {"<body>:<code>": {extract, url}}}`` from the mapped charts'
    Wikipedia articles. Only Mercury, Venus and Mars charts carry a QID — the
    Moon's LAC sheets aren't on Wikipedia."""
    out: dict[str, dict[str, dict]] = {}
    for (body_id, code), qid in QUADRANGLE_QIDS.items():
        for lang, summary in load_wikipedia_summaries_for_qid(qid).items():
            if not summary.extract:
                continue
            out.setdefault(lang, {})[f"{body_id}:{code}"] = {
                "extract": summary.extract,
                **({"url": summary.url} if summary.url else {}),
            }
    missing = len(QUADRANGLE_QIDS) - len(out.get("en", {}))
    if missing > 0:
        logger.info("%d quadrangle(s) have no English Wikipedia extract", missing)
    return out


def write_quadrangles(
    out_dir: Path,
    payload: dict[str, dict],
    texts: dict[str, dict[str, dict]] | None = None,
) -> None:
    """Write the quadrangle index under ``out_dir/nomenclature/quadrangles``."""
    if not payload:
        logger.info("No quadrangle data to export")
        return
    target = out_dir / "nomenclature" / QUADRANGLE_DIR
    target.mkdir(parents=True, exist_ok=True)
    (target / GLOBAL_FILE).write_bytes(gzip.compress(orjson.dumps(payload)))
    for lang, entries in (texts or {}).items():
        (target / f"{lang}.json.gz").write_bytes(gzip.compress(orjson.dumps(entries)))
    logger.info(
        "Wrote quadrangle index for %d bodies (%d quadrangles, %d languages of text)",
        len(payload),
        sum(len(b["quads"]) for b in payload.values()),
        len(texts or {}),
    )


def export_quadrangles_only(engine: Engine) -> None:
    """Additive run: rewrite just the quadrangle index."""
    out_dir = EXPORT_DIR / "v1"
    if not out_dir.exists():
        raise SystemExit(f"Export dir {out_dir} missing — run a full export first.")
    with Session(engine) as session:
        write_quadrangles(out_dir, build_quadrangles(session), build_quadrangle_texts())


def load_quadrangles(export_dir: Path) -> dict[str, dict]:
    """Read the exported quadrangle index, or {} when it hasn't been written."""
    path = export_dir / "v1" / "nomenclature" / QUADRANGLE_DIR / GLOBAL_FILE
    if not path.exists():
        logger.warning("No quadrangle index at %s", path)
        return {}
    data: dict[str, dict] = orjson.loads(gzip.decompress(path.read_bytes()))
    return data
