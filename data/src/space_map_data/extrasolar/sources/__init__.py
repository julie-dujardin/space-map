"""The catalogues that feed the extrasolar ingest, one module each.

- `gaia`: Gaia DR3 positionable stars with their fidelity, home Point source,
  and the rows of the SIMBAD stars without a 5σ parallax, which never mint.
- `hipparcos`: the Hipparcos new reduction with the 1997 photometry, and the
  entries of 1997 that the new reduction drops.
- `simbad`: SIMBAD's well-known stars and their designations.
- `names`: the IAU star names. They never mint.
- `literature`: the star values of the literature table in the repo.
- `distances`: the distance catalogues.
- `wikidata`: the Wikidata items of stars. They never mint.
"""
