# Export Format (v1 directory, binary v4)

All files are served under `/data/v1/` and are gzip-compressed unless noted.

## Directory structure

```
v1/
  metadata.json                                  (not gzipped)
  credits.json                                   (not gzipped) aggregated attribution for the /credits page
  nut_prec_angles.json                           (not gzipped) IAU nutation angles, by owner naif_id
  elements/{zone}/{zoom}/{part}.bin.gz           binary orbital elements (single-snapshot zones)
  elements/{zone}/{zoom}/{part}.loc.{lang}.gz    localized labels
  elements/earth/{zoom}/{time}/{part}.bin.gz     time-segmented Earth elements (per CelesTrak day-dir)
  elements/earth/{zoom}/{time}/{part}.loc.{lang}.gz  localized labels for the snapshot
  chebyshev/{zone}/{chunk}/data.bin.gz           binary Chebyshev polynomial ephemeris
  objects/__global__/{bucket}.json.gz            global object details, hash-bucketed
  objects/{lang}/{bucket}.json.gz                localized details, hash-bucketed
  v1/images/{filename}/{label}.{ext}             thumbnail variants (label = s | m | xl)
  v1/images/{filename}/metadata.json.gz          per-image license + variants map
  textures/{id}/{tier}.webp                      tier = low | medium | high
  textures/{id}/metadata.json                    texture source + exports
  systems/{barycenter_id}.json                   per-system body metadata
```

## metadata.json

Entry point. Lists all available chunks so the consumer knows what to fetch.

```json
{
  "zones": {
    "major": {
      "zooms": { "0": { "parts": 1 } }
    },
    "earth": {
      "zooms": {
        "0": { "start_date": "2026-04-23", "end_date": "2026-04-26", "parts": 2 }
      }
    }
  },
  "object_bundles": {
    "global": 1093,
    "en": 208, "fr": 208, "ja": 208, "ar": 201, "ru": 208, "zh": 208
  },
  "chebyshev": {
    "start_jd": 2433282.5,
    "end_jd": 2469807.5,
    "sun": {
      "chunks": 20,
      "chunk_years": 5,
      "zones": ["major", "major_asteroids"]
    },
    "moons": {
      "zones": [
        {"zone": "moons/earth", "chunks": 20, "chunk_years": 5.0},
        {"zone": "moons/mars", "chunks": 200, "chunk_years": 0.5},
        {"zone": "moons/jupiter", "chunks": 200, "chunk_years": 0.5},
        {"zone": "moons/saturn", "chunks": 800, "chunk_years": 0.125},
        {"zone": "moons/uranus", "chunks": 400, "chunk_years": 0.25},
        {"zone": "moons/neptune", "chunks": 400, "chunk_years": 0.25},
        {"zone": "moons/pluto", "chunks": 50, "chunk_years": 2.0}
      ]
    }
  }
}
```

`chebyshev` is only present when Chebyshev exports were produced (i.e. the
`[chebyshev]` section in `config.toml` matched kernels present at download
time). Clients should feature-detect it.

The `sun` tier uses uniform `chunks`/`chunk_years` across its zones (planets +
Sun barely move over years). The `moons` tier ships per-zone chunk cadence:
each parent's zone is tuned to ~200 KB/chunk, so Saturn's 21 whitelisted moons
ride 0.125y chunks while Pluto's four moons fit comfortably in 2y chunks. The
previous `moons/{parent}/{main,inner}` split was dropped — uniform per-parent
zones replace it. Clients index per-zone:
`chunk_idx = floor((jd - start_jd) / (chunk_years * 365.25))`.

## Zones and zoom levels

**Non-SBDB zones** (always zoom 0):
- `major` — Sun, planets, dwarf planets, barycenters, Lagrange points
- `moons` — natural satellites
- `earth` — spacecraft/debris orbiting Earth
- `spacecraft` — spacecraft/debris orbiting other bodies

**SBDB zones** — named after [orbit class](../data/src/space_map_data/models/object/sbdb.py) (e.g. `APO`, `MBA`, `TJN`):
- Zoom 0 = named objects
- Zoom 1 = unnamed objects

Each (zone, zoom) pair may have multiple parts (max 10,000 objects per part).

### Time-segmented zones

Two zones segment elements over time, with two distinct manifest shapes:

- **`earth`** — date-segmented. One snapshot per CelesTrak day. Metadata
  entry: `{start_date, end_date, parts}`. Path:
  `elements/earth/0/{YYYY-MM-DD}/{part}.bin.gz`. SGP4 accuracy degrades fast
  past the TLE epoch, so each snapshot's header `start_jd`/`end_jd` bounds
  it to `min(epoch)−14d … max(epoch)+14d`.

