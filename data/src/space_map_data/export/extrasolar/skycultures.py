"""The sky cultures of the extrasolar export, one JSON file per culture.

The input is the matched cultures that `space-map-ingest` writes at the end of
the extrasolar target, or with `--targets skycultures`. A culture
file holds its figures, the members that the figures and the star names point
to, and the star names. A member is a star with its ID and its position in the
frame of the render tree, or an object with no ID, kept with its reference so
that no line is cut. The position comes from `render.render_rows`, run over
the whole Point source region as the tree build runs it, so a line ends on
the rendered star. A star that the tree does not draw keeps its ID and has no
position.

All files share one directory. A Bucur culture that has the key of a
Stellarium culture, or that is a copy of one under another key, is left out,
and `select` logs why.

A file is JSON in gzip. Its `token` field holds the token of the table. The
token hashes each file with 16 zeros in that field, as a container token
hashes a payload with a zero token.
"""

import gzip
import hashlib
import html
import json
import logging
from collections.abc import Iterable
from dataclasses import dataclass
from itertools import pairwise
from pathlib import Path
from urllib.parse import quote

import numpy as np

from space_map_data.export.extrasolar import container, render
from space_map_data.export.extrasolar.container import Written
from space_map_data.export.extrasolar.skyculture_authors import AUTHORS
from space_map_data.extrasolar.ids import cell_of
from space_map_data.extrasolar.registry import Registry
from space_map_data.extrasolar.sky import region_of
from space_map_data.skycultures.build import COMMON_NAMES, INDEX_FILE
from space_map_data.skycultures.licences import NON_COMMERCIAL, OPEN, UNDECIDED
from space_map_data.utils.paths import DERIVED_SKYCULTURES_DIR

logger = logging.getLogger(__name__)

TABLE = "skycultures"
STELLARIUM = "stellarium"
# A Bucur culture is a copy of a Stellarium one when they share at least
# SAME_SEGMENTS of their line segments (Jaccard), and the Stellarium one has
# at least SAME_NAMES of the Bucur figure names.
SAME_SEGMENTS = 0.5
SAME_NAMES = 0.5
# The matched cultures that the export reads.
CULTURES_DIR = DERIVED_SKYCULTURES_DIR
ZERO_TOKEN = "0" * container.TOKEN_SIZE
# The name fields a figure or a star name keeps.
NAME_FIELDS = ("native", "english", "pronounce", "transliteration", "IPA")
# The tiers from the most open; an unknown tier is never served.
LADDER = (OPEN, NON_COMMERCIAL, "site-only")
DATASET_URLS = {
    "stellarium": "https://github.com/Stellarium/stellarium",
    "bucur": "https://github.com/doinab/constellation-lines",
}
CREDITS = (
    {
        "name": "Stellarium sky cultures",
        "organisation": "Stellarium",
        "source": "https://github.com/Stellarium/stellarium/tree/master/skycultures",
    },
    {
        "name": "Constellation line figures in sky cultures across the world",
        "organisation": "Doina Bucur",
        "source": "https://github.com/doinab/constellation-lines",
        "license": "CC BY-SA",
    },
    {
        "name": "SIMBAD astronomical database",
        "organisation": "CDS, Strasbourg Astronomical Observatory, France",
        "source": "https://simbad.cds.unistra.fr/simbad/",
        "license": "ODbL",
        "attribution": "This research has made use of the SIMBAD database,"
        " operated at CDS, Strasbourg, France.",
        "citation": "Wenger et al. 2000, A&AS 143, 9",
    },
)


def path_of(key: str) -> str:
    return f"{TABLE}/{key}.json.gz"


def segments(record: dict) -> set[frozenset]:
    """The line segments of a matched culture, each a pair of points."""
    found = set()
    for kind in ("constellations", "asterisms"):
        for figure in record["culture"].get(kind, []):
            for chain in figure.get("lines", []):
                points = [
                    p if isinstance(p, int) else json.dumps(p, sort_keys=True)
                    for p in chain
                ]
                found.update(frozenset(s) for s in pairwise(points) if s[0] != s[1])
    return found


