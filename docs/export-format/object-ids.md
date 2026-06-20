# Object ID reconstruction

Object IDs (`naif-399`, `spkid-2000433`, `norad_satcat-25544`, `probe-100265984`)
are not shipped as separate files — consumers rebuild them from the binary:

- **Elements**: combine the elements extension's `id_type` byte (offset 27)
  with column 0 (`int32`) per row.
- **Chebyshev**: combine each per-body header's `id_type` (offset 18) with
  `obj_id_value` (offset 8).
- **Probes**: combine each per-probe header's `id_type` (offset 4, always
  `4 = PROBE`) with `obj_id_value` (offset 0).

All three formats use the same id-type ordinal map:
`0 naif, 1 spkid, 2 norad_satcat, 3 sbdb_moon, 4 probe, 255 unknown`.

For col 2 (parent), elements files don't carry a per-row id-type byte — every
row's parent in a given zone shares the same prefix (the SQL queries are
single-typed by construction). The prefix lives at the zone level in
`metadata.json` as `parent_id_type` (e.g. `"naif"`, `"spkid"`); rebuild parent
ids as `${parent_id_type}-${col 2}`. Older zones may omit the field — treat
`undefined` as `"naif"`.

`sbdb_moon` is a compound id (`sbdb_moon-<parent_spkid>-<sat_index>`): col 0
ships the `sat_index`, col 2 ships the parent SPK-ID, and the elements
extension's id-type byte = 3 picks the prefix. Frontends rebuild as
`sbdb_moon-${col2}-${col0}`.
