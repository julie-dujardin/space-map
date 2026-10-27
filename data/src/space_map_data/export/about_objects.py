"""The objects table of `/about/data`: for each kind of object, how many the
export holds, the bytes they take, how many have text of their own in each
language, and where their data comes from.

Every figure is read off the files on disk, so a phase that the export skipped
as unchanged counts for what it left there. A gzip file can hold several
kinds. Its size is split between them by the raw bytes of their entries or rows.
"""

import gzip
import logging
import os
import zlib
from collections import Counter, defaultdict
from collections.abc import Iterable
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np
import orjson

from space_map_data.constants.providers import ID_TYPES, LANGUAGES
from space_map_data.export.objects.stars import PLANET_ID
from space_map_data.export.objects.stars import PREFIX as STAR_PREFIX
from space_map_data.export.position.format import (
    BODY_HEADER_SIZE,
    FORMAT_CHEBYSHEV,
    FORMAT_ELEMENTS,
    FORMAT_PROBES,
    HEADER_SIZE,
    ID_TYPE_ORDINAL,
    OBJECT_TYPE_ORDINAL,
    align8,
    unpack_body_header,
    unpack_chebyshev_header,
    unpack_elements_header,
)
from space_map_data.models.object import ObjectType

logger = logging.getLogger(__name__)

# The rows in the order of the page. A kind that is not listed follows by name.
KINDS = (
    "star",
    "extrasolar_star",
    "extrasolar_planet",
    "planet",
    "dwarf_planet",
    "moon",
    "asteroid",
    "comet",
    "ring_system",
    "surface_feature",
    "satellite",
    "probe",
    "debris",
    "barycenter",
)

_GLOBAL = "__global__"

# What a body's entry says about its rings. These bytes go to the ring systems.
_RING_KEYS = (
    "has_rings",
    "rings",
    "ring_features",
    "ring_sources",
    "ring_stats",
    "ring_images",
)
_LOCALIZED_RING_KEYS = ("ring_features", "ring_system")

# Blocks whose `sources` cite works by title and URL.
_WORK_BLOCKS = ("atmosphere", "temperatures", "interior", "activity", "radiation")

# A pole or a shape from a paper is a cited work.
_NAMED_FITS = ("occultation", "photometry")

_SATCAT_PREFIX = f"{ID_TYPES.NORAD_SATCAT}-"
_SATCAT_ORDINAL = ID_TYPE_ORDINAL[ID_TYPES.NORAD_SATCAT]
_TYPE_BY_ORDINAL = {ordinal: str(kind) for kind, ordinal in OBJECT_TYPE_ORDINAL.items()}


def kind_of(object_type: str, satcat: bool) -> str:
    """The row of an object. An Earth satellite has a NORAD id, a probe the id
    of the probe registry or of a hand-made object."""
    if object_type.startswith("asteroid"):
        return "asteroid"
    if object_type == ObjectType.spacecraft:
        return "satellite" if satcat else "probe"
    return object_type


def _entry_kind(object_id: str, object_type: str) -> str:
    """The row of an object entry. A star or a planet of the extrasolar
    catalogue has a row of its own: the catalogue holds many more of them than
    those with an entry."""
    if PLANET_ID.match(object_id):
        return "extrasolar_planet"
    if object_id.startswith(STAR_PREFIX):
        return "extrasolar_star"
    return kind_of(object_type, object_id.startswith(_SATCAT_PREFIX))


def has_own_text(entry: dict) -> bool:
    """True when a localized entry describes the object in its language. Names
    do not count. A missing label falls back to another language."""
    return "description" in entry or "wikipedia" in entry


def _field_bytes(entry: dict, keys: Iterable[str]) -> int:
    """Raw bytes of ``keys`` in ``entry``, with their names."""
    return sum(
        len(orjson.dumps(entry[key])) + len(key) + 4 for key in keys if key in entry
    )


