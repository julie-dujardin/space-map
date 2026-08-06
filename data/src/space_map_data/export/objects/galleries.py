"""Extra image galleries attached to an object's global bundle.

A page shows one gallery per *subject*: the body itself (``images``), its rings
(``ring_images``), and the pooled galleries built here — the pictures of its
named surface features and of its moons. Each is a separate shelf in the Images
tab rather than one undifferentiated pile, so a picture of Ganymede is filed
under Ganymede instead of sitting between two portraits of Jupiter.

Both pools are drawn from the notable lists the tiers above already ranked, so
a picture leads its gallery for the same reason its subject leads the list. The
subject id rides on every entry: it labels the tile and links out of the viewer.
"""

import logging
from collections import Counter
from collections.abc import Iterable, Sequence

from space_map_data.export.images import collect_feature_images, collect_object_images
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


def attach_galleries(chunk: ChunkObjectData) -> None:
    """Inject ``galleries`` into every global bundle that earns one.

    Mutates ``chunk`` in place (mirrors ``attach_notable_moons``) and must run
    after the notable moon and feature passes, whose output it pools.
    """
    counts: Counter[str] = Counter()
    for global_data in chunk.global_data.values():
        # Nothing is worth showing twice: the body's own pictures and its ring
        # pictures are galleries of their own, one shelf up.
        seen = {
            entry["file"]
            for key in ("images", "ring_images")
            for entry in global_data.get(key) or ()
        }
        galleries = []
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
    logger.info(
        "Attached pooled image galleries: %s",
        ", ".join(f"{key} on {n} bodies" for key, n in sorted(counts.items()))
        or "none",
    )


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
