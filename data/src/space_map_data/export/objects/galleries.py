"""Extra image galleries attached to an object's global bundle.

A page shows one gallery per *subject*: the body itself (``images``), its rings
(``ring_images``), and the galleries built here — its atmosphere, its insides,
its named surface features and its moons. Each is a separate shelf in the Images
tab rather than one undifferentiated pile, so a picture of Ganymede is filed
under Ganymede instead of sitting between two portraits of Jupiter.

The topic shelves come from the articles the Structure tab already cites. The
pooled shelves are drawn from the notable lists the tiers above ranked, so a
picture leads its gallery for the same reason its subject leads the list, and
the subject id rides on every entry: it labels the tile and links out of the
viewer.
"""

import logging
from collections import Counter
from collections.abc import Iterable, Sequence

from space_map_data.constants.providers import LANGUAGES
from space_map_data.export.images import (
    collect_feature_images,
    collect_object_images,
    collect_topic_images,
    localized_image_titles,
)
from space_map_data.export.objects.writer import ChunkObjectData

logger = logging.getLogger(__name__)

# Shelf sizes. Both pools can run long (Saturn has 20 notable moons, the Moon
# has 20 notable features), and a shelf is a taste of the subject rather than
# its catalogue — the subject's own page holds the rest.
FEATURE_GALLERY_LIMIT = 12
MOON_GALLERY_LIMIT = 10
# One prolific moon shouldn't crowd out the rest of the system.
MOON_PER_SUBJECT_CAP = 2

# Locator maps are IAU outline drawings, not pictures of the feature.
_GALLERY_KINDS = frozenset({"photo", "radar"})

# Shelves about one aspect of the body, ahead of the ones about other bodies.
# Interior is deliberately absent: its articles illustrate with cutaway
# schematics (often lettered in one language), which is what the Structure tab
# already draws. Its selection is cached all the same — adding it back is this
# tuple.
_TOPICS = ("atmosphere",)

# Vectors on Commons are diagrams, never photographs, and a topic article's
# diagrams restate the cross-section and composition bar the app draws itself.
_DIAGRAM_SUFFIX = ".svg"


def attach_galleries(chunk: ChunkObjectData) -> None:
    """Inject ``galleries`` into every global bundle that earns one.

    Mutates ``chunk`` in place (mirrors ``attach_notable_moons``) and must run
    after the notable moon and feature passes, whose output it pools.
    """
    counts: Counter[str] = Counter()
    for object_id, global_data in chunk.global_data.items():
        # Nothing is worth showing twice: the body's own pictures and its ring
        # pictures are galleries of their own, one shelf up.
        seen = {
            entry["file"]
            for key in ("images", "ring_images")
            for entry in global_data.get(key) or ()
        }
        galleries = []
        for topic in _TOPICS:
            pictures = [
                entry
                for entry in collect_topic_images(object_id, topic) or ()
                if entry["kind"] in _GALLERY_KINDS
                and entry["file"] not in seen
                and not entry["file"].lower().endswith(_DIAGRAM_SUFFIX)
            ]
            if pictures:
                seen.update(entry["file"] for entry in pictures)
                galleries.append({"key": topic, "images": pictures})
                counts[topic] += 1
        features = _pool(
            [
                (fid, collect_feature_images(fid))
                for fid in _subject_ids(
                    global_data.get("notable_features"), "feature_id"
                )
            ],
            seen,
            limit=FEATURE_GALLERY_LIMIT,
            per_subject=1,
        )
        moons = _pool(
            [
                (moon_id, collect_object_images(moon_id))
                for moon_id in _subject_ids(global_data.get("notable_moons"), "id")
            ],
            seen,
            limit=MOON_GALLERY_LIMIT,
            per_subject=MOON_PER_SUBJECT_CAP,
        )
        for key, images in (("features", features), ("moons", moons)):
            if images:
                galleries.append({"key": key, "images": images})
                counts[key] += 1
        if galleries:
            global_data["galleries"] = galleries
            _attach_titles(chunk, object_id, galleries)
    logger.info(
        "Attached pooled image galleries: %s",
        ", ".join(f"{key} on {n} bodies" for key, n in sorted(counts.items()))
        or "none",
    )


def _attach_titles(
    chunk: ChunkObjectData, object_id: str, galleries: list[dict]
) -> None:
    """Fold these shelves' picture titles into the object's localized bundles.

    The writer only knows about the object's own and its ring pictures, so the
    pooled ones are added here. Never onto a language with no entry of its own:
    the ``has_localized`` bit is already baked into the binary chunk.
    """
    files = [entry["file"] for gallery in galleries for entry in gallery["images"]]
    for lang in LANGUAGES:
        localized = chunk.localized_data.get(lang, {}).get(object_id)
        if localized is None:
            continue
        titles = localized_image_titles(files, lang)
        if titles:
            localized.setdefault("image_titles", {}).update(titles)


def _subject_ids(entries: Iterable[dict] | None, id_key: str) -> list:
    """Subject ids from a notable list, keeping its ranking."""
    return [entry[id_key] for entry in entries or () if entry.get(id_key) is not None]


def _pool(
    pools: Sequence[tuple[object, list[dict] | None]],
    seen: set[str],
    *,
    limit: int,
    per_subject: int,
) -> list[dict]:
    """Interleave each subject's pictures into one shelf, best subject first.

    Walks the subjects in rank order taking one picture each, then goes round
    again, so a shelf that fills up still spans the system instead of stopping
    inside the first moon's gallery. ``seen`` grows as pictures are taken, both
    across subjects here and against the galleries one shelf up.
    """
    out: list[dict] = []
    for _ in range(per_subject):
        for subject, entries in pools:
            entry = next(
                (
                    e
                    for e in entries or ()
                    if e["kind"] in _GALLERY_KINDS and e["file"] not in seen
                ),
                None,
            )
            if entry is None:
                continue
            seen.add(entry["file"])
            out.append({**entry, "subject": subject})
            if len(out) >= limit:
                return out
    return out