def _entry_bytes(entry_id: str, entry: dict) -> int:
    """Raw bytes of an entry with its id."""
    return len(entry_id) + 3 + len(orjson.dumps(entry))


def _cited(works: set[str], sources: list[dict] | None) -> None:
    for source in sources or ():
        if source.get("url"):
            works.add(source["url"])


def entry_sources(entry: dict, works: set[str]) -> set[str]:
    """Sources of a global entry, by the keys of the object panel's source list.
    The URLs of the works it cites go into ``works``."""
    keys: set[str] = set()
    if archive := entry.get("ephemeris_source"):
        keys.add(archive)
    refs = entry.get("cross_refs") or {}
    if refs.get("wikidata_qid") or entry.get("wikidata"):
        keys.add("wikidata")
    if refs.get("mpc_designation"):
        keys.add("mpc")
    sbdb = entry.get("sbdb")
    if sbdb is not None:
        keys.add("sbdb")
    # The panel credits both catalogues for every Earth satellite.
    if entry.get("celestrak") is not None:
        keys.update(("celestrak", "jonathan"))
    if entry.get("johnston"):
        keys.add("johnston")
    if entry.get("astersat"):
        keys.add("nsdb")
    if entry.get("discovery_year") is not None:
        keys.add("jpl-satellite-discovery")
    if entry.get("color") or (sbdb or {}).get("color"):
        keys.add("truecolortools")
    if entry.get("images"):
        keys.add("commons")
    orientation = entry.get("orientation") or {}
    pole = orientation.get("source", "pck") if orientation else None
    if pole == "lightcurve":
        keys.add("damit")
    elif pole in _NAMED_FITS:
        _cited(works, [orientation.get("reference") or {}])
    elif pole is not None:
        keys.add("pck")
    if entry.get("radii"):
        if (entry.get("radii_source") or pole) in _NAMED_FITS:
            _cited(works, [entry.get("radii_reference") or {}])
        else:
            keys.add("pck")
    for taxonomy in (entry.get("interior") or {}).get("taxonomy_sources") or ():
        keys.add(f"taxonomy:{taxonomy}")
    for block in _WORK_BLOCKS:
        _cited(works, (entry.get(block) or {}).get("sources"))
    _cited(works, entry.get("position_sources"))
    return keys


class _Tally:
    """What each row adds up, kind by kind."""

    def __init__(self) -> None:
        self.count: Counter[str] = Counter()
        self.detail_bytes: defaultdict[str, float] = defaultdict(float)
        self.position_bytes: defaultdict[str, float] = defaultdict(float)
        self.localized: dict[str, Counter[str]] = {
            lang: Counter() for lang in LANGUAGES
        }
        self.any_localized: defaultdict[str, set] = defaultdict(set)
        self.wikipedia: defaultdict[str, set] = defaultdict(set)
        self.sources: defaultdict[str, Counter[str]] = defaultdict(Counter)
        self.works: defaultdict[str, set[str]] = defaultdict(set)
        self.systems = 0

    def text(self, lang: str, kind: str, key, wikipedia: bool) -> None:
        """Count an item that has text of its own in ``lang``."""
        self.localized[lang][kind] += 1
        self.any_localized[kind].add(key)
        if wikipedia:
            self.wikipedia[kind].add(key)

    def row(self, kind: str) -> dict:
        sources = self.sources[kind]
        if self.wikipedia[kind]:
            sources["wikipedia"] = len(self.wikipedia[kind])
        position = round(self.position_bytes[kind])
        row: dict = {
            "id": kind,
            "count": self.count[kind],
            "size_bytes": round(self.detail_bytes[kind]) + position,
        }
        if position:
            row["position_bytes"] = position
        row["localized"] = {lang: self.localized[lang][kind] for lang in LANGUAGES}
        row["localized"]["any"] = len(self.any_localized[kind])
        row["sources"] = [
            {"key": key, "objects": objects}
            for key, objects in sorted(
                sources.items(), key=lambda item: (-item[1], item[0])
            )
        ]
        if self.works[kind]:
            row["works"] = len(self.works[kind])
        if kind == "ring_system":
            row["systems"] = self.systems
        return row