- **`moons`** — chunk-indexed. One snapshot per 6-month chunk over the
  Chebyshev coverage range. Method C secular elements are re-fitted at each
  chunk midpoint so Ω̇/ω̇/n_mean track multi-decade Kozai-Lidov-style drift
  on outer irregulars instead of being a single linear approximation across
  the whole range. Metadata entry: `{chunks, chunk_years, start_jd, parts}`.
  Path: `elements/moons/0/{chunk_idx}/{part}.bin.gz` where `chunk_idx` is a
  decimal integer (no zero-padding needed — clients compute it numerically
  and concatenate). Compute the chunk index from a JD with
  `floor((jd - start_jd) / (chunk_years * 365.25))`. Header
  `start_jd`/`end_jd` bound the chunk's validity window. Whitelisted moons
  (those with full Chebyshev coverage) ride along at every chunk with their
  single-epoch DB elements (constant across chunks).

Clients dispatch on field presence: `chunks` ⇒ chunk-indexed,
`start_date` ⇒ date-segmented, neither ⇒ static `{parts}`. The
discriminator is set explicitly per zone (via the `Snapshot.chunk_years`
field on the producer side), not inferred from label format.

## Binary elements file

Columnar binary format with zero-copy typed array support.

### Header (32 bytes)

| Offset | Type    | Field     |
|--------|---------|-----------|
| 0      | char[4] | Magic `SMAP` |
| 4      | uint16  | Version (5) |
| 6      | uint16  | Format type: 0 = Keplerian, 1 = Parabolic, 2 = SGP4 |
| 8      | float64 | `start_jd` — chunk validity start (JD TDB), `-Infinity` = unbounded |
| 16     | float64 | `end_jd` — chunk validity end (JD TDB, inclusive), `+Infinity` = unbounded |
| 24     | uint32  | Row count |
| 28     | uint8   | Source: `0 horizons, 1 sbdb, 2 celestrak, 3 spice, 255 unknown` — every row in the file shares this source |
| 29     | uint8   | Id type: `0 naif, 1 spkid, 2 norad_satcat, 255 unknown` — every row in the file shares this prefix; combine with column 0 (numeric ID) to rebuild the full `<prefix>-<numeric>` Object ID |
| 30     | uint16  | Reserved  |

One provider writes one zone/part (pipeline-enforced), so the source fits in a single file-level byte rather than per-row. The id type follows the same single-typed-chunk invariant — each (zone, zoom) query selects on the prefix-defining column, so one byte per file is enough. Frontend must mirror both ordinal mappings.

`start_jd`/`end_jd` define the window where propagation is defined for this
chunk. Outside it, consumers must hide every body in the file rather than call
the propagator — SGP4 diverges beyond the TLE epoch spread, and even Kepler
orbits fit from short observation arcs aren't trustworthy far out. Matches the
header convention in the Chebyshev export. Writers use `±Infinity` for
formats with no hard cutoff (Keplerian/parabolic orbits are mathematical
solutions); SGP4 chunks bound it to `min(epoch) − 14d … max(epoch) + 14d`.

### Keplerian columns (format type 0)