def figure_names(record: dict) -> set[str]:
    """The English and native names of the figures of a matched culture."""
    found = set()
    for kind in ("constellations", "asterisms"):
        for figure in record["culture"].get(kind, []):
            names = figure.get("names") or [figure.get("common_name") or {}]
            for name in names:
                for field in ("english", "native"):
                    if isinstance(name.get(field), str) and name[field].strip():
                        found.add(name[field].strip().casefold())
    return found


def same_culture(bucur: dict, stellarium: dict) -> tuple[float, float]:
    """The share of segments the two cultures share (Jaccard), and the share
    of the Bucur figure names that the Stellarium one also has."""
    a, b = segments(bucur), segments(stellarium)
    names = figure_names(bucur)
    shared_segments = len(a & b) / len(a | b) if a | b else 0.0
    shared_names = len(names & figure_names(stellarium)) / len(names) if names else 0.0
    return shared_segments, shared_names


def select(records: list[dict]) -> tuple[list[dict], list[str]]:
    """The records to export, and why each other one is left out.

    The files share one directory, so Stellarium's culture wins a key that
    Bucur also uses, in any case. A Bucur culture that is a copy of a
    Stellarium one under another key is left out too.
    """
    stellarium = [r for r in records if r["dataset"] == STELLARIUM]
    stellarium_keys = {r["key"].casefold() for r in stellarium} | {COMMON_NAMES}
    taken = set(stellarium_keys)
    kept, left_out = list(stellarium), []
    for record in records:
        if record["dataset"] == STELLARIUM:
            continue
        name = f"{record['dataset']}/{record['key']}"
        key = record["key"].casefold()
        if key in stellarium_keys:
            left_out.append(f"{name}: Stellarium has the key {record['key']}")
            continue
        if key in taken:
            left_out.append(f"{name}: another culture has the key {record['key']}")
            continue
        copies = []
        for other in stellarium:
            shared_segments, shared_names = same_culture(record, other)
            if shared_segments >= SAME_SEGMENTS and shared_names >= SAME_NAMES:
                copies.append(
                    f"{name}: a copy of stellarium/{other['key']}, sharing"
                    f" {shared_segments:.2f} of the segments and {shared_names:.2f}"
                    " of the figure names"
                )
        if copies:
            left_out.append(copies[0])
            continue
        taken.add(key)
        kept.append(record)
    for line in left_out:
        logger.info("sky cultures: left out %s", line)
    return kept, left_out


def combined(*tiers: str) -> str:
    """The tier that every one of `tiers` allows; undecided when one is unknown."""
    if any(t not in LADDER for t in tiers):
        return UNDECIDED
    return max(tiers, key=LADDER.index)


def check(registry: Registry, cultures_dir: Path) -> str | None:
    """Why the matched cultures cannot be exported, or None.

    The IDs of the cultures are those of one registry state, so they must
    come from the ingest that the export reads.
    """
    index = cultures_dir / INDEX_FILE
    if not index.exists():
        return None
    matched = json.loads(index.read_text())["registry_ingest"]
    if matched != registry.last_ingest:
        return (
            f"the sky cultures match registry ingest {matched}, the registry is at"
            f" {registry.last_ingest}: run space-map-ingest --targets skycultures"
        )
    return None


class Members:
    """The distinct objects of one culture, in order of first use."""

    def __init__(self) -> None:
        self.entries: list[dict] = []
        self._index: dict[tuple, int] = {}

    def add(self, point: object) -> int:
        if isinstance(point, int):
            key: tuple = ("id", point)
            entry: dict = {"id": point}
        elif isinstance(point, list):
            key = ("sky", *point)
            entry = {"ra_hours": point[0], "dec": point[1]}
        elif isinstance(point, dict):
            key = ("ref", point["ref"], point["reason"])
            entry = {
                k: point[k] for k in ("ref", "reason", "designation") if k in point
            }
        else:
            raise TypeError(f"not a culture point: {point!r}")
        if key not in self._index:
            self._index[key] = len(self.entries)
            self.entries.append(entry)
        return self._index[key]

    def ids(self) -> list[int]:
        return [entry["id"] for entry in self.entries if "id" in entry]


