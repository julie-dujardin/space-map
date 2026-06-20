# Elements payload (format byte = 0)

Columnar binary format with zero-copy typed array support.

## Elements extension (8 bytes, offsets 24..31)

| Offset | Type    | Field |
|--------|---------|-------|
| 24     | uint16  | Sub-format: `0 = Keplerian, 1 = Parabolic, 2 = SGP4` |
| 26     | uint8   | Source: `0 horizons, 1 sbdb, 2 celestrak, 3 spice, 4 sbdb_moon, 255 unknown` — every row in the file shares this provider |
| 27     | uint8   | Id type: `0 naif, 1 spkid, 2 norad_satcat, 3 sbdb_moon, 255 unknown` — every row in the file shares this prefix; combine with column 0 (numeric ID) to rebuild the full `<prefix>-<numeric>` Object ID. For `sbdb_moon` (compound id `sbdb_moon-<parent_spkid>-<sat_index>`), col 0 carries `sat_index` and the parent SPK-ID rides in col 2 — combine both with the zone's `parent_id_type` (`"spkid"`) to rebuild the id |
| 28     | uint32  | Row count |

One provider writes one zone/part (pipeline-enforced), so the source fits in
a single file-level byte rather than per-row. The id type follows the same
single-typed-file invariant — each (zone, zoom) query selects on the prefix-
defining column, so one byte per file is enough. Frontend must mirror both
ordinal mappings.

## Keplerian columns (sub-format = 0)

