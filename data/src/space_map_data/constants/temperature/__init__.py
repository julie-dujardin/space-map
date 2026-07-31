"""Curated temperature constants feeding `export/objects/`.

Split by how strong the claim is: `bodies` holds published measurements for
the 15 bodies where one exists and beats Wikidata, `cores` holds modelled
central temperatures as low-high brackets, and `references` maps the citation
keys both use onto works for /credits.

Everything not listed here is either passed through from Wikidata or computed
as an equilibrium estimate (`export/objects/temperature.py`), and the export
marks which of the three a reading is so the frontend never presents a model
result as a measurement.
"""
