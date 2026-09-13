"""Objects whose Wikidata item is named after something other than the object.

A localized name is the label of the item the probe inventory registers, so a
craft filed against its mission reads as the mission in all twelve languages.
The item named here supplies the label instead, leaving every other claim —
mass, launch, sitelinks — on the registered item, which is what the inventory
means it to be. The Wikidata downloader seeds these items into ``referenced/``,
since an item only reachable through a claim on the entity it replaces would
lose the name the moment that claim moved.
"""

# Object.id -> the Wikidata item whose label the object is named by.
NAME_ENTITIES: dict[str, str] = {
    # NAIF -76 is the rover standing on Mars, not the launch that delivered it:
    # Q48496 is the Mars Science Laboratory mission, Q48485 is Curiosity.
    "probe-100265984": "Q48485",
}
