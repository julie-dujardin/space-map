"""Curated temperature constants feeding `export/objects/`.

Split by how strong the claim is: `bodies` holds published measurements for
the 15 bodies where one exists and beats Wikidata, and `references` maps its
citation keys onto works for /credits.

Nothing here describes the inside of a body. A modelled core temperature is a
temperature *at a boundary*, so it lives with the boundary in
`constants/interior/bodies.py` and the export reads it back from there.

Everything not listed here is either passed through from Wikidata or computed
as an equilibrium estimate (`export/objects/temperature.py`), and the export
marks which of the three a reading is so the frontend never presents a model
result as a measurement.
"""
