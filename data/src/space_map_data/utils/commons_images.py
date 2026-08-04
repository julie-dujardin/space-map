"""Shared helpers for Commons-hosted image files.

Used by:
- download/providers/images/commons.py — decide what to download, write metadata
- ingest/providers/image_selection.py — pick best per object, set ``image_available``
- export/images.py — emit per-object image lists and generate thumbnails

The on-disk layout after download is::

    IMAGES_DIR/<filename>/source.<ext>    # the source image bytes
    IMAGES_DIR/<filename>/metadata.json   # Commons imageinfo + license_servable

``<filename>`` is the full canonical Commons filename (underscore form, including
extension) — it is the stable Commons identity.
"""

import json
import logging
import re
from pathlib import Path
from urllib.parse import unquote, urlparse

import orjson

from space_map_data.constants.providers import LANGUAGES
from space_map_data.utils.paths import SOURCES_IMAGES_DIR, SOURCES_METADATA_DIR

logger = logging.getLogger(__name__)


COMMONS_DIR = SOURCES_IMAGES_DIR / "commons"
IMAGES_DIR = COMMONS_DIR / "images"
MANUAL_EXTRA_PATH = COMMONS_DIR / "manual-extra.json"

_WIKIDATA_IMAGE_PIDS = ("P18", "P154")
# P18 photo + P242 locator map (USGS-style IAU feature outline). Logo (P154)
# isn't meaningful for surface features.
FEATURE_WIKIDATA_IMAGE_PIDS = ("P18", "P242")
# Auto-generated orbit diagrams on ru.wiki that flood the pageimages set.
EXCLUDED_FILENAME_PREFIXES = ("Орбита_астероида_", "Орбита_кометы_")

# Filename signals for images whose Commons categories don't reliably mark them
# as noise. Orbit-viewer/diagram renders are categorised by depicted body, and
# the position/size comparison-diagram families below (many language variants)
# are categorised by the bodies they show, not as diagrams — so only the
# filename gives them away. Matched case-insensitively.
_ORBIT_FILENAME_SUBSTRINGS = (
    "orbit-viewer-snapshot",
    "orbital_diagram",
    "orbit_diagram",
)
_DIAGRAM_FILENAME_PREFIXES = ("innersolarsystem", "outersolarsystem", "eighttnos")

# Diagrams of a *subject the app draws itself* — ring cutaways, belt maps, moon
# line-ups, orbit schematics. Dropped only for those subjects (see
# ``drop_subject_diagrams``), never for spacecraft, whose schematics are often
# the only illustration that exists.
#
# Two signals, because neither covers the family alone. The category one catches
# the translated sets, whose uploads are tagged by the language of the text
# baked into them; the filename one catches the diagrams that carry no category
# beyond the body they depict (Commons files the uploader only filed under
# "Uranus (rings)"). "annotated" is a prefix rather than a substring: it marks a
# photograph relabelled in one language, and only ever leads a filename.
_SUBJECT_DIAGRAM_FILENAME_SUBSTRINGS = ("scheme", "schema", "esquema", "schematic")
_SUBJECT_DIAGRAM_FILENAME_PREFIXES = ("annotated",)
_LANGUAGE_DIAGRAM_CATEGORY = re.compile(r"-language (svg )?diagrams$")

# Small-body radar / shape-model render categories. These get tagged
# (kind="radar") rather than dropped so they stay visible until 3D shape
# rendering replaces them. Planetary surface radar maps (Magellan/Venus,
# Cassini/Titan) are deliberately absent — those are real surface imagery.
_RADAR_CATEGORIES = frozenset(
    {
        "radar images of asteroids",
        "radar images of near-earth objects",
        "arecibo telescope radar images",
        "radar-imaged asteroids",
    }
)

# License tags we refuse to serve. Matched case-insensitively as substrings of
# ``extmetadata.LicenseShortName`` (and of each segment of a multi-license
# "A or B or C" string).
_DENIED_LICENSE_KEYWORDS = (
    "fair use",
    "non-free",
    "all rights reserved",
    "cc by-nc",
    "cc-by-nc",
    "cc by-nd",
    "cc-by-nd",
)


def canonical_filename(filename: str) -> str:
    """Normalize a Commons filename to its MediaWiki canonical (underscore) form.

    MediaWiki treats spaces and underscores as equivalent in page titles and
    always stores the underscore form internally. Callers mix space-form (from
    Wikidata claim values) and underscore-form (from parsed URL paths), which
    would otherwise produce duplicate downloads/queries for the same file.
    """
    return filename.replace(" ", "_")