def _bundle(path: Path) -> tuple[int, dict]:
    """The gzip size of a bundle, and its entries."""
    packed = path.read_bytes()
    return len(packed), orjson.loads(gzip.decompress(packed))


def _spread(target: defaultdict[str, float], size: int, raw: Counter[str]) -> None:
    """Add ``size`` bytes to ``target`` in the shares of ``raw``."""
    total = raw.total()
    for kind, n in raw.items():
        target[kind] += size * n / total


def _buckets(directory: Path) -> list[Path]:
    return sorted(directory.glob("*.json.gz")) if directory.is_dir() else []


def _ring_system(tally: _Tally, entry: dict) -> None:
    """The catalogued rings, gaps and arcs of a body."""
    features = entry["ring_features"]
    tally.systems += 1
    tally.count["ring_system"] += len(features)
    sources = tally.sources["ring_system"]
    sources["wikidata"] += sum(
        1 for feature in features.values() if feature.get("wikidata_qid")
    )
    if entry.get("ring_images"):
        sources["commons"] += len(features)
    _cited(tally.works["ring_system"], entry.get("ring_sources"))


def _scan_objects(objects_dir: Path, tally: _Tally) -> None:
    """The object bundles. The global entries come first because they give
    each id its kind."""
    kinds: dict[str, str] = {}
    for path in _buckets(objects_dir / _GLOBAL):
        size, entries = _bundle(path)
        raw: Counter[str] = Counter()
        for object_id, entry in entries.items():
            kind = _entry_kind(object_id, entry["type"])
            kinds[object_id] = kind
            tally.count[kind] += 1
            rings = _field_bytes(entry, _RING_KEYS)
            raw[kind] += _entry_bytes(object_id, entry) - rings
            raw["ring_system"] += rings
            sources = tally.sources[kind]
            for key in entry_sources(entry, tally.works[kind]):
                sources[key] += 1
            if entry.get("ring_features"):
                _ring_system(tally, entry)
        _spread(tally.detail_bytes, size, raw)
    unknown = 0
    for lang in LANGUAGES:
        for path in _buckets(objects_dir / lang):
            size, entries = _bundle(path)
            raw = Counter()
            for object_id, entry in entries.items():
                kind = kinds.get(object_id)
                if kind is None:
                    unknown += 1
                    continue
                rings = _field_bytes(entry, _LOCALIZED_RING_KEYS)
                raw[kind] += _entry_bytes(object_id, entry) - rings
                raw["ring_system"] += rings
                if has_own_text(entry):
                    tally.text(lang, kind, object_id, "wikipedia" in entry)
                # A ring feature has an article when it has a link or an extract.
                for slug, feature in (entry.get("ring_features") or {}).items():
                    if "extract" in feature or "url" in feature:
                        tally.text(lang, "ring_system", (object_id, slug), True)
            _spread(tally.detail_bytes, size, raw)
    if unknown:
        logger.warning("%d localized object entries have no global entry", unknown)


def _element_kinds(buf: bytes) -> Counter[str]:
    """Rows of an elements file by kind. Every row has the same width."""
    header = unpack_elements_header(buf)
    n = header.row_count
    types = np.frombuffer(buf, np.uint8, n, HEADER_SIZE + align8(4 * n))
    satcat = header.id_type == _SATCAT_ORDINAL
    out: Counter[str] = Counter()
    for ordinal, rows in enumerate(np.bincount(types, minlength=256).tolist()):
        if rows:
            out[kind_of(_TYPE_BY_ORDINAL.get(ordinal, "undocumented"), satcat)] += rows
    return out


