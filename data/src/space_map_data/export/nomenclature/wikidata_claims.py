"""Feature-specific Wikidata claim definitions for IAU planetary nomenclature.

Mirrors the object claim spec in ``export/objects/wikidata_claims.py`` but
scoped to surface features: physical quantities (length/width/height/area/
elevation/depth) and entity references (instance_of/named_after/location/
located-on-physical-feature). Images are pulled out by the image-selection
ingest pass, not extracted here.
"""

from space_map_data.export.objects.wikidata_claims import (
    EntityRefClaim,
    GlobalClaim,
    extract_claims,
)
from space_map_data.export.wikidata import WikidataEntityCache


# Quantity claims emitted into the per-feature global JSON.
# P2043/P2049 overlap with the object spec (spacecraft length/width); the
# disambiguation logic is shared via :func:`extract_claims`.
FEATURE_GLOBAL_CLAIMS: tuple[GlobalClaim, ...] = (
    GlobalClaim("length", "P2043", "quantity"),
    GlobalClaim("width", "P2049", "quantity"),
    GlobalClaim("height", "P2048", "quantity"),
    GlobalClaim("area", "P2046", "quantity"),
    GlobalClaim("elevation", "P2044", "quantity"),
    GlobalClaim("vertical_depth", "P4511", "quantity"),
)


# Reference claims resolved to ``{name, short_name?, wikipedia?}`` in the
# per-feature localized JSON. The downloader's secondary-qid pass follows
# these PIDs into ``referenced/``.
FEATURE_ENTITY_REF_CLAIMS: tuple[EntityRefClaim, ...] = (
    EntityRefClaim("instance_of", "P31", multiple=True),
    EntityRefClaim("named_after", "P138", multiple=True),
    EntityRefClaim("location", "P276", multiple=True),
    EntityRefClaim("located_on_physical_feature", "P706", multiple=True),
    EntityRefClaim("part_of", "P361", multiple=True),
)


FEATURE_PID_TO_KEY: dict[str, str] = {
    c.pid: c.key for c in (*FEATURE_GLOBAL_CLAIMS, *FEATURE_ENTITY_REF_CLAIMS)
}


def extract_feature_claims(
    claims: dict,
    qid: str,
    wikidata_entities: WikidataEntityCache | None = None,
) -> dict:
    """Run the shared claim extractor over the feature claim spec.

    Returns a flat dict keyed by claim ``.key`` (e.g. ``length``,
    ``named_after``) with values shaped the same as object extraction.
    """
    return extract_claims(
        claims,
        qid,
        wikidata_entities,
        global_claims=FEATURE_GLOBAL_CLAIMS,
        entity_ref_claims=FEATURE_ENTITY_REF_CLAIMS,
        route_temperature=False,
    )