def is_excluded(filename: str) -> bool:
    """Skip-list check for known-noise filename prefixes."""
    return any(filename.startswith(p) for p in EXCLUDED_FILENAME_PREFIXES)


def _image_categories(metadata: dict | None) -> list[str]:
    """Pipe-split ``extmetadata.Categories`` for a downloaded image, or ``[]``.

    Present on ~99.8% of Commons files — a far more reliable classifier than
    filenames.
    """
    if not metadata:
        return []
    em = (metadata.get("imageinfo") or {}).get("extmetadata") or {}
    raw = (em.get("Categories") or {}).get("value")
    if not isinstance(raw, str):
        return []
    return [c.strip() for c in raw.split("|") if c.strip()]


def image_exclusion_reason(
    filename: str,
    metadata: dict | None,
    *,
    drop_locator_maps: bool = False,
    drop_subject_diagrams: bool = False,
) -> str | None:
    """Classify an image as redundant noise to skip, or ``None`` to keep.

    Drops images the app already renders natively or that carry no value as a
    photo: ``"orbit-diagram"`` (orbit/trajectory plots) and
    ``"comparison-diagram"`` (Solar-System schematic & size-comparison diagrams,
    including localized text-baked variants). With ``drop_locator_maps`` (the
    nomenclature-feature pass) also drops ``"locator-map"`` red-dot/outline
    locators — these are surface features whose position the app shows itself.

    ``drop_subject_diagrams`` adds ``"subject-diagram"``: cutaways and maps of
    the subject itself — ring schemes, belt maps, moon line-ups — which restate
    what the scene and the charts already draw, and restate it in one language,
    since these families are drawn once and then retranslated file by file. It
    is off by default, and off for spacecraft in particular: the same signals
    tag *localized spacecraft schematics* (Astro-H, Ranger, Skylab), and for a
    probe with no photograph the schematic is the only illustration there is.
    Locator detection is likewise scoped to features so constellation coverage
    maps (categorised as country locator maps) survive; country groups drop
    their own maps via the selection skip.
    """
    lname = filename.lower()
    if is_excluded(filename) or any(s in lname for s in _ORBIT_FILENAME_SUBSTRINGS):
        return "orbit-diagram"
    if lname.startswith(_DIAGRAM_FILENAME_PREFIXES):
        return "comparison-diagram"
    if drop_subject_diagrams and (
        lname.startswith(_SUBJECT_DIAGRAM_FILENAME_PREFIXES)
        or any(s in lname for s in _SUBJECT_DIAGRAM_FILENAME_SUBSTRINGS)
    ):
        return "subject-diagram"
    for cat in _image_categories(metadata):
        c = cat.lower()
        if (
            c.startswith(("orbits of ", "orbit of "))
            or c in ("orbits", "orbits in art")
            or c.startswith(
                ("animations of orbits", "animations of minor planet orbits")
            )
            or c.startswith("videos of orbits")
            or "trajectory of" in c
        ):
            return "orbit-diagram"
        if (
            c == "solar system diagrams"
            or "solar system object comparison" in c
            or c.startswith("horizontal diagrams of the solar system")
            or "euler diagram" in c
        ):
            return "comparison-diagram"
        if drop_subject_diagrams and (
            c == "astronomical diagrams" or _LANGUAGE_DIAGRAM_CATEGORY.search(c)
        ):
            return "subject-diagram"
        if drop_locator_maps and "locator map" in c:
            return "locator-map"
    return None


def is_radar_render(metadata: dict | None) -> bool:
    """True for small-body radar / shape-model renders (asteroid/NEO radar).

    Tagged rather than dropped so they stay visible until 3D shape rendering
    lands. Excludes planetary surface radar maps (Magellan/Venus, Cassini/Titan),
    which are real surface imagery and stay tagged as photos.
    """
    return any(c.lower() in _RADAR_CATEGORIES for c in _image_categories(metadata))


def image_dir(filename: str) -> Path:
    """Per-image directory under IMAGES_DIR."""
    return IMAGES_DIR / filename


def source_path(filename: str) -> Path:
    """Downloaded source image path. Extension matches the Commons filename."""
    ext = Path(filename).suffix
    return image_dir(filename) / f"source{ext}"


