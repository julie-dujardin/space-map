# Export Format (v2)

All files are served under `/data/v1/` and are gzip-compressed unless noted.

## Directory structure

```
v1/
  metadata.json                                  (not gzipped)
  elements/{zone}/{zoom}/{part}.bin.gz           binary orbital elements
  elements/{zone}/{zoom}/{part}.id.gz            object IDs (text)
  elements/{zone}/{zoom}/{part}.loc.{lang}.gz    localized labels
  objects/__global__/{id}.json.gz                global object details
  objects/{lang}/{id}.json.gz                    localized object details
  textures/{id}/{tier}.webp                      tier = low | medium | high
  textures/{id}/metadata.json                    texture source + exports
  systems/{barycenter_id}.json                   per-system body metadata
```

## metadata.json

Entry point. Lists all available chunks so the consumer knows what to fetch.

```json
{
  "version": 1,
  "exported_at": "2025-01-01T00:00:00+00:00",
  "zones": {
    "major": {
      "zooms": {
        "0": { "parts": 1, "object_count": 42, "avg_part_bytes": 12345 }
      }
    }
  }
}
```

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

## Binary elements file

Columnar binary format with zero-copy typed array support.

### Header (16 bytes)

| Offset | Type   | Field     |
|--------|--------|-----------|
| 0      | char[4]| Magic `SMAP` |
| 4      | uint16 | Version (2) |
| 6      | uint16 | Format type: 0 = Keplerian, 1 = Parabolic |
| 8      | uint32 | Row count |
| 12     | uint32 | Reserved  |

### Keplerian columns (format type 0)

Each column is padded to 8-byte alignment. Julian Dates use float64 for sub-day precision; other numeric columns use float32 (~7 significant digits). See [Precision rationale](#precision-rationale) below.

| # | Name        | Type    | Missing | Notes |
|---|-------------|---------|---------|-------|
| 0 | id          | int32   | -1      | Source-specific numeric ID (`horizons_naif_id`, `sbdb_spkid`, or `celestrak_norad_cat_id`) |
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

Coordinate frame: ecliptic J2000.

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
| q (AU)     | 0 – 43                  | ~3 × 10⁻⁶ AU                | Parabolic comets only |
| radius_km  | 0.001 – 70,000          | ~0.004 km at max             | |

## Object IDs file (`.id.gz`)

Newline-delimited text, one ID per line, same order as the binary file. Format: `{source}-{numeric_id}`, e.g. `naif-399`, `spkid-2000433`, `norad_satcat-25544`.

## Element labels file (`.loc.{lang}.gz`)

One line per object, same order as the binary file. Each line:

```
{flag}\x1f{name}
```

- `\x1f` = ASCII Unit Separator
- Flag `0` = no object detail file exists
- Flag `1` = localized detail file exists at `objects/{lang}/{id}.json.gz`
- Flag `2` = only English fallback at `objects/en/{id}.json.gz`

## Object detail files

### Global (`objects/__global__/{id}.json.gz`)

Written for every exported object. Contains cross-references, orbit source data, SBDB physical parameters, and Wikidata quantities.

```typescript
interface GlobalObjectData {
  id: string;
  type: string;                       // ObjectType name
  name?: string;
  map_texture_available?: boolean;    // only present if true
  provisional_designation?: string;
  sbdb_primary_designation?: string;  // SBDB MPC designation (e.g. "2000 RU65")
  cross_refs?: {
    wikidata_qid?: string;
    horizons_naif_id?: number;
    sbdb_spkid?: number;
    sbdb_mcp_designation?: string;
    celestrak_norad_cat_id?: number;
    celestrak_cospar_id?: string;
  };
  nasa_science_url?: string;          // URL to science.nasa.gov page
  orientation?: {                     // SPICE PCK pole/spin (deg, deg/day)
    pole_ra: number; pole_dec: number; w0: number; w_rate: number;
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
  };
  sbdb?: {
    neo?: boolean;   pha?: boolean;   class?: string;
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
  wikidata?: {
    discovery_date?: string;  // ISO 8601
    launch_date?: string;
    image?: string;           // URL
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
    logo_image?: string;          // URL
    capital_cost?: CurrencyQuantity;
    length?: QuantityWithUnit;
    width?: QuantityWithUnit;
  };
}

// Quantities use best-fit units from Wikidata (e.g. "solar_mass", "kilometre")
interface QuantityWithUnit { value: number; unit: string; }
// Currencies use ISO 4217 codes (e.g. "EUR", "USD")
interface CurrencyQuantity { value: number; currency: string; }
```

### Localized (`objects/{lang}/{id}.json.gz`)

Only written when Wikidata/Wikipedia data exists for the language. Entity references link to Wikipedia where available.

```typescript
interface LocalizedObjectData {
  name?: string;
  description?: string;
  aliases?: string[];
  instance_of?: EntityRef[];
  discoverers?: EntityRef[];
  named_after?: EntityRef;
  discovery_site?: EntityRef;
  minor_planet_group?: EntityRef;
  spectral_type?: EntityRef;
  asteroid_family?: EntityRef;
  operator?: EntityRef;
  manufacturer?: EntityRef;
  launch_vehicle?: EntityRef;
  launch_site?: EntityRef;
  developer?: EntityRef[];
  funder?: EntityRef[];
  country_of_origin?: EntityRef[];
  launch_contractor?: EntityRef[];
  part_of?: EntityRef[];
  wikipedia?: {
    extract?: string;
    description?: string;
    thumbnail?: string;  // URL
    image?: string;      // URL
    url?: string;        // URL
  };
}

interface EntityRef { name: string; wikipedia?: string; }
```

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

## System metadata (`systems/{barycenter_id}.json`)

Generated during export (not ingest). One file per planetary system, keyed by barycenter ID (e.g. `naif-3` for Earth-Moon, `naif-5` for Jupiter). Per-body entries carry available texture tiers, SPICE PCK orientation (pole/spin), and triaxial radii when known.

```json
{
  "naif-399": {
    "tiers": ["high", "low", "medium"],
    "orientation": { "pole_ra": 0.0, "pole_dec": 90.0, "w0": 190.147, "w_rate": 360.9856235 },
    "radii": { "a": 6378.1366, "b": 6378.1366, "c": 6356.7519 }
  },
  "naif-301": { "tiers": ["low"] }
}
```

The frontend fetches this when entering a system: it preloads low-res textures for every listed body, applies axial tilt + spin to meshes, and (where `radii` differ) flattens bodies into oblate ellipsoids.

## Consuming the data

1. Fetch `metadata.json` to discover available chunks
2. For each (zone, zoom, part), fetch the three element files in parallel:
   - `.bin.gz` — parse with the binary format above
   - `.id.gz` (IDs) — split by newline, index matches binary row order
   - `.loc.{lang}.gz` (labels) — split by newline, parse flag + name
3. Combine by array index to get full body records
4. Compute 3D positions from orbital elements using Kepler's equation at your target date (or Barker's equation for format type 1 / parabolic files)
5. Object detail files are fetched on demand using the ID and the label flag
