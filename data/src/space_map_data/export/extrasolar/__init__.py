"""`space-map-export --only extrasolar`: the extrasolar registry's tables as
served files under `space-map-extrasolar/v1/x/`.

- `container`: the binary format of every file, with its token.
- `tiles`: record tiles, the split tables and the checks on the rows.
- `render`: the Milky Way render tree.
- `skycultures`: the sky cultures, one file per culture.
- `planets`: the planet index and one file per planetary system.
- `orbits`: planet orbits from the plane of the sky to the scene's frame.
- `skyculture_authors`: the plain author names of each Stellarium culture.
- `build`: the run, from the registry to the swap into place.
- `reader`: lookups with the steps that a client takes.

The format is in docs/export-format/extrasolar.md.
"""