def download_metadata_path(filename: str) -> Path:
    """Per-image Commons metadata JSON (raw API response + license_servable flag)."""
    return image_dir(filename) / "metadata.json"


def parse_upload_url(url: str) -> tuple[str, str] | None:
    """Return ``(repo, filename)`` from an ``upload.wikimedia.org`` URL, or None.

    ``repo`` is ``"commons"`` for Commons files and a wiki code (e.g. ``"ru"``)
    for files hosted locally on a specific wiki.
    """
    parts = urlparse(url).path.split("/")
    # path is like /wikipedia/<repo>/<hash>/<hash>/<filename>
    if len(parts) < 4 or parts[1] != "wikipedia":
        return None
    repo = parts[2]
    filename = unquote(parts[-1])
    if not filename:
        return None
    return repo, filename


def _wikidata_image_claims(entity: dict, pid: str) -> list[str]:
    """Canonical filenames from one image-claim PID, skipping deprecated statements."""
    out: list[str] = []
    for stmt in entity.get("claims", {}).get(pid, []):
        if stmt.get("rank") == "deprecated":
            continue
        val = stmt.get("mainsnak", {}).get("datavalue", {}).get("value")
        if isinstance(val, str) and val:
            out.append(canonical_filename(val))
    return out


def extract_wikidata_filenames(
    entity: dict, pids: tuple[str, ...] = _WIKIDATA_IMAGE_PIDS
) -> set[str]:
    """Extract unique Commons image filenames from image-claim properties."""
    return {fn for pid in pids for fn in _wikidata_image_claims(entity, pid)}


def collect_qid_image_candidates(
    qid: str,
    wikidata_dir: Path | None = None,
    wiki_dir: Path | None = None,
    *,
    aux_pid: str = "P154",
    aux_kind: str = "logo",
) -> tuple[list[str], dict[str, str], dict[str, int]]:
    """Return ``(direct, kind_of, pageimage_count)`` for a QID's Commons images.

    ``direct`` is the deduped, ordered list of canonical filenames discovered
    as Wikidata P18 (photo) → Wikipedia pageimages (photo) → Wikidata
    ``aux_pid`` (``aux_kind``) so the "first image" stays stable as Wikipedia
    sources come and go. ``kind_of`` maps each filename to ``"photo"`` or
    ``aux_kind``. ``pageimage_count[name]`` counts how many language wikis
    picked that file as their pageimage for this QID.

    The default ``aux_pid``/``aux_kind`` model objects (P154 logo); pass
    ``aux_pid="P242", aux_kind="locator"`` to model IAU nomenclature features.

    Non-Commons Wikipedia images and excluded-prefix filenames are filtered
    out; callers see only servable candidates.
    """
    wikidata_dir = wikidata_dir or (SOURCES_METADATA_DIR / "wikidata" / "objects")
    wiki_dir = wiki_dir or (SOURCES_METADATA_DIR / "wikipedia")

    photo_from_wikidata: list[str] = []
    aux_from_wikidata: list[str] = []
    entity_path = wikidata_dir / f"{qid}.json"
    if entity_path.exists():
        try:
            entity = orjson.loads(entity_path.read_bytes())
        except orjson.JSONDecodeError:
            logger.warning("Corrupt Wikidata JSON, skipping: %s", entity_path)
            entity = None
        if entity:
            photo_from_wikidata = _wikidata_image_claims(entity, "P18")
            aux_from_wikidata = _wikidata_image_claims(entity, aux_pid)

    photo_from_wikipedia: list[str] = []
    pageimage_count: dict[str, int] = {}
    for lang in LANGUAGES:
        page_path = wiki_dir / lang / f"{qid}.json"
        if not page_path.exists():
            continue
        try:
            page = orjson.loads(page_path.read_bytes())
        except orjson.JSONDecodeError:
            continue
        if page.get("missing"):
            continue
        src = (page.get("original") or {}).get("source")
        if not src:
            continue
        parsed = parse_upload_url(src)
        if parsed is None:
            continue
        repo, filename = parsed
        if repo != "commons":
            continue
        canonical = canonical_filename(filename)
        photo_from_wikipedia.append(canonical)
        pageimage_count[canonical] = pageimage_count.get(canonical, 0) + 1

    direct: list[str] = []
    seen: set[str] = set()
    kind_of: dict[str, str] = {}
    for name in photo_from_wikidata + photo_from_wikipedia:
        if name in seen or is_excluded(name):
            continue
        seen.add(name)
        kind_of[name] = "photo"
        direct.append(name)
    for name in aux_from_wikidata:
        if name in seen or is_excluded(name):
            continue
        seen.add(name)
        kind_of[name] = aux_kind
        direct.append(name)
    return direct, kind_of, pageimage_count


