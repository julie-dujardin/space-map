# Pre-interaction labels (`labels/{lang}.gz`)

One global file per language, listing only the *promoted* set — bodies that
get a label rendered on first paint without waiting for the user to interact:

- All planets, dwarf planets, moons, stars, barycenters, and Lagrange points
  (picked by `ObjectType`).
- A small curated list of spacecraft / satellites / asteroids / comets in
  [`constants/promoted.py`](../../data/src/space_map_data/constants/promoted.py)
  (Voyager 1/2, ISS, Hubble, Apophis, Halley, …).

The frontend fetches one of these on app start (and on locale change) and uses
its keys as the authoritative promoted set — there's no separate frontend list.

Format: gzipped UTF-8, one `{id}\x1f{name}\x1f{flags}` line per object
(`\x1f` = ASCII Unit Separator). The name is the one of the object's page in
the language (`export/names.py`): the localized `name` of its bundle entry,
else its global `name`. It is empty for an object whose only name is its id
(two moons with no name and no designation). The only flag is `m` (minor: a collapsed halo that
expands on hover), for a moon with no IAU name, in every language, and for a
probe outside the curated list.

Localized detail bundles for clicked objects are still fetched on demand (see
[Object detail files](objects.md)) and are gated on the
`has_localized` bit in each binary file's row/body — when the bit is `0`, the
frontend skips the fetch entirely (avoiding a 404 round-trip for objects with
no Wikidata at all). There is no English-fallback tier: if the user's locale
has no localized bundle for an object, no localized data is shown.
