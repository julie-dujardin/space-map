"""Search-index base + shared primary-key helpers.

The catalog is a single Meili index of heterogeneous documents discriminated
by ``kind`` ("object" | "feature" | "group"). Primary keys mirror the frontend
URL scheme (lib/state/url.ts) so they're globally unique across kinds by
construction:

    object   <letter>-<id>          b-399 / s-123 / e-7 / p-x
    feature  <letter>-<id>-f-<fid>  b-499-f-1234
    group    g-<slug>               g-starlink

The natural per-kind identifier (object id, feature body_id+feature_id, group
slug) also rides on the document's nested key, so the frontend can route a hit
without re-parsing the primary key.
"""

from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any

# Backend object-id prefix → URL type letter. Mirrors ``urlTypeToIdPrefix`` in
# the frontend (lib/state/url.ts).
_OBJECT_ID_PREFIX_TO_LETTER: dict[str, str] = {
    "naif-": "b",
    "spkid-": "s",
    "norad_satcat-": "e",
    "probe-": "p",
    "extra-": "u",
}


def object_pk(obj_id: str) -> str:
    """URL-form primary key for an object id (``naif-399`` → ``b-399``)."""
    for prefix, letter in _OBJECT_ID_PREFIX_TO_LETTER.items():
        if obj_id.startswith(prefix):
            return f"{letter}-{obj_id.removeprefix(prefix)}"
    return f"o-{obj_id}"  # unknown prefix: stay unique rather than crash


def feature_pk(body_id: str, feature_id: int) -> str:
    """URL-form primary key for a feature (``naif-499`` + 1234 → ``b-499-f-1234``)."""
    return f"{object_pk(body_id)}-f-{feature_id}"


def group_pk(slug: str) -> str:
    """Primary key for a group (``starlink`` → ``g-starlink``)."""
    return f"g-{slug}"


@dataclass(frozen=True)
class Index:
    uid: str
    primary_key: str
    settings: dict[str, Any]

    def build_documents(self, export_dir: Path) -> Iterator[dict[str, Any]]:
        raise NotImplementedError