def collect_qid_commons_filenames(
    qid: str,
    wikidata_dir: Path | None = None,
    wiki_dir: Path | None = None,
) -> list[dict]:
    """Return the ordered, deduped list of Commons-hosted images for a QID.

    Each entry is ``{"filename": str, "kind": "photo"|"logo"}``. Thin wrapper
    around :func:`collect_qid_image_candidates` for callers that don't need
    the pageimage frequency map.
    """
    direct, kind_of, _ = collect_qid_image_candidates(qid, wikidata_dir, wiki_dir)
    return [{"filename": name, "kind": kind_of[name]} for name in direct]


def license_is_servable(extmetadata: dict) -> tuple[bool, str | None]:
    """Decide whether a Commons image's license allows us to serve it.

    Returns ``(servable, reason)`` where ``reason`` is non-None when rejected
    (used for log lines). The rules are the same as the legacy
    ``export/images._license_is_servable``:

    - LicenseShortName must exist and be a non-empty string
    - Each "A or B or C" segment is tested independently; at least one must
      pass ``_is_acceptable`` and NOT be GFDL-only. Multi-licensed
      ``CC BY-SA or GFDL`` images are fine because we can serve under the CC
      side and skip the GFDL license-text obligation.
    """
    short_value = (extmetadata.get("LicenseShortName") or {}).get("value")
    if not isinstance(short_value, str) or not short_value.strip():
        return False, "no LicenseShortName"

    tags = [t.strip() for t in short_value.split(" or ") if t.strip()]
    acceptable = [t for t in tags if _license_tag_is_acceptable(t)]
    if not acceptable:
        return False, f"unacceptable license {short_value!r}"
    non_gfdl = [t for t in acceptable if "gfdl" not in t.lower()]
    if not non_gfdl:
        return False, f"GFDL-only license {short_value!r}"
    return True, None


def _license_tag_is_acceptable(short_name: str) -> bool:
    """True if a single LicenseShortName tag is one we're willing to serve."""
    lower = short_name.lower()
    return not any(kw in lower for kw in _DENIED_LICENSE_KEYWORDS)


def read_download_metadata(filename: str) -> dict | None:
    """Read a downloaded image's metadata JSON, or None if missing/corrupt."""
    path = download_metadata_path(filename)
    if not path.exists():
        return None
    try:
        return orjson.loads(path.read_bytes())
    except orjson.JSONDecodeError:
        logger.warning("Corrupt download metadata: %s", path)
        return None


def read_manual_extras() -> dict[str, list[dict]]:
    """Read manually-curated extra images keyed by ``Object.id``.

    Lets us inject Commons images for objects whose Wikidata/Wikipedia
    discovery missed them. Same on-disk shape as ``object_images.json``:
    ``{object_id: [{"file": ..., "kind": ...}, ...]}``. Filenames are
    normalised to canonical (underscore) form on read.
    """
    if not MANUAL_EXTRA_PATH.exists():
        return {}
    try:
        data = orjson.loads(MANUAL_EXTRA_PATH.read_bytes())
    except orjson.JSONDecodeError:
        logger.warning("Corrupt %s; ignoring", MANUAL_EXTRA_PATH)
        return {}
    out: dict[str, list[dict]] = {}
    for obj_id, entries in data.items():
        normalised: list[dict] = []
        for entry in entries:
            file = entry.get("file")
            if not isinstance(file, str) or not file:
                logger.warning("Skipping manual-extra entry with no file: %r", entry)
                continue
            normalised.append(
                {"file": canonical_filename(file), "kind": entry.get("kind", "photo")}
            )
        if normalised:
            out[obj_id] = normalised
    return out


def is_servable_on_disk(filename: str) -> bool:
    """True when the downloaded metadata says the image's license is servable.

    Callers that also need the source bytes should check ``source_path`` too.
    """
    meta = read_download_metadata(filename)
    if not meta:
        return False
    return bool(meta.get("license_servable"))


def write_download_metadata(filename: str, payload: dict) -> None:
    """Persist the Commons metadata for a downloaded image (JSON, indented)."""
    path = download_metadata_path(filename)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2))