def _names(names: Iterable[dict]) -> list[dict]:
    out = []
    for name in names:
        kept = {k: name[k] for k in NAME_FIELDS if isinstance(name.get(k), str)}
        if kept:
            out.append(kept)
    return out


def _figure(figure: dict, kind: str, members: Members) -> dict:
    names = figure.get("names") or (
        [figure["common_name"]] if "common_name" in figure else []
    )
    out: dict = {"id": figure["id"], "kind": kind, "names": _names(names)}
    out["lines"] = [
        [members.add(point) for point in chain] for chain in figure.get("lines", [])
    ]
    if "group" in figure:
        out["group"] = [members.add(point) for point in figure["group"]]
    if "IAU" in figure:
        out["iau"] = figure["IAU"]
    if figure.get("is_ray_helper"):
        out["ray_helper"] = True
    return out


def layout(record: dict) -> tuple[dict, Members]:
    """The file content of a matched culture, without positions."""
    culture = record["culture"]
    members = Members()
    figures = [
        _figure(figure, kind, members)
        for key, kind in (
            ("constellations", "constellation"),
            ("asterisms", "asterism"),
        )
        for figure in culture.get(key, [])
    ]
    names = [
        {"member": members.add(entry["object"]), "names": _names(entry["names"])}
        for entry in culture.get("common_names", [])
    ]
    content = {
        "token": ZERO_TOKEN,
        "dataset": record["dataset"],
        "key": record["key"],
        "name": record["name"],
        "members": members.entries,
        "figures": figures,
        "names": names,
    }
    return content, members


def positions(registry: Registry, ids: Iterable[int]) -> dict[int, list[float]]:
    """The render-tree position (pc) of each ID that the tree draws.

    Each region is rendered whole, as `render.region_rows` renders it, so the
    float64 positions are the tree's.
    """
    wanted = np.unique(np.fromiter(ids, np.int64))
    found: dict[int, list[float]] = {}
    regions = region_of(cell_of(wanted))
    for region in np.unique(regions).tolist():
        rows, _ = render.render_rows(render.region_table(registry, region))
        hit = np.isin(rows["id"], wanted[regions == region])
        for id_, x, y, z in zip(
            rows["id"][hit].tolist(),
            rows["x"][hit].tolist(),
            rows["y"][hit].tolist(),
            rows["z"][hit].tolist(),
        ):
            found[id_] = [x, y, z]
    return found


def _letters(text: str) -> str:
    return "".join(ch for ch in text.casefold() if ch.isalnum())


def authors(record: dict) -> list[str]:
    """The plain author names of a Stellarium culture that its Authors section
    still holds. Bucur's cultures credit the dataset."""
    if record["dataset"] != STELLARIUM:
        return []
    names = AUTHORS.get(record["key"])
    if names is None:
        logger.warning("%s: no author names, so its credit has none", record["key"])
        return []
    text = _letters(html.unescape(record.get("authors") or ""))
    found = [name for name in names if _letters(name) in text]
    for name in names:
        if name not in found:
            logger.warning(
                "%s: %r is not in its Authors section, so its credit leaves it out",
                record["key"],
                name,
            )
    return found


def _payload(content: dict) -> bytes:
    return (
        json.dumps(content, ensure_ascii=False, separators=(",", ":")) + "\n"
    ).encode()


@dataclass
class Result:
    files: list[Written]
    entry: dict
    # Each culture left out, and why.
    left_out: list[str]