def _chebyshev_kinds(buf: bytes) -> Counter[str]:
    """Raw bytes of a chebyshev file by kind, body by body."""
    header = unpack_chebyshev_header(buf)
    coeff_size = 8 if header.float64_coeffs else 4
    out: Counter[str] = Counter()
    offset = HEADER_SIZE
    for _ in range(header.body_count):
        body = unpack_body_header(buf, offset)
        size = BODY_HEADER_SIZE + body.segment_count * (
            16 + 3 * body.coeffs_per_axis * coeff_size
        )
        object_type = _TYPE_BY_ORDINAL.get(body.object_type, "undocumented")
        out[kind_of(object_type, body.id_type == _SATCAT_ORDINAL)] += size
        offset += size
    return out


def position_file_bytes(path: Path) -> defaultdict[str, float]:
    """The gzip bytes of a position file, split by kind."""
    packed = path.read_bytes()
    head = zlib.decompressobj(31).decompress(packed, HEADER_SIZE)
    file_format = head[6]
    split: defaultdict[str, float] = defaultdict(float)
    # Its writer gives every record of a probes file the probe id type.
    if file_format == FORMAT_PROBES:
        split["probe"] = len(packed)
        return split
    buf = gzip.decompress(packed)
    if file_format == FORMAT_ELEMENTS:
        raw = _element_kinds(buf)
    elif file_format == FORMAT_CHEBYSHEV:
        raw = _chebyshev_kinds(buf)
    else:
        logger.warning("%s has an unknown position format %d", path, file_format)
        return split
    _spread(split, len(packed), raw)
    return split


def _scan_positions(position_dir: Path, tally: _Tally) -> None:
    files = sorted(position_dir.rglob("*.bin.gz")) if position_dir.is_dir() else []
    # zlib releases the GIL, so threads use all cores.
    with ThreadPoolExecutor(max_workers=os.cpu_count()) as pool:
        for split in pool.map(position_file_bytes, files, chunksize=16):
            for kind, size in split.items():
                tally.position_bytes[kind] += size


def _scan_features(nomenclature_dir: Path, tally: _Tally) -> None:
    """The surface features. A body's label file has one line per feature."""
    if not nomenclature_dir.is_dir():
        return
    kind = "surface_feature"
    for path in nomenclature_dir.rglob("*"):
        if path.is_file():
            target = (
                tally.position_bytes
                if path.parent.name == "positions"
                else tally.detail_bytes
            )
            target[kind] += path.stat().st_size
    for path in sorted((nomenclature_dir / "labels" / "en").glob("*.txt.gz")):
        text = gzip.decompress(path.read_bytes())
        tally.count[kind] += len(text.splitlines())
    sources = tally.sources[kind]
    sources["iau-naming"] = tally.count[kind]
    for path in _buckets(nomenclature_dir / "details" / _GLOBAL):
        for entry in _bundle(path)[1].values():
            if entry.get("wikidata_qid"):
                sources["wikidata"] += 1
            if entry.get("images"):
                sources["commons"] += 1
    for lang in LANGUAGES:
        for path in _buckets(nomenclature_dir / "details" / lang):
            for feature_id, entry in _bundle(path)[1].items():
                if has_own_text(entry):
                    tally.text(lang, kind, feature_id, "wikipedia" in entry)


def _ordered(kinds: Iterable[str]) -> list[str]:
    listed = [kind for kind in KINDS if kind in kinds]
    return listed + sorted(set(kinds) - set(KINDS))


def object_rows(out_dir: Path) -> list[dict]:
    """One row for each kind of object in the export at ``out_dir``."""
    tally = _Tally()
    _scan_objects(out_dir / "objects", tally)
    _scan_positions(out_dir / "position", tally)
    _scan_features(out_dir / "nomenclature", tally)
    kinds = {kind for kind, n in tally.count.items() if n} | {
        kind for kind, n in tally.position_bytes.items() if n
    }
    for kind in kinds - set(tally.count):
        logger.warning("Position files hold %s rows that no bundle lists", kind)
    return [tally.row(kind) for kind in _ordered(kinds)]
