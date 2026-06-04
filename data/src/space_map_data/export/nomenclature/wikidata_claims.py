"""Feature-specific Wikidata claim definitions for IAU planetary nomenclature.

Stage 2a stub. The full extractor (``FEATURE_GLOBAL_CLAIMS`` + an extraction
entry point) will land alongside this list when the feature-details writer is
wired up. For now only the entity-reference claims live here, so the Wikidata
download fan-out can follow them into ``referenced/`` independently.
"""

from space_map_data.export.objects.wikidata_claims import EntityRefClaim


# Claims followed for feature entities on top of the shared object set
# (``ENTITY_REF_CLAIMS`` already covers P31 instance_of, P138 named_after,
# P361 part_of). Restricted to the nomenclature scan so object entities don't
# trigger downloads of unrelated location refs.
FEATURE_ENTITY_REF_CLAIMS: tuple[EntityRefClaim, ...] = (
    EntityRefClaim("location", "P276"),
    EntityRefClaim("located_on_physical_feature", "P706"),
)