def _entry(record: dict, content: dict, path: str) -> dict:
    licence = record["licence"]
    parts = [
        p["licence"]
        if p["applies_to"] == "all"
        else f"{p['licence']} ({p['applies_to']})"
        for p in licence["parts"]
    ]
    stellarium = record["dataset"] == STELLARIUM
    # A Stellarium culture is a directory, a Bucur culture one file.
    view = "tree" if stellarium else "blob"
    credit = {
        "name": record["name"],
        "organisation": "Stellarium" if stellarium else "Doina Bucur",
        "source": (
            f"{DATASET_URLS[record['dataset']]}/{view}/{record['source']['commit']}"
            f"/{quote(record['source']['path'])}"
        ),
        "license": "; ".join(parts) or "none stated",
    }
    names = authors(record)
    if names:
        credit["authors"] = names
    members = content["members"]
    return {
        "dataset": record["dataset"],
        "key": record["key"],
        "name": record["name"],
        "region": record["region"],
        "subregion": record.get("subregion"),
        "packaged": record["packaged"],
        "fallback_to_international_names": bool(
            record["culture"].get("fallback_to_international_names")
        ),
        "file": path,
        "licence": {"parts": licence["parts"], "distribution": licence["distribution"]},
        "distribution": combined(licence["distribution"], NON_COMMERCIAL),
        "flags": licence["flags"],
        "credit": credit,
        "figures": len(content["figures"]),
        "members": len(members),
        "positioned": sum(1 for m in members if "position" in m),
        "unresolved": sum(1 for m in members if "ref" in m),
    }


def build(
    registry: Registry, out: Path, cultures_dir: Path | None = None
) -> Result | None:
    """Write the culture files below `out` with their token, or None with no input.

    The returned entry goes to `skycultures` in metadata.json.
    """
    cultures_dir = cultures_dir or CULTURES_DIR
    index_file = cultures_dir / INDEX_FILE
    if not index_file.exists():
        logger.warning("no matched sky cultures at %s: the export has none", index_file)
        return None
    index = json.loads(index_file.read_text())
    records, left_out = select(
        [
            json.loads((cultures_dir / entry["file"]).read_text())
            for entry in index["cultures"]
        ]
    )
    common = json.loads(
        (cultures_dir / "stellarium" / f"{COMMON_NAMES}.json").read_text()
    )

    laid_out = [layout(record) for record in (*records, common)]
    ids = {id_ for _, members in laid_out for id_ in members.ids()}
    logger.info("sky cultures: positions of %d stars", len(ids))
    found = positions(registry, ids)
    logger.info(
        "sky cultures: %d of %d stars are in the render tree", len(found), len(ids)
    )
    contents = []
    for content, members in laid_out:
        for entry in members.entries:
            if "id" in entry and entry["id"] in found:
                entry["position"] = found[entry["id"]]
        contents.append(content)
    unplaced = sorted(ids - set(found))
    logger.debug("sky cultures: stars that the tree does not draw: %s", unplaced)

    paths = [path_of(c["key"]) for c in contents]
    digests = [hashlib.sha256(_payload(c)).digest() for c in contents]
    token = container.token_of(
        [Written(path, digest, 0, 0) for path, digest in zip(paths, digests)]
    )
    written = []
    for path, digest, content in zip(paths, digests, contents):
        content["token"] = token
        data = gzip.compress(_payload(content), compresslevel=9, mtime=0)
        target = out / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
        written.append(Written(path, digest, len(content["members"]), len(data)))

    cultures = [
        _entry(record, content, path)
        for record, content, path in zip(records, contents, paths)
    ]
    entry = {
        "token": token,
        "file": path_of("{key}"),
        "international_names": paths[-1],
        "international_names_distribution": combined(
            common["licence"]["distribution"], NON_COMMERCIAL
        ),
        "units": "pc",
        "commits": index["commits"],
        "cultures": cultures,
        "credits": list(CREDITS),
    }
    return Result(written, entry, left_out)