Each column is padded to 8-byte alignment. Julian Dates use float64 for sub-day precision; other numeric columns use float32 (~7 significant digits). See [Precision rationale](#precision-rationale) below.

| # | Name        | Type    | Missing | Notes |
|---|-------------|---------|---------|-------|
| 0 | id          | int32   | -1      | Numeric portion of `Object.id`; combine with the elements extension's id-type byte to rebuild the full `<prefix>-<numeric>` form (e.g. id-type=0 + 399 → `naif-399`). Sourced from `naif_id`, `spkid`, or `norad_cat_id` per the file's id type. For `sbdb_moon` files this is the per-parent `sat_index` (0-based); the parent SPK-ID in col 2 supplies the rest of the compound id. |
| 1 | object_type | uint8   | 255     | `ObjectType` ordinal (see below) |
| 2 | parent_id   | int32   | -1      | Numeric portion of the parent's `Object.id`. Combine with the zone-level `parent_id_type` from `metadata.json` (default `"naif"` when absent) to rebuild `<parent_id_type>-<col2>`. Examples: `naif-3` (Earth-Moon barycenter), `spkid-2000004` (Vesta) |
| 3 | scale       | uint8   | 255     | 0 = planet, 1 = system |
| 4 | epoch_jd    | float64 | NaN     | Epoch, Julian Date TDB |
| 5 | a           | float32 | NaN     | Semi-major axis: **km** if planet-scale, **AU** if system-scale |
| 6 | e           | float32 | NaN     | Eccentricity |
| 7 | i           | float32 | NaN     | Inclination (deg) |
| 8 | om          | float32 | NaN     | Longitude of ascending node (deg) |
| 9 | w           | float32 | NaN     | Argument of perihelion (deg) |
| 10| ma          | float32 | NaN     | Mean anomaly (deg) |
| 11| n           | float32 | NaN     | Mean motion: **rev/day** if planet-scale, **deg/day** if system-scale |
| 12| radius_km   | float32 | NaN     | Physical radius (km) |
| 13| om_dot      | float32 | 0.0     | Secular drift of `om` (deg/day). Populated by SPICE for non-whitelisted moons via the Method C mean-element fit; zero for everything else |
| 14| w_dot       | float32 | 0.0     | Secular drift of `w` (deg/day). Same source / convention as `om_dot` |
| 15| has_localized | uint8 | 0       | `1` iff the object has a localized detail bundle in at least one language; `0` otherwise. Frontend gates its localized-bundle fetch on this bit so flag-0 objects don't trigger a 404 per click |
| 16| flags       | uint8   | 0       | Per-point SBDB-derived bits: bit 0 = NEO (`sbdb.neo`), bit 1 = PHA (`sbdb.pha`), bits 2–7 reserved. Zero on rows without an SBDB sub-table (planets, moons, sats). |

Coordinate frame: ecliptic J2000.

Propagation with secular rates: `om(t) = om + om_dot · (jd − epoch_jd)`,
`w(t) = w + w_dot · (jd − epoch_jd)`. Sources that don't fit secular drift
(Horizons/SBDB/CelesTrak) write zeros, making the rate term a no-op. This
captures J2/J4 nodal regression and apsidal precession on small moons
(Phobos' ~−160°/yr, inner Saturn/Neptune moons up to ~−300°/yr) without
shipping per-frame Chebyshev coefficients.

## ObjectType ordinals

```
0  barycenter       4  dwarf_planet    8  asteroid_main_belt   12  comet
1  lagrange_point   5  moon            9  asteroid_trojan      13  spacecraft
2  star             6  asteroid       10  asteroid_centaur      14  debris
3  planet           7  asteroid_inner 11  asteroid_tno          15  undocumented
```

## Scale and unit conversions

The `scale` flag determines how to interpret `a` and `n`:

| scale | a unit | n unit  | Context |
|-------|--------|---------|---------|
| 0 (planet) | km | rev/day | Earth-orbiting satellites |
| 1 (system) | AU | deg/day | Heliocentric objects, moons |

To consume uniformly, normalize planet-scale values: `a_au = a / 149_597_870.7`, `n_degday = n * 360`.

## SGP4 columns (sub-format = 2)

Used for the `earth` zone. Shares columns 0–12 with the Keplerian layout
(SGP4 omits the secular rate columns 13–14 since the SGP4 propagator
already models J2 drag/drift internally), followed by the extra OMM fields
needed to initialize a [satellite.js](https://github.com/shashwatak/satellite-js)
`satrec` via `json2satrec()` and propagate with the SGP4 model. Consumers that
don't do SGP4 can ignore columns 13–17 and treat the file as Keplerian.

| #  | Name             | Type    | Missing | Notes |
|----|------------------|---------|---------|-------|
| 13 | bstar            | float32 | —       | B\* drag term (1 / Earth radius) |
| 14 | mean_motion_dot  | float32 | —       | First derivative of mean motion (rev/day²) |
| 15 | mean_motion_ddot | float32 | —       | Second derivative of mean motion (rev/day³) |
| 16 | element_set_no   | int32   | -1      | TLE element set number |
| 17 | rev_at_epoch     | int32   | -1      | Revolution number at epoch |
| 18 | has_localized    | uint8   | 0       | Same semantics as the Keplerian column 15 |
| 19 | flags            | uint8   | 0       | Always zero for SGP4 (no SBDB sub-table); emitted for layout uniformity with the Keplerian sub-format |

`a` and `n` use the planet-scale units (km, rev/day) — the raw OMM values from
CelesTrak, which `json2satrec` expects unconverted.

## Parabolic columns (sub-format = 1)

Used for the `small_bodies/PAR` zone. Parabolic comets (`e = 1`) lack a semi-major axis and mean motion; they use perihelion distance and time of perihelion instead.

Columns 0–3 are identical to Keplerian. Julian Dates use float64; other columns use float32:

| # | Name        | Type    | Missing | Notes |
|---|-------------|---------|---------|-------|
| 4 | epoch_jd    | float64 | NaN     | Epoch, Julian Date TDB |
| 5 | q           | float32 | NaN     | Perihelion distance (AU) |
| 6 | e           | float32 | NaN     | Eccentricity (= 1.0) |
| 7 | i           | float32 | NaN     | Inclination (deg) |
| 8 | om          | float32 | NaN     | Longitude of ascending node (deg) |
| 9 | w           | float32 | NaN     | Argument of perihelion (deg) |
| 10| tp          | float64 | NaN     | Time of perihelion passage (Julian Date, TDB) |
| 11| radius_km   | float32 | NaN     | Physical radius (km) |
| 12| has_localized | uint8 | 0       | Same semantics as the Keplerian column 15 |
| 13| flags       | uint8   | 0       | Same semantics as the Keplerian column 16 |

To compute positions, use Barker's equation instead of Kepler's equation.

## Precision rationale

Orbit propagation computes mean anomaly as `M = ma + n * (jd_now - epoch_jd)`. The `jd_now - epoch_jd` subtraction is the precision bottleneck: Julian Dates are ~2,460,000, so float32 (24-bit mantissa) can only resolve ~0.25 days (6 hours) at that magnitude — causing degree-scale position errors for fast-moving bodies. float64 resolves ~0.1 ms, which is more than sufficient. The same applies to `tp` in the parabolic format.

All other columns are safe as float32 based on their value ranges in the database:

| Column     | DB range                | float32 worst-case precision | Notes |
|------------|-------------------------|------------------------------|-------|
| a (AU)     | 0 – 1.6 × 10⁶          | ~0.125 AU at max             | At typical values (< 100 AU): ~8 × 10⁻⁶ AU ≈ 1 km |
| a (km)     | 6,500 – 430,000         | ~0.03 km at max              | Earth-orbiting satellites |
| e          | 0 – 6.3                 | ~5 × 10⁻⁷                   | |
| i, om, w, ma | 0 – 360              | ~2 × 10⁻⁵ deg ≈ 0.08 arcsec | |
| n (deg/d)  | 0 – 1,225               | ~7 × 10⁻⁵ deg/d             | |
| n (rev/d)  | 0.07 – 16.4             | ~1 × 10⁻⁶ rev/d             | Earth-orbiting satellites |
| om_dot, w_dot (deg/d) | -1.0 – 1.0   | ~6 × 10⁻⁸ deg/d             | Phobos' ~−160°/yr ≈ 0.44°/d sets the upper magnitude |
| q (AU)     | 0 – 43                  | ~3 × 10⁻⁶ AU                | Parabolic comets only |
| radius_km  | 0.001 – 70,000          | ~0.004 km at max             | |
