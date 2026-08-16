"""Launch pads in the search index.

Source file:

    v1/groups/__global__/{bucket}.json.gz   — ``site-`` groups, each carrying
                                              its GCAT places and their pads

A pad is indexed so a trip can leave from one, not so it can be read about:
there is nothing to say about a concrete slab that its cosmodrome does not say
better, and a hit routes to the site page holding it. Which is also why the
documents are deliberately thin — a name, a place and a point.

Nothing here carries prominence. Pads have no Wikidata entity to take a
sitelink count from, so every one of them sorts below anything that does, and
they surface only for a reader who is already asking for a pad. That is the
wanted outcome rather than a gap: launch ranges are what the catalogue is
about, and there are ~2800 pads under them.
"""

import gzip
import json
import logging
from collections.abc import Iterator
from pathlib import Path
from typing import Any

from space_map_data.constants.earth_sats.launch_sites import LAUNCH_SITE_SLUG_PREFIX
from space_map_data.constants.providers import LANGUAGES

from .base import pad_pk

logger = logging.getLogger(__name__)


def _localized_site_names(
    groups_dir: Path, slugs: set[str]
) -> dict[str, dict[str, str]]:
    """``{lang: {slug: name}}`` for the given collections."""
    out: dict[str, dict[str, str]] = {}
    for lang in LANGUAGES:
        lang_dir = groups_dir / lang
        names: dict[str, str] = {}
        if lang_dir.exists():
            for bundle in sorted(lang_dir.glob("*.json.gz")):
                for slug, entry in json.loads(
                    gzip.decompress(bundle.read_bytes())
                ).items():
                    if slug in slugs and entry.get("name"):
                        names[slug] = entry["name"]
        out[lang] = names
    return out


def build_pad_documents(export_dir: Path) -> Iterator[dict[str, Any]]:
    groups_dir = export_dir / "v1" / "groups"
    global_dir = groups_dir / "__global__"
    if not global_dir.exists():
        logger.warning("No group bundles at %s — no pads to index", global_dir)
        return

    sites: dict[str, dict[str, Any]] = {}
    for bundle in sorted(global_dir.glob("*.json.gz")):
        for slug, group in json.loads(gzip.decompress(bundle.read_bytes())).items():
            if slug.startswith(LAUNCH_SITE_SLUG_PREFIX) and group.get("gcat_sites"):
                sites[slug] = group

    localized = _localized_site_names(groups_dir, set(sites))
    count = 0
    for slug, group in sites.items():
        for site in group["gcat_sites"]:
            for pad in site.get("pads", ()):
                # The trimmed label, not GCAT's raw name: the raw one repeats the
                # place on every row, so "Canaveral" would match all 82 of its
                # pads ahead of the range they belong to.
                name = pad.get("label") or pad["name"]
                doc: dict[str, Any] = {
                    "id": pad_pk(slug, pad["code"]),
                    "kind": "pad",
                    "name": name,
                    "pad": {
                        "code": pad["code"],
                        "site_slug": slug,
                        "site_name": site.get("name") or site["code"],
                        "lat": pad["lat"],
                        "lon": pad["lon"],
                        "launches": pad.get("launches", 0),
                    },
                }
                for lang, names in localized.items():
                    # The pad's own name is GCAT's English; what a reader may
                    # search it by in their language is the range holding it.
                    if names.get(slug):
                        doc[f"description_{lang}"] = names[slug]
                yield doc
                count += 1
    logger.info("Indexing %d launch pads across %d sites", count, len(sites))
