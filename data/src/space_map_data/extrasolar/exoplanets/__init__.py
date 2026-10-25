"""Exoplanets and their host stars in the extrasolar ingest.

The NASA Exoplanet Archive, exoplanet.eu and the Open Exoplanet Catalogue
(OEC) come in, in that source order. SIMBAD joins their stars and planets.
Each host star gets a registry ID through the engine, as a row of each
catalogue that lists it. The planets do not get IDs: a planet is
`/x/<host>/b/<n>`, where n counts from 1 within its host. The registry's
Planets part keeps the numbers and the catalogue ids of each planet, and
the planets table holds the values, both written by `PlanetsExtension` at
the commit of the ingest.

Modules:
- catalogues: the readers of the three catalogues
- simbad: the SIMBAD names, objects, identifiers and parents
- hosts: star identities, systems, system keys and the engine rows
- join: the planet join across catalogues
- iau: the IAU classes
- names: the IAU NameExoWorlds names
- table: the planets table and its defaults
- numbering: the Planets part of the registry
- ingest: the passes and the extension
"""