Each column is padded to 8-byte alignment. Julian Dates use float64 for sub-day precision; other numeric columns use float32 (~7 significant digits). See [Precision rationale](#precision-rationale) below.

| # | Name        | Type    | Missing | Notes |
|---|-------------|---------|---------|-------|
| 0 | id          | int32   | -1      | Numeric portion of `Object.id`; combine with the header's id-type byte to rebuild the full `<prefix>-<numeric>` form (e.g. id-type=0 + 399 → `naif-399`). Sourced from `naif_id`, `spkid`, or `norad_cat_id` per the chunk's id type. |
| 1 | object_type | uint8   | 255     | `ObjectType` ordinal (see below) |
| 2 | parent_id   | int32   | -1      | NAIF ID of central body (0 = SSB) |
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

Coordinate frame: ecliptic J2000.

Propagation with secular rates: `om(t) = om + om_dot · (jd − epoch_jd)`,
`w(t) = w + w_dot · (jd − epoch_jd)`. Sources that don't fit secular drift
(Horizons/SBDB/CelesTrak, plus SPICE rows for planets/dwarves/whitelisted
moons) write zeros, making the rate term a no-op. This captures J2/J4
nodal regression and apsidal precession on small moons (Phobos' ~−160°/yr,
inner Saturn/Neptune moons up to ~−300°/yr) without shipping per-frame
Chebyshev coefficients.

### ObjectType ordinals

```
0  barycenter       4  dwarf_planet    8  asteroid_main_belt   12  comet
1  lagrange_point   5  moon            9  asteroid_trojan      13  spacecraft
2  star             6  asteroid       10  asteroid_centaur      14  debris
3  planet           7  asteroid_inner 11  asteroid_tno          15  undocumented
```

### Scale and unit conversions

The `scale` flag determines how to interpret `a` and `n`:

| scale | a unit | n unit  | Context |
|-------|--------|---------|---------|
| 0 (planet) | km | rev/day | Earth-orbiting satellites |
| 1 (system) | AU | deg/day | Heliocentric objects, moons |

To consume uniformly, normalize planet-scale values: `a_au = a / 149_597_870.7`, `n_degday = n * 360`.

### SGP4 columns (format type 2)

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

`a` and `n` use the planet-scale units (km, rev/day) — the raw OMM values from
CelesTrak, which `json2satrec` expects unconverted.

### Parabolic columns (format type 1)

Used for the `PAR` zone. Parabolic comets (`e = 1`) lack a semi-major axis and mean motion; they use perihelion distance and time of perihelion instead.

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

To compute positions, use Barker's equation instead of Kepler's equation.

### Precision rationale

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

## Chebyshev ephemeris (`chebyshev/{zone}/{chunk}/`)

High-accuracy polynomial ephemeris for bodies that a user zooms in on — the
Sun, planets, dwarf planets, planetary-system barycenters, the 16 sb441-n16
asteroid perturbers, and ~30 whitelisted surface-feature moons. Each
(zone, time-chunk) pair is one gzipped binary; the per-body header carries
`id_type` + `obj_id_value` so consumers rebuild the full `{prefix}-{numeric}`
Object ID (e.g. `spkid-20134340` for Pluto) without a sidecar file. Evaluate
with Clenshaw's recursion on the Chebyshev basis.

Non-whitelisted moons (tiny irregulars, inner shepherds without surface
features) don't appear here — they're covered by the standard Keplerian
elements format with secular drift columns (om_dot, w_dot), populated via a
numerical mean-element fit at extraction time so the orbit captures J2/J4
secular precession without shipping per-frame Chebyshev coefficients.

### Zones

Two tiers; the `sun` tier shares chunk cadence across its zones, the `moons`
tier ships per-zone (per-parent) cadence so each chunk lands at ~200 KB
regardless of body density.

**Coarse, always-loaded set** (5y chunks, ~20 chunks over 100y):
- `major` — Sun, planets, dwarf planets, planetary-system barycenters.
- `major_asteroids` — the ~15 sb441-n16 perturber asteroids (Pallas, Vesta,
  Juno, Hebe, Iris, Hygiea, Eunomia, Psyche, Amphitrite, Europa-asteroid,
  Cybele, Sylvia, Thisbe, Davida, Interamnia — Ceres is in `major` as a
  dwarf planet).

**Per-system moons** — one zone per parent, each with its own `chunk_years`:
- `moons/earth` — the Moon (5y chunks).
- `moons/mars` — Phobos, Deimos (0.5y chunks).
- `moons/jupiter` — Galileans + Amalthea, Thebe (0.5y chunks).
- `moons/saturn` — 21 named bodies including ring shepherds and co-orbital
  Trojans (0.125y chunks; densest population).
- `moons/uranus` — 5 majors + 4 close-in chaotic shepherds (0.25y chunks).
- `moons/neptune` — Triton, Proteus + 4 close-in shepherds (0.25y chunks).
- `moons/pluto` — Charon, Nix, Kerberos, Styx (2y chunks).

The previous `moons/{parent}/{main,inner}` split was dropped; clients that
want to throttle network requests at high time-warp speeds should fall back
to the elements-format Kepler propagator (see Time-segmented zones above)
rather than skipping a Chebyshev sub-zone — accuracy loss at >1 week/second
is not visible at the resolutions where time-warp is used.

### Time chunks

Per-zone chunk cadence (`chunk_years`) is in the manifest. Chunk bounds are
in each file's header, so clients can convert JD → chunk index by reading
the per-zone entry from `metadata.json → chebyshev.{sun,moons}.zones[…]`
and computing `chunk_idx = floor((jd - start_jd) / (chunk_years * 365.25))`
against the top-level `start_jd`.

### Binary layout (`data.bin.gz`, little-endian)

**File header (32 bytes)**

| Offset | Type    | Field |
|--------|---------|-------|
| 0      | char[4] | Magic `SCHB` |
| 4      | uint16  | Version (2) |
| 6      | uint16  | Format type: 0 = position-only Chebyshev |
| 8      | float64 | start_jd (chunk start, JD TDB) |
| 16     | float64 | end_jd (chunk end, JD TDB) |
| 24     | uint32  | body_count |
| 28     | uint32  | Reserved |

**Per-body (repeats body_count times)**

Each body carries its own 24-byte header then a packed list of segments.

| Offset | Type    | Field |
|--------|---------|-------|
| 0      | int32   | naif_id (SPICE-side identifier; used for parent linking and frame indexing) |
| 4      | int32   | parent_naif_id (orbital reference body) |
| 8      | int32   | obj_id_value (numeric portion of the full `Object.id`; equals naif_id when id_type=naif) |
| 12     | float32 | radius_km (NaN if unknown) |
| 16     | uint16  | coeffs_per_axis (= polynomial degree + 1, per segment) |
| 18     | uint8   | id_type (`0 naif, 1 spkid, 2 norad_satcat, 255 unknown` — same ordinals as the elements header byte) |
| 19     | uint8   | Reserved |
| 20     | uint32  | segment_count |

Combine `id_type` with `obj_id_value` to rebuild the full Object ID for
cross-referencing with the elements export and object detail bundles. Pluto
and the perturber asteroids ride as `spkid-…` even though their SPICE
`naif_id` is the planetary ID, so consumers must not assume `naif-{naif_id}`.

Then `segment_count` segments, each laid out as:

| Type    | Field |
|---------|-------|
| float64 | seg_start_jd (JD TDB) |
| float64 | seg_end_jd (JD TDB, exclusive) |
| float32 × N | x coefficients (c₀ … c_{N-1}) |
| float32 × N | y coefficients |
| float32 × N | z coefficients |

where N = `coeffs_per_axis`. Each segment's coefficients form a Chebyshev
series in τ ∈ [-1, 1] giving the body's position in **km, ECLIPJ2000 frame,
relative to `parent_naif_id`**.

### Evaluating a position at time t (JD TDB)

1. For a body, pick the segment with `seg_start_jd ≤ t < seg_end_jd`
   (binary-search; segments are sorted).
2. Normalize: `τ = 2 (t - seg_start_jd) / (seg_end_jd - seg_start_jd) - 1`.
3. Evaluate each axis with Clenshaw's recursion on the coefficients.

The returned vector is parent-relative in km. Walk up the parent chain
(accumulating positions) to get SSB-relative or any other frame you need.

### Precision

Segment bounds stay float64 for JD precision (same rationale as the Keplerian
format's `epoch_jd`). Coefficients are float32: for the time windows and
sub-interval sizes produced by the pipeline, truncation error stays well below
meter-level for planets and sub-km for inner moons — below visualization
resolution in every realistic zoom.

## Object ID reconstruction

Object IDs (`naif-399`, `spkid-2000433`, `norad_satcat-25544`) are not shipped
as separate files — consumers rebuild them from the binary:

- **Elements**: combine the file-header `id_type` byte (offset 29) with column
  0 (`int32`) per row.
- **Chebyshev**: combine each body header's `id_type` (offset 18) with
  `obj_id_value` (offset 8).

Both formats use the same id-type ordinal map: `0 naif, 1 spkid, 2 norad_satcat, 255 unknown`.

## Element labels file (`.loc.{lang}.gz`)

One line per object, same order as the binary file. Each line:

```
{flag}\x1f{name}
```

- `\x1f` = ASCII Unit Separator
- Flag `0` = no localized entry exists — skip the localized fetch
- Flag `1` = localized entry exists in the target language's bundle
- Flag `2` = only English exists — fetch the English bundle instead

The flag selects *which tier* to fetch; the bucket id is derived from the
object id (see [Object detail files](#object-detail-files)).

## Object detail files

Object details are grouped into **hash-bucketed bundles** to keep the file
count manageable. The bundle count per tier (`N_global`, one `N_{lang}` per
language) is chosen at export time so average members-per-bundle stays near
target K (`K_global = 100`, `K_localized = 200`) regardless of DB size. The
resulting Ns are published in `metadata.json → object_bundles` so the
frontend can reconstruct URLs from an id alone — needed for deep links where
no element chunk has been loaded yet.

The bucket id for an object in tier T (global or a specific language) is:

```
bucket = sha256(id)[:4] as big-endian uint32, mod N_tier
```

Each bundle is a gzipped JSON object keyed by object id:
`{ "<id>": ObjectData, ... }`. Bundles split by hash — no zone structure in
the path, no co-location guarantee, but tight uniformity (max bundle ≈ 1.3×
average at K=100).

### Global (`objects/__global__/{bucket}.json.gz`)

Written for every exported object. `bucket = sha256(id)[:4] % N_global`. Each
bundle is a JSON object `{ "<id>": GlobalObjectData, ... }`.

`GlobalObjectData` contains cross-references, orbit source data, SBDB physical
parameters, and Wikidata quantities:

```typescript
interface GlobalObjectData {
  id: string;
  type: string;                       // ObjectType name
  name?: string;
  map_texture_available?: boolean;    // only present if true
  texture?: {                         // only when map_texture_available; mirrors systems/{bary}.json
    source: string;                   // source page URL
    organisation: string;             // short canonical label, deduplicable (e.g. "NASA", "USGS", "Björn Jónsson")
    type: string;                     // texture kind (cylindrical, cylindrical_tile, …)
    attribution?: string;             // long-form credit line; omitted when unavailable
    description?: string;
  };
  provisional_designation?: string;
  sbdb_primary_designation?: string;  // SBDB MPC designation (e.g. "2000 RU65")
  cross_refs?: {
    wikidata_qid?: string;
    naif_id?: number;
    spkid?: number;
    mpc_designation?: string;
    norad_cat_id?: number;
    cospar_id?: string;
  };
  nasa_science_url?: string;          // URL to science.nasa.gov page
  images?: ObjectImage[];             // from Wikidata P18/P154 + all Wikipedia languages
  orientation?: {                     // SPICE PCK IAU rotation polynomial
    // α(T) = pole_ra_0 + pole_ra_1·T   (T = Julian centuries since J2000)
    // δ(T) = pole_dec_0 + pole_dec_1·T
    // W(d) = w0 + w1·d + w2·d²         (d = days since J2000)
    pole_ra_0: number; pole_ra_1: number;
    pole_dec_0: number; pole_dec_1: number;
    w0: number; w1: number; w2: number;
  };
  nut_prec?: {                        // SPICE PCK nutation/precession sums (paired with /v1/nut_prec_angles.json)
    // α += Σ ra[i]  · sin(θ_i(T)),  δ += Σ dec[i] · cos(θ_i(T)),  W += Σ pm[i] · sin(θ_i(T))
    ra: number[]; dec: number[]; pm: number[];
  };
  radii?: {                           // SPICE PCK triaxial radii (km, body-fixed X/Y/Z)
    a: number; b: number; c: number;
  };
  orbit?: {
    epoch_jd: number; e: number; i: number;
    om: number; w: number;
    scale: "planet" | "system";
    parent_naif_id: number;
    source: "horizons" | "sbdb" | "celestrak";
    // Keplerian (standard orbits):
    a?: number; ma?: number; n?: number;
    // Parabolic (e=1 comets):
    q?: number; tp?: number;
    // SGP4 init fields (CelesTrak-sourced earth sats only) — feed into
    // satellite.js `json2satrec` so URL-navigated sats can build a satrec
    // before their element chunk arrives.
    bstar?: number;           // 1 / Earth radius
    mean_motion_dot?: number; // rev/day²
    mean_motion_ddot?: number; // rev/day³
    element_set_no?: number;
    rev_at_epoch?: number;
  };
  sbdb?: {
    neo?: boolean;   pha?: boolean;
    class?: string;  // OrbitClass enum *name* (e.g. "MBA", "APO") — same id used to name the export zone
    sats?: number;   diameter?: number;  // km
    extent?: string; albedo?: number; rot_per?: number;  // hours
    GM?: number;     // km^3/s^2
    mass?: { value: number; unit: string };
    H?: number; G?: number;
    spec_B?: string; spec_T?: string;
    BV?: number; UB?: number; IR?: number;
    moid?: number;   // AU, Earth MOID
    moid_jup?: number; t_jup?: number;
    per_y?: number;  // orbital period, years
    ad?: number;  // AU, aphelion distance
    prefix?: string; // comet prefix
    M1?: number; M2?: number; K1?: number; K2?: number; PC?: number;
    first_obs?: string;
    last_obs?: string;
    data_arc?: number;   // observation arc span, days
    n_obs_used?: number; // number of observations used
  };
  celestrak?: {                       // SATCAT metadata for CelesTrak-sourced satellites
    object_type?: string;             // payload / rocket_body / debris / unknown
    ops_status?: string;              // operational / nonoperational / partial / backup / spare / extended_mission / decayed / unknown
    data_status?: string;             // no_current_elements / no_initial_elements / no_elements_available
    launch_date?: string;             // ISO date
    decay_date?: string;              // ISO date
    period?: number;                  // minutes
    apogee?: number;                  // km
    perigee?: number;                 // km
    rcs?: number;                     // m²
    orbit_center?: string;            // earth / jupiter / moon / … / docked
    orbit_center_docked_to?: number;  // NORAD of host (only when orbit_center == "docked")
    launch_site_code?: string;        // SATCAT short code, see constants/earth_sats/launch_sites.py
    owner?: string;                   // SATCAT OWNER short code, see constants/earth_sats/sources.py
    constellation_slug?: string;      // see constants/earth_sats/constellations.py
    categories?: string[];            // SatelliteCategory values
    country_codes?: string[];         // ISO 3166-1 alpha-2 (feed into Intl.DisplayNames)
  };
  wikidata?: {
    discovery_date?: string;  // ISO 8601
    launch_date?: string;
    mass?: QuantityWithUnit;
    radius?: QuantityWithUnit;
    density?: QuantityWithUnit;
    surface_gravity?: QuantityWithUnit;
    absolute_magnitude?: number;
    apparent_magnitude?: number;
    temperature?: QuantityWithUnit;
    min_temperature?: QuantityWithUnit;
    max_temperature?: QuantityWithUnit;
    website?: string;
    blog?: string;
    capital_cost?: CurrencyQuantity;
    length?: QuantityWithUnit;
    width?: QuantityWithUnit;
  };
}

// Images collected from Wikidata P18/P154 + Wikipedia pageimages (all languages)
interface ObjectImage {
  file: string;           // Commons filename, used as the bundle directory name
  source_url: string;     // Wikimedia Commons file page URL (for license/attribution)
  kind: "photo" | "logo";
  variants: { [label in "s" | "m" | "xl"]?: string };  // label → extension
  width?: number;         // source pixel dimensions (omitted for SVG/WebM passthrough)
  height?: number;
}
// Quantities use best-fit units from Wikidata (e.g. "solar_mass", "kilometre")
interface QuantityWithUnit { value: number; unit: string; }
// Currencies use ISO 4217 codes (e.g. "EUR", "USD")
interface CurrencyQuantity { value: number; currency: string; }
```

### Localized (`objects/{lang}/{bucket}.json.gz`)

Per-language bundles. `bucket = sha256(id)[:4] % N_{lang}` where `N_{lang}`
is that language's count in `metadata.object_bundles`. An object appears in
the language's bundle only when Wikidata/Wikipedia data exists for that
language (per-row `flag` in the labels file: `1` = present, `2` = fallback
to `en` bundle, `0` = skip).

Each bundle is a JSON object `{ "<id>": LocalizedObjectData, ... }`. Entity
references link to Wikipedia where available.

```typescript
interface LocalizedObjectData {
  name?: string;          // Wikidata label in the target lang, falling back to English. Omitted if no Wikidata entity.
  description?: string;
  aliases?: string[];
  instance_of?: EntityRef[];
  discoverers?: EntityRef[];
  named_after?: EntityRef;
  discovery_site?: EntityRef;
  minor_planet_group?: EntityRef;
  spectral_type?: EntityRef;
  asteroid_family?: EntityRef;
  operators?: EntityRef[];        // merged from Wikidata P137 + CelesTrak, deduped
  constellation?: EntityRef;      // CelesTrak-derived
  manufacturer?: EntityRef;
  launch_vehicle?: EntityRef;
  launch_site?: EntityRef;        // CelesTrak-derived takes precedence over Wikidata P1427
  developer?: EntityRef[];
  funder?: EntityRef[];
  country_of_origin?: EntityRef[];
  launch_contractor?: EntityRef[];
  part_of?: EntityRef[];
  wikipedia?: {
    extract?: string;
    description?: string;
    url?: string;        // URL
  };
}

interface EntityRef { name: string; short_name?: string; wikipedia?: string; }
```

## Images

Sourced from Wikimedia Commons (Wikidata P18 image + P154 logo) and Wikipedia pageimages across all supported languages. Downloaded during the `commons` download step; the export step generates per-image thumbnail bundles.

**Path:** `v1/images/{filename}/{label}.{ext}` + `v1/images/{filename}/metadata.json.gz`

Each servable image is materialized as its own directory, keyed by the original Commons filename. The directory contains one or more size variants and a gzipped metadata blob.

### Size variants

| Label | Max dimension |
|-------|---------------|
| s     | 512 px        |
| m     | 1024 px       |
| xl    | 4096 px       |

Which labels appear — and what extension each carries — depends on the source format:

| Source                        | Downscaled buckets | Resting bucket (first ≥ source dim) |
|-------------------------------|--------------------|-------------------------------------|
| `.jpg` / `.jpeg`              | lossy webp         | verbatim `.jpg` (re-encoding lossy just degrades) |
| `.png` and other lossless     | lossy webp         | lossy webp at source dim            |
| animated `.gif` (n_frames > 1)| animated AVIF      | animated AVIF at source dim         |
| static `.gif`                 | lossy webp         | lossy webp at source dim            |
| `.svg`, `.webm`               | —                  | verbatim `xl.<ext>` (size-capped at 25 MiB) |
| `.pdf`, `.stl`, `.djvu`       | — (skipped entirely — not renderable as thumbnails)       ||

Buckets strictly above the resting bucket are not emitted (no upscaling). The `variants` field on each `ObjectImage` records `{label: ext}` for the emitted set.

### Per-image metadata (`v1/images/{filename}/metadata.json.gz`)

```typescript
interface ImageMetadata {
  schema: number;        // bumped when variant rules change; stale bundles are regenerated
  source_url: string;    // Commons file page URL
  variants: { [label: string]: string };  // mirrors ObjectImage.variants
  width?: number;        // source pixel dimensions (omitted for SVG/WebM passthrough)
  height?: number;
  license?: { name?: string; url?: string };       // from Commons extmetadata
  artist?: string | { [lang: string]: string };    // multilang or bare string
  description?: string | { [lang: string]: string };
}
```

Not cleaned on re-export — bundles are reused across runs. Schema mismatches trigger per-image regeneration; to force a full rebuild, wipe `v1/images/`.

## Textures

Generated during ingest (not export) and written directly to the export directory. An object's `map_texture_available` flag in its global JSON signals whether a texture exists.

**Path:** `textures/{id}/{tier}.webp`

| Tier   | Max dimension | Size target | Quality                              | Condition        |
|--------|---------------|-------------|--------------------------------------|------------------|
| low    | 2048 px       | 300 KiB     | lossy 80                             | always generated |
| medium | 8192 px       | 2 MiB       | lossy 80                             | source > 2048 px |
| high   | 16383 px      | 6 MiB       | lossy 80 or lossless if small enough | source > 8192 px |

16,383 px is the WebP hard limit per dimension.

The size is a target, not a hard limit. Some textures go over it.

### Texture metadata (`textures/{id}/metadata.json`)

```json
{
  "id": "naif-499",
  "source": "https://example.com/mars.tif",
  "organisation": "NASA",
  "attribution": "NASA/JPL-Caltech/MSSS. …",
  "description": "Mars surface map",
  "type": "map",
  "source_file": "mars_color.tif",
  "source_dimensions": [8192, 4096],
  "processed_at": "2025-01-01T00:00:00+00:00",
  "exports": {
    "low":    { "file": "low.webp",    "width": 2048, "height": 1024, "size_bytes": 290000, "lossless": false },
    "medium": { "file": "medium.webp", "width": 8192, "height": 4096, "size_bytes": 1800000, "lossless": false }
  }
}
```

- `source` — the page URL the texture was obtained from.
- `organisation` — short canonical label used for deduplicated UI attribution (e.g. `"NASA"`, `"USGS"`, `"ESA/DLR/FU Berlin"`, `"The Planetary Society"`, `"Björn Jónsson"`).
- `attribution` — optional long-form credit string. Populated from `download-metadata.yaml` where provided; for NASA/USGS-hosted textures this is expected to be auto-filled from the source page at ingest time. Omitted entirely when unavailable.

## System metadata (`systems/{barycenter_id}.json`)

Generated during export (not ingest). One file per planetary system, keyed by barycenter ID (e.g. `naif-3` for Earth-Moon, `naif-5` for Jupiter). Per-body entries carry available texture tiers, texture attribution, SPICE PCK orientation (pole/spin polynomial), nutation/precession coefficients, and triaxial radii when known.

```json
{
  "naif-399": {
    "tiers": ["high", "low", "medium"],
    "texture": {
      "source": "https://science.nasa.gov/earth/earth-observatory/blue-marble-next-generation/",
      "organisation": "NASA",
      "type": "cylindrical"
    },
    "orientation": {
      "pole_ra_0": 0.0, "pole_ra_1": -0.641,
      "pole_dec_0": 90.0, "pole_dec_1": -0.557,
      "w0": 190.147, "w1": 360.9856235, "w2": 0.0
    },
    "nut_prec": { "ra": [], "dec": [], "pm": [] },
    "radii": { "a": 6378.1366, "b": 6378.1366, "c": 6356.7519 }
  },
  "naif-301": { "tiers": ["low"], "texture": { "source": "…", "organisation": "NASA", "type": "cylindrical" } }
}
```

The frontend fetches this when entering a system: it preloads low-res textures for every listed body, applies the full IAU rotation polynomial + nutation sums to meshes, (where `radii` differ) flattens bodies into oblate ellipsoids, and shows per-organisation imagery attribution for bodies currently in view. `texture` mirrors the shape embedded in each body's global detail file.

## Credits (`credits.json`)

Aggregated attribution manifest read by the standalone `/credits` page. A
single non-gzipped JSON file so the page can render everything in one fetch
without walking per-system or per-body files.

```typescript
interface Credits {
  systems: Array<{
    id: string | null;           // barycenter object ID ("naif-3", …) or null for the standalone bucket
    name: string | null;         // primary-planet name ("Earth", "Jupiter", …); null for standalones
    textures: Array<{
      body_id: string;           // e.g. "naif-399"
      name: string;              // English display name; localisation is deferred
      source: string;            // attribution source URL
      organisation: string;      // short label, deduplicable (e.g. "NASA", "USGS")
      type: string;              // cylindrical / cylindrical_tile / …
      attribution?: string;      // long-form credit line when available
      description?: string;      // optional one-liner about the dataset
    }>;
  }>;
}
```

Systems are ordered Mercury → Pluto by barycenter NAIF ID; a final `id: null`
bucket collects standalones (sun-orbiting dwarf planets or asteroids such as
Ceres and Bennu). Each system's `textures` list is alphabetised by body name.
Only bodies whose texture metadata.json exists on disk are included —
asteroids or 3D mesh assets can slot into sibling keys (`models`,
`mesh_assets`, …) on the same file when those pipelines come online. Static
credits (orbital providers, SPICE/IAU rotation kernels, Wikidata, Wikipedia,
Wikimedia Commons, IAU nomenclature) live in the frontend page itself and
don't need to be emitted here.

## Nutation angles (`nut_prec_angles.json`)

A single tiny top-level file fetched once at app start. Lists the IAU nutation/precession angle pairs `(θ₀, θ₁)` defined per "owner" body — typically the planetary system barycenter. Bodies derive their owner as `naif_id // 100` if `naif_id ≥ 100`, else `naif_id`.

```json
{
  "1": [174.791086, 4.092335, 349.582171, 8.184670],
  "3": [125.045, -0.0529921, 250.089, -0.1059842],
  "5": [73.32, 91472.9, 24.62, 45137.2]
}
```

Each owner's array is a flat list of `[θ₀_1, θ₁_1, θ₀_2, θ₁_2, ...]` in degrees and degrees/century. Combined with each body's `nut_prec` coefficient arrays:

```
θ_i(T) = angles[2i] + angles[2i+1]·T          (T = Julian centuries since J2000)
α(T)  += Σ nut_prec.ra[i]  · sin(θ_i(T))
δ(T)  += Σ nut_prec.dec[i] · cos(θ_i(T))
W(d)  += Σ nut_prec.pm[i]  · sin(θ_i(T))
```

## Consuming the data

1. Fetch `metadata.json` to discover available chunks
2. For each (zone, zoom, part), fetch the two element files in parallel:
   - `.bin.gz` — parse with the binary format above; rebuild full IDs by
     combining the header's id-type byte with column 0 per row
   - `.loc.{lang}.gz` (labels) — split by newline, parse flag + name; index
     matches binary row order
3. Combine by array index to get full body records
4. Compute 3D positions from orbital elements using Kepler's equation at your target date (or Barker's equation for format type 1 / parabolic files)
5. Object detail bundles are fetched on demand by hashing the id: `bucket = sha256(id)[:4] % N`, where `N` comes from `metadata.object_bundles.global` (global) or `metadata.object_bundles.{lang}` (localized). Then fetch `objects/__global__/{bucket}.json.gz` and (when the label flag is non-zero) `objects/{lang}/{bucket}.json.gz` — fall back to the `en` bundle when the flag is `2`. Extract the entry by object id from the returned dict; cache the whole bundle to amortize neighbor lookups.
6. For bodies that also appear in `metadata.json → chebyshev.{sun|moons}.zones`,
   fetch the chunk covering the current simulated time from
   `chebyshev/{zone}/{chunk}/data.bin.gz`; rebuild each body's Object ID from
   its `id_type` + `obj_id_value` header fields. Prefer those positions over
   the Keplerian ones and fall back to Keplerian only for bodies not in the
   Chebyshev export.
