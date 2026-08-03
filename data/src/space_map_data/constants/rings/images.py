"""The picture that opens each ring system's panel.

Picked by hand from what the pages the panel already cites carry — the
"Rings of X" Wikidata item's P18, or the lead image of whichever language's
article makes the better case. Two rules decided every row:

- a photograph over a diagram, because the chart below already draws the
  structure a scheme would repeat;
- nothing with text baked into the pixels, since it would read in English (or
  Italian) in all twelve locales. That rules out the P18 images of Uranus and
  Neptune, both schemes, and Jupiter's annotated cutaway.

Values are Commons filenames in the underscore form the download layout uses.
All four are public domain.
"""

# Keyed to the host body, matching ``RingCatalog.body``.
RING_HERO_IMAGES: dict[str, str] = {
    # Galileo, the main ring lit from behind either side of Jupiter's shadow.
    # The one photograph in the set that shows a ring rather than a planet
    # wearing one (it.wikipedia).
    "naif-599": "JupiterRings.jpg",
    # Cassini's "The Day the Earth Smiled": the planet eclipsing the Sun, so
    # the whole system lights up, E ring and all (P18 + en.wikipedia).
    "naif-699": "PIA17172_Saturn_eclipse_mosaic_bright_crop.jpg",
    # JWST/NIRCam, the unlabelled cut of the frame en.wikipedia annotates —
    # the ε ring and the ζ sheet inside it both resolve (it.wikipedia).
    "naif-799": "STScI-01GWQDPJTF1MY8ZGN4WBMWMACJ.png",
    # JWST/NIRCam, the clearest view of the rings since Voyager 2, with the
    # arcs on the Adams ring visible (en.wikipedia).
    "naif-899": "New_Webb_Image_Captures_Clearest_View_of_Neptune’s_Rings_in_Decades.png",
}
