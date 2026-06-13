# Export Format (v1 directory, position binary v7)

All files are served under `/data/v1/` and are gzip-compressed unless noted.

## Directory structure

```
v1/
  metadata.json                                   (not gzipped)
  credits.json                                    (not gzipped) aggregated attribution for the /credits page
  labels/{lang}.gz                                pre-interaction labels for the promoted set (one per language)
  position/
    {zone}/{zoom}/{part}.bin.gz                   static parted        — small_bodies/{class} zones, Earth-orbit spacecraft
    {zone}/{zoom}/{label}/{part}.bin.gz           time-chunked + parted — earth (date label), moons (chunk-idx label)
    {zone}/{zoom}/{chunk}.bin.gz                  time-chunked, unparted — chebyshev zones
    probes/{zone}/{chunk}.bin.gz                  time-chunked, no zoom segment — interplanetary probes (format byte = 2)
  objects/__global__/{bucket}.json.gz             global object details, hash-bucketed
  objects/{lang}/{bucket}.json.gz                 localized details, hash-bucketed
  nomenclature/positions/{body_id}.bin.gz         IAU surface-feature marker positions (SMNF format)
  nomenclature/__global__/{body_id}.json.gz       lean per-body marker metadata (name, approval_date, origin, parent_feature_id)
  nomenclature/details/__global__/{bucket}.json.gz   feature detail bundles, hash-bucketed by `{body_id}:{feature_id}`
  nomenclature/details/{lang}/{bucket}.json.gz       localized feature details, hash-bucketed
  v1/images/{filename}/{label}.{ext}              thumbnail variants (label = s | m | xl)
  v1/images/{filename}/metadata.json.gz           per-image license + variants map
  textures/{id}/{tier}.webp                       tier = low | medium | high (single-frame)
  textures/{id}/{tier}_{NN}.webp                  monthly frames (type = cylindrical_monthly), NN = 01..frames
  textures/{id}/metadata.json                     texture source + exports
  textures/{id}_clouds/{tier}_{YYYYMMDDHH}.webp   cloud-overlay snapshots (type = clouds_overlay)
  textures/{id}_clouds/metadata.json              cloud-overlay source + tier/frame inventory
  textures/{id}_specular/{tier}.webp              specular/roughness map (type = cylindrical_specular)
  textures/{id}_specular/metadata.json            specular source + exports
  textures/stars/{tier}_{face}.webp               cubemap-skybox faces (type = cubemap_skybox), face ∈ px|nx|py|ny|pz|nz
  textures/stars/metadata.json                    skybox source + per-face exports
  rings/{id}/{channel}.webp                       channel = backscattered | forwardscattered | unlitside | transparency | color
  rings/{id}/metadata.json                        ring source + geometry + per-channel files
  models/{slug}/{tier}.glb                          tier = low | high — Meshopt geometry + WebP textures
  models/{slug}/metadata.json                       model kind + missions + per-tier exports (incl. credit)
  systems/global.json                             (not gzipped) always-loaded: per-body GMs + IAU nutation angles
  systems/{barycenter_id}.json                    per-system body metadata, loaded on system entry
```

Every file under `position/` shares one binary format (`SMAP` v7, common 24-byte
header + 8-byte format-specific extension); the format byte at offset 6 of the
header dispatches between the columnar **elements** payload (Keplerian /
Parabolic / SGP4), the per-body **chebyshev** segments, and the per-probe
**probes** payload (mixed Kepler-with-drift + Chebyshev sub-chunks). One file
carries exactly one payload kind — bodies covered by chebyshev are excluded from
elements files entirely (no ride-along), since the frontend can derive
osculating Kepler elements from chebyshev positions when it needs to.

## metadata.json

Entry point. Every `position/zones/{zone}/zooms/{zoom}` entry carries a
`shape` discriminator that tells the URL builder which path template to use:

```jsonc
{
  "position": {
    "zones": {
      "small_bodies/MBA": {
        "zooms": {
          "0": { "shape": "parted", "parts": 12 },
          "1": { "shape": "parted", "parts": 47 }
        },
        "parent_id_type": "naif"
      },
      "small_body_moons": {
        "zooms": {
          "0": { "shape": "parted", "parts": 1 }
        },
        "parent_id_type": "spkid"
      },
      "earth": {
        "zooms": {
          "0": {
            "shape": "chunked-parted",
            "label": "date",
            "start_date": "2026-04-23",
            "end_date": "2026-04-26",
            "parts": 2
          }
        }
      },
      "moons": {
        "zooms": {
          "0": {
            "shape": "chunked-parted",
            "label": "index",
            "chunks": 200,
            "chunk_years": 0.5,
            "start_jd": 2433282.5,
            "parts": 1
          }
        }
      },
      "major": {
        "zooms": {
          "0": {
            "shape": "chunked",
            "chunks": 20,
            "chunk_years": 5.0,
            "start_jd": 2433282.5,
            "end_jd": 2469807.5
          },
          "1": { "shape": "parted", "parts": 1 }
        }
      },
      "moons/jupiter": {
        "zooms": {
          "0": {
            "shape": "chunked",
            "chunks": 200,
            "chunk_years": 0.5,
            "start_jd": 2433282.5,
            "end_jd": 2469807.5
          }
        }
      },
      "probes/interplanetary": {
        "shape": "chunked",
        "chunks": 100,
        "chunk_years": 1.0,
        "start_jd": 2433282.5,
        "end_jd": 2469807.5,
        "subchunk_days": 7.0,
        "float64_coeffs": true,
        "fit_center_naif_id": 10,
        "parent_id_type": "probe",
        "present": [[27, 99]]
      }
    }
  },
  "object_bundles": {
    "global": 1093,
    "en": 208, "fr": 208, "ja": 208, "ar": 201, "ru": 208, "zh": 208
  },
  "feature_bundles": {
    "global": 90,
    "en": 17, "fr": 12, "ja": 2, "ar": 2, "ru": 10, "zh": 13
  },
  "group_bundles": {
    "global": 6,
    "en": 4, "fr": 4, "ja": 4, "ar": 3, "ru": 4, "zh": 4
  },
  "skybox": {
    "id": "stars",
    "type": "cubemap_skybox",
    "encoding": "webp",
    "frame": "j2000",
    "faces": ["px", "nx", "py", "ny", "pz", "nz"],
    "tiers": ["low", "high"],
    "tier_face_size": { "low": 2048, "high": 4096 },
    "source": "https://svs.gsfc.nasa.gov/4851/",
    "organisation": "NASA",
    "attribution": "..."
  }
}
```

The `skybox` block is omitted when no cubemap-skybox bundle is present in
the export. The frontend loads face URLs as
`/v1/textures/{skybox.id}/{tier}_{face}.webp` and picks the largest tier
whose `tier_face_size[tier]` fits the device's max texture dimension.

### Shape → URL

| `shape`           | URL                                              | Used by                              |
|-------------------|--------------------------------------------------|--------------------------------------|
| `parted`          | `position/{zone}/{zoom}/{part}.bin.gz`           | `small_bodies/{class}` zones, Earth-orbit spacecraft, major/1 (horizons-sourced dwarves), major/2 (SBDB dwarves) |
| `chunked-parted`  | `position/{zone}/{zoom}/{label}/{part}.bin.gz`   | `earth` (label = ISO date), `moons` (label = chunk index) |
| `chunked` (zoomed) | `position/{zone}/{zoom}/{chunk}.bin.gz`         | every chebyshev zone (`major`, `major_asteroids`, `moons/{parent}`) |
| `chunked` (flat)  | `position/{zone}/{chunk}.bin.gz`                 | probe zones (`probes/*`) — manifest entry has no `zooms` wrapper, signalling no zoom segment in the URL |

`chunked-parted` carries an extra `label` discriminator: `"date"` for ISO
dates (`earth`), `"index"` for numeric chunk indices (`moons` Method-C secular
elements). Clients dispatch on `label` to format the path segment.

The `chunked` shape carries `chunks` and `chunk_years`; clients compute
`chunk_idx = floor((jd - start_jd) / (chunk_years * 365.25))`. There's no
parts axis on chebyshev — files are tuned to ~200 KB by adjusting
`chunk_years` per zone.

Probe zones use the same `chunked` shape but with the manifest entry placed
directly at zone level (no `zooms` wrapper). That signals the URL builder to
omit the zoom segment: `position/probes/interplanetary/47.bin.gz` rather
than `position/probes/interplanetary/0/47.bin.gz`. Probes never need
multi-resolution tiers — per-zone routing already picks the right detail
level — so the zoom level would always be `0` and is elided for clarity.

Probe zones are **sparse**: the writer only emits a file for a chunk index
when ≥1 probe contributes (Pluto only during the New Horizons flyby,
Uranus/Neptune only across the Voyager 2 windows, …), so most `chunk_idx ∈
[0, chunks)` slots have no file. To avoid speculative 404s, each probe-zone
manifest entry carries a `present` field listing every chunk index a file
actually exists for, collapsed into inclusive-inclusive ranges:

```
"present": [[27, 99]]          // interplanetary — dense, one contiguous range
"present": [[129, 132]]        // pluto — New Horizons flyby only
"present": []                  // zone planned but no probe contributed
```

Clients should treat any `chunk_idx` outside every `[start, end]` pair as
authoritatively absent and skip the GET. Indices are the same values used in
the URL (`{zone}/{chunk_idx}.bin.gz`).

## Zones and zoom levels

**Non-SBDB zones** (zoom 0 unless noted):
- `major` zoom 0 — chebyshev for Sun, planets, Pluto, Ceres (shape `chunked`).
- `major` zoom 1 — horizons-sourced majors not in any SPK kernel; in practice
  dwarf planets with Horizons ephemerides but no chebyshev coverage.
- `major` zoom 2 — SBDB-only dwarves (Eris, Makemake, Quaoar, …) that aren't
  in any SPK kernel and still need a Kepler propagator.
- `major_asteroids` — the ~15 sb441-n16 perturber asteroids (chebyshev only).
- `moons` — non-whitelisted moons of planets with Method-C secular elements
  (chunk-indexed). Excludes SBDB-discovered satellites of small bodies — those
  ride in `small_body_moons`.
- `moons/{parent}` — whitelisted moons under each parent body, chebyshev coverage.
- `small_body_moons` — moons of asteroids/comets discovered via SBDB's
  per-object satellite payload (e.g. Dactyl around Ida, Linus around Kalliope).
  Static-parted, system-scale Keplerian. Only orbit-bearing rows ship here;
  publication-placeholder rows (no orbit) appear in object bundles for
  navigation but not in this position file. Parent ids are SPK-IDs (small
  bodies don't have NAIF IDs), surfaced in the manifest via `parent_id_type:
  "spkid"`.
- `earth` — Earth-orbiting spacecraft/debris (SGP4, date-segmented).
- `spacecraft` — spacecraft/debris orbiting other bodies.
- `probes/{zone}` — interplanetary and planetary-system probes refit from
  NASA/ESA SPICE kernels. One zone per Hill-sphere-2× region: `interplanetary`,
  `mercury`, `venus`, `earth-moon`, `mars`, `jupiter`, `saturn`, `uranus`,
  `neptune`, `pluto`. Mixed Kepler-with-drift + Chebyshev per sub-chunk —
  see [Probes payload](#probes-payload-format-byte--2). A probe shows up in
  every zone its trajectory passes through (cruise + planet captures), so
  the same probe can appear in multiple zone files at different times.

**`small_bodies/{class}`** — SBDB-sourced asteroids and comets, one zone per
[orbit class](../data/src/space_map_data/models/object/sbdb.py) (`small_bodies/APO`, `small_bodies/MBA`, `small_bodies/TJN`, …):
- Zoom 0 = named objects
- Zoom 1 = unnamed objects

Each (zone, zoom) pair may have multiple parts (10,000 objects per part).
Objects are hash-bucketed across parts by `Object.random_int` so the same id
always lands in the same part across runs — required for the per-part
incremental sidecar to be meaningful.

The shared `small_bodies/` prefix lets export wipe + prune target the whole
group as a unit: a fresh SBDB pull invalidates every part, but no other
zone's outputs are touched.

### Incremental export

Both `earth` and `small_bodies/{class}` parts carry a `{part}.meta.json`
sidecar (stored in `EXPORT_METADATA_DIR` mirror, never published) recording
the upstream snapshot that produced them:

- `earth/{zoom}/{date}/{part}.meta.json` — fingerprints the CelesTrak CSVs
  for that day (`name + mtime_ns + size` per CSV). A re-downloaded day
  invalidates only that date's parts.
- `small_bodies/{class}/{zoom}/{part}.meta.json` — fingerprints the SBDB
  download metadata (`downloaded_at + record_count + complete`). The unit
  of cacheability is the whole SBDB snapshot, so a re-download invalidates
  every `small_bodies/*` part; a no-op re-export drops the cost to a
  sidecar scan.

Both sidecar shapes carry `format_version` so a writer/encoding change
invalidates everything regardless of upstream freshness. Probes use the
same pattern at `probes/{zone}/{chunk}.meta.json` (see [Probes payload](#probes-payload-format-byte--2)).

A post-export prune pass walks `position/small_bodies/` and deletes orphan
parts (and their sidecars) that this run didn't plan — covers asteroids
moving between classes, class shrinkage, or zooms disappearing.

Above the per-part sidecars sit run-level skip gates (all in the
`EXPORT_METADATA_DIR` mirror, see `export/pipeline/incremental.py`):

- `position/{zone}/{zoom}/__zone__.meta.json` — per-zone signature plus the
  snapshot stats `metadata.json` needs. A matching zone skips its DB load
  and per-object build entirely, not just the re-encode.
- `position/chebyshev.meta.json` / `position/probes/__pass__.meta.json` —
  gate those whole passes behind their input fingerprints (npz tree /
  kernels + events + candidates + registry), caching the manifest fragments.
- `tier_b.meta.json` — fingerprint over everything feeding the per-object
  outputs (ingest stamp, wikidata/wikipedia/images download stamps, kernel
  tree). When it matches, bundles / labels / nomenclature details /
  messages / groups are skipped and their bucket counts reused.

Zone and pass skips require a clean tier-B fingerprint: DB- and
wikidata-derived row state (membership, `has_localized`, radius overrides)
is only tracked there. The `ingest_stamp` DB table is rewritten by every
ingest run, so any ingest invalidates tier B.

### Time-segmented zones

Two zones segment elements over time, distinguished by `label` in the
manifest:

- **`earth`** — date-segmented (`label: "date"`). One snapshot per CelesTrak
  day. Path: `position/earth/0/{YYYY-MM-DD}/{part}.bin.gz`. SGP4 accuracy
  degrades fast past the TLE epoch, so each snapshot's header
  `start_jd`/`end_jd` bounds it to `min(epoch)−14d … max(epoch)+14d`.

- **`moons`** — chunk-indexed (`label: "index"`). One snapshot per 6-month
  chunk over the Chebyshev coverage range. Method C secular elements are
  re-fitted at each chunk midpoint so Ω̇/ω̇/n_mean track multi-decade
  Kozai-Lidov-style drift on outer irregulars instead of being a single
  linear approximation across the whole range. Path:
  `position/moons/0/{chunk_idx}/{part}.bin.gz`. Compute the chunk index from
  a JD with `floor((jd - start_jd) / (chunk_years * 365.25))`. Header
  `start_jd`/`end_jd` bound the chunk's validity window. Whitelisted moons
  are absent from `moons` — they ride in their parent's chebyshev zone
  instead.

## Binary format — common header

Every file under `position/` starts with the same 24-byte common header,
followed by an 8-byte format-specific extension (32 bytes total before the
payload).

### Common header (24 bytes, 8-aligned)

| Offset | Type    | Field |
|--------|---------|-------|
| 0      | char[4] | Magic `SMAP` |
| 4      | uint16  | Version (10) |
| 6      | uint8   | Format: `0 = elements, 1 = chebyshev, 2 = probes` |
| 7      | uint8   | Reserved |
| 8      | float64 | `start_jd` — file validity start (JD TDB), `-Infinity` = unbounded |
| 16     | float64 | `end_jd` — file validity end (JD TDB), `+Infinity` = unbounded |

`start_jd`/`end_jd` define the window where propagation is defined for this
file. Outside it, consumers must hide every body in the file rather than call
the propagator — SGP4 diverges beyond the TLE epoch spread, and even Kepler
orbits fit from short observation arcs aren't trustworthy far out. Writers
use `±Infinity` for formats with no hard cutoff (Keplerian/parabolic orbits
are mathematical solutions); SGP4 files bound it to `min(epoch) − 14d …
max(epoch) + 14d`.

## Elements payload (format byte = 0)

Columnar binary format with zero-copy typed array support.

### Elements extension (8 bytes, offsets 24..31)

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

### Keplerian columns (sub-format = 0)

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

### SGP4 columns (sub-format = 2)

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

### Parabolic columns (sub-format = 1)

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

## Chebyshev payload (format byte = 1)

High-accuracy polynomial ephemeris for bodies that a user zooms in on — the
Sun, planets, dwarf planets, planetary-system barycenters, the 16 sb441-n16
asteroid perturbers, and ~30 whitelisted surface-feature moons. Each
(zone, time-chunk) pair is one gzipped binary at
`position/{zone}/0/{chunk}.bin.gz`; the per-body header carries `id_type` +
`obj_id_value` so consumers rebuild the full `{prefix}-{numeric}` Object ID
(e.g. `spkid-20134340` for Pluto) without a sidecar file. Evaluate with
Clenshaw's recursion on the Chebyshev basis.

Non-whitelisted moons (tiny irregulars, inner shepherds without surface
features) don't appear here — they're covered by the `moons` elements zone
with secular drift columns (`om_dot`, `w_dot`), populated via a numerical
mean-element fit at extraction time so the orbit captures J2/J4 secular
precession without shipping per-frame Chebyshev coefficients.

### Zones

Two tiers; the coarse set shares chunk cadence across zones, while moons
ship per-zone (per-parent) cadence so each chunk lands at ~200 KB regardless
of body density.

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

Per-zone chunk cadence (`chunks`, `chunk_years`, `start_jd`, `end_jd`) lives
under each zone's `position.zones[zone].zooms[0]` entry with
`shape: "chunked"`.

### Chebyshev extension (8 bytes, offsets 24..31)

| Offset | Type    | Field |
|--------|---------|-------|
| 24     | uint32  | body_count |
| 28     | uint32  | Reserved (zero) |

### Per-body header (24 bytes, repeats body_count times)

| Offset | Type    | Field |
|--------|---------|-------|
| 0      | int32   | naif_id (SPICE-side identifier; used for parent linking and frame indexing) |
| 4      | int32   | parent_id (orbital reference body) |
| 8      | int32   | obj_id_value (numeric portion of the full `Object.id`; equals naif_id when id_type=naif) |
| 12     | float32 | radius_km (NaN if unknown) |
| 16     | uint16  | coeffs_per_axis (= polynomial degree + 1, per segment) |
| 18     | uint8   | id_type (`0 naif, 1 spkid, 2 norad_satcat, 255 unknown` — same ordinals as the elements extension byte) |
| 19     | uint8   | has_localized (1 iff the body has a localized detail bundle in at least one language) |
| 20     | uint8   | object_type (`ObjectType` ordinal — same map as the elements `objectType` column) |
| 21     | uint8   | Reserved |
| 22     | uint16  | segment_count |

Combine `id_type` with `obj_id_value` to rebuild the full Object ID for
cross-referencing with the elements export and object detail bundles. Pluto
and the perturber asteroids ride as `spkid-…` even though their SPICE
`naif_id` is the planetary ID, so consumers must not assume `naif-{naif_id}`.

`object_type` lets the frontend construct full body records (with the right
rendering style) from chebyshev alone, since cheb-covered bodies don't ship
in any elements file.

### Per-segment layout

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
relative to `parent_id`**.

### Evaluating a position at time t (JD TDB)

1. For a body, pick the segment with `seg_start_jd ≤ t < seg_end_jd`
   (binary-search; segments are sorted).
2. Normalize: `τ = 2 (t - seg_start_jd) / (seg_end_jd - seg_start_jd) - 1`.
3. Evaluate each axis with Clenshaw's recursion on the coefficients.

The returned vector is parent-relative in km. Walk up the parent chain
(accumulating positions) to get SSB-relative or any other frame you need.

### Precision

Segment bounds stay float64 for JD precision (same rationale as the elements
format's `epoch_jd`). Coefficients are float32: for the time windows and
sub-interval sizes produced by the pipeline, truncation error stays well
below meter-level for planets and sub-km for inner moons — below
visualization resolution in every realistic zoom.

## Probes payload (format byte = 2)

Spacecraft trajectories refit from NASA / ESA / NAIF-PDS SPICE kernels.
Each `(zone, chunk_idx)` file aggregates EVERY probe whose coverage
intersects the chunk's time window. Within a probe, the trajectory is
sliced into fixed-width **sub-chunks** (`subchunk_days` from the chunk
header) — each sub-chunk is independently fit as one of:

  * **Kepler pure** — 6-element snapshot at the snapshot epoch, propagated
    by `conics` (mu from the zone's central body), plus 1 anchor offset.
    Cheap (28/56 B). Used for clean heliocentric cruise where there's no
    J2 source.
  * **Kepler drift** — 6 snapshot elements + linear-fit `Ω̇, ω̇, Ṁ` + 1
    anchor offset (40/80 B). Used for J2-perturbed planetary orbiters
    (MAVEN, MEX, …); `Ṁ` absorbs any J2 mean-motion correction so the
    propagation honors secular drift without an analytic J2 term.
  * **Chebyshev** — degree-11 polynomial coefficients over a uniform
    sub-segment grid (3 axes × 12 coeffs = 144 / 288 B per segment).
    Used during flybys, maneuvers, EDLs, and other windows where Kepler
    error exceeds the zone threshold. Segment time bounds are NOT
    stored — they're implicit from the sub-chunk window divided by the
    coefficient count.
  * **Uncoverable** — placeholder when no fit produced finite output
    (typically a SPICE sampling failure mid-sub-chunk). Empty payload;
    the consumer hides the probe during that window.

A probe naturally switches methods over time — cruise on Kepler-pure,
flybys on Chebyshev, low-orbit phases on Kepler-drift.

### Probes extension (8 bytes, offsets 24..31)

| Offset | Type    | Field |
|--------|---------|-------|
| 24     | uint32  | `probe_count` |
| 28     | float32 | `subchunk_days` (from the zone's `kepler_subchunk_days`) |

`subchunk_days` is shared across every probe in the file — it's a zone
property — so it's promoted to the file header rather than repeated per
probe.

### Per-probe header (12 bytes, repeats `probe_count` times)

| Offset | Type    | Field |
|--------|---------|-------|
| 0      | int32   | `obj_id_value` — `probe_id` (combine with `id_type=PROBE` to rebuild `probe-{value}`) |
| 4      | uint8   | `id_type` (always `4` = `PROBE`; see [Object ID reconstruction](#object-id-reconstruction)) |
| 5      | uint8   | `object_type` (`ObjectType` ordinal — currently always `spacecraft`) |
| 6      | uint8   | `has_localized` (1 iff the probe has a localized detail bundle) |
| 7      | uint8   | Reserved |
| 8      | uint16  | `n_subchunks` |
| 10     | uint16  | `first_subchunk_offset` (in units of `subchunk_days`, from the chunk's `start_jd`) |

`first_subchunk_offset` lets probes start partway into a chunk without
having to ship dummy leading sub-chunks. The first sub-chunk's time bounds
are:

```
sub0_start_jd = chunk.start_jd + first_subchunk_offset * subchunk_days
sub0_end_jd   = sub0_start_jd + subchunk_days
```

Subsequent sub-chunks advance by `subchunk_days` each. No explicit
sub-chunk time bounds are stored.

### Per-sub-chunk record (8-byte header + variable payload)

Each probe's `n_subchunks` records follow its header, in time order:

| Offset | Type    | Field |
|--------|---------|-------|
| 0      | uint8   | `method` (`0 uncoverable, 1 kepler_pure, 2 kepler_drift, 3 chebyshev`) |
| 1      | uint8   | Reserved |
| 2      | uint16  | Reserved |
| 4      | uint32  | `payload_len` (bytes following this header) |
| 8      | ...     | Method-specific payload (see below) |

`payload_len` is `uint32` because the finest-intlen Chebyshev sub-chunks
(interplanetary 7-day window × 0.03-day intlen × float64) can reach
~67 KiB and overflow a `uint16`.

### Method payloads

Coefficient dtype is **float32** by default, or **float64** when the
zone's `float64_coeffs` flag is `true` (currently only `probes/interplanetary`,
which sees Voyagers at 100+ AU where float32's ~600 km quantization floor
would dominate).

**`kepler_pure` (method = 1)** — 6 elements + 1 anchor offset:
```
[ a_km, e, i_rad, om0, w0, m0, t_anchor_offset_s ]   # 28 B (f32) or 56 B (f64)
```
The fit doesn't anchor at the sub-chunk midpoint — it anchors at
`t_snap`, the closest valid SPICE sample to the midpoint (some samples
get rejected when the orbit goes hyperbolic at flybys). `t_anchor_offset_s`
stores `t_snap - sub_t_start_et` so the consumer can reconstruct the
correct propagation epoch. Without it the implicit-midpoint assumption
costs millions of km on cruise probes.

Evaluation:
```
t_anchor = sub_t_start_et + t_anchor_offset_s
rp       = a_km * (1 - e)
position = spiceypy.conics([rp, e, i_rad, om0, w0, m0, t_anchor, mu], et)
```
where `mu` is the gravitational parameter of the zone's central body
(`fit_center_naif_id`). `conics` propagates `M` via `mu` from `t_anchor`.

**`kepler_drift` (method = 2)** — 9 elements + 1 anchor offset:
```
[ a_km, e, i_rad, om0, w0, m0,
  om_dot, w_dot, n_mean_rad_s,
  t_anchor_offset_s ]                                # 40 B (f32) or 80 B (f64)
```
Evaluate by manually drifting `om`, `w`, `M` from `t_anchor`, then calling
`conics` with `t0=et` (so it doesn't re-propagate `M`):
```
t_anchor = sub_t_start_et + t_anchor_offset_s
dt       = et - t_anchor
om_t     = om0 + om_dot * dt
w_t      = w0  + w_dot  * dt
m_t      = m0  + n_mean_rad_s * dt
position = spiceypy.conics([rp, e, i_rad, om_t, w_t, m_t, et, mu], et)
```
The fitted `n_mean_rad_s` (vs. `sqrt(mu/a³)`) bakes any J2 `Ṁ` correction
into the propagation.

**`chebyshev` (method = 3)** — `n_seg × 3 × (degree+1)` packed coefficients:
```
[ seg0_x_c0 … seg0_x_c11,
  seg0_y_c0 … seg0_y_c11,
  seg0_z_c0 … seg0_z_c11,
  seg1_x_c0 … ]                      # n_seg × 144 B (f32) or 288 B (f64)
```
`n_seg = payload_len / (3 * (degree+1) * coeff_bytes)`. Segments uniformly
divide the sub-chunk:
```
seg_dt = subchunk_days_seconds / n_seg
seg_k_start_et = sub_start_et + k * seg_dt
seg_k_end_et   = sub_start_et + (k+1) * seg_dt
```
Within a segment, evaluate each axis with Clenshaw's recursion on
`τ = 2 * (et - seg_k_start_et) / seg_dt - 1` ∈ `[-1, 1]`. Position is in
**km, ECLIPJ2000 frame, relative to the zone's `fit_center_naif_id`**:

| Zone                   | `fit_center_naif_id` | Frame center |
|------------------------|---------------------:|--------------|
| `probes/interplanetary`| 10  | Sun |
| `probes/mercury`       | 199 | Mercury |
| `probes/venus`         | 299 | Venus |
| `probes/earth-moon`    | 399 | Earth |
| `probes/mars`          | 499 | Mars |
| `probes/jupiter`       | 599 | Jupiter |
| `probes/saturn`        | 699 | Saturn |
| `probes/uranus`        | 799 | Uranus |
| `probes/neptune`       | 899 | Neptune |
| `probes/pluto`         | 999 | Pluto |

**`uncoverable` (method = 0)** — `payload_len = 0`. The consumer must hide
the probe through the sub-chunk's time window.

### Probe ID stability

`probe_id` is a synthetic int32 packing the spacecraft's inception MJD
(date of the start of its longest contiguous SPK coverage interval) plus a
per-day dedupe index:

```
probe_id = ((inception_mjd - 31412) << 12) | (dedupe & 0xFFF)
```

`31412` is the MJD of 1945-01-01. 20-bit date × 12-bit dedupe fits int32
and covers up to year ~4817 with 4096 distinct probes per inception day.

This synthetic ID exists because **NAIF integers are recycled** —
NAIF -76 was Mariner 10 in 1973 and is Mars Science Laboratory today;
NAIF -12 belongs to both LADEE and Pioneer Venus Multiprobe; NAIF -66
covers both InSight cruise and Vega-2 descent. The probe_id is pinned at
first ingest and cached at
`derived/position/tables/probe_ids.json` keyed by `(mission, naif_id)`,
so the value stays stable across DB rebuilds even when new earlier-coverage
kernels arrive.

## Object ID reconstruction

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

## Pre-interaction labels (`labels/{lang}.gz`)

One global file per language, listing only the *promoted* set — bodies that
get a label rendered on first paint without waiting for the user to interact:

- All planets, dwarf planets, moons, stars, barycenters, and Lagrange points
  (picked by `ObjectType`).
- A small curated list of spacecraft / satellites / asteroids / comets in
  [`constants/promoted.py`](../data/src/space_map_data/constants/promoted.py)
  (Voyager 1/2, ISS, Hubble, Apophis, Halley, …).

The frontend fetches one of these on app start (and on locale change) and uses
its keys as the authoritative promoted set — there's no separate frontend list.

Format: gzipped UTF-8, one `{id}\x1f{name}` line per object (`\x1f` = ASCII
Unit Separator). Name fallback per (object, lang): localized Wikidata label →
English Wikidata label → DB `name` → empty (the frontend then falls back to
the id).

Localized detail bundles for clicked objects are still fetched on demand (see
[Object detail files](#object-detail-files)) and are gated on the
`has_localized` bit in each binary file's row/body — when the bit is `0`, the
frontend skips the fetch entirely (avoiding a 404 round-trip for objects with
no Wikidata at all). There is no English-fallback tier: if the user's locale
has no localized bundle for an object, no localized data is shown.

## Object detail files

Object details are grouped into **hash-bucketed bundles** to keep the file
count manageable. The bundle count per tier (`N_global`, one `N_{lang}` per
language) is chosen at export time so average members-per-bundle stays near
target K (`K_global = 100`, `K_localized = 200`) regardless of DB size. The
resulting Ns are published in `metadata.json → object_bundles` so the
frontend can reconstruct URLs from an id alone — needed for deep links where
no element file has been loaded yet.

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
  parent_name?: string;               // host display name; moons only — lets the breadcrumb label the parent when its body isn't resident in the scene
  map_texture_available?: boolean;    // only present if true
  texture?: {                         // only when map_texture_available; mirrors systems/{bary}.json
    source: string;                   // source page URL
    organisation: string;             // short canonical label, deduplicable (e.g. "NASA", "USGS", "Björn Jónsson")
    type: string;                     // texture kind (cylindrical, cylindrical_monthly, cylindrical_tile, …)
    frames?: number;                  // only on cylindrical_monthly; frame count (1-based, files end in _01..frames)
    attribution?: string;             // long-form credit line; omitted when unavailable
    description?: string;
  };
  has_rings?: boolean;                // only present if true; full ring metadata (channels, geometry, attribution) lives in systems/{bary}.json
  clouds?: {                          // only when a cloud overlay was ingested for this body; mirrors systems/{bary}.json
    id: string;                       // export bundle id, e.g. "naif-399_clouds" — used to compose /v1/textures/{id}/{tier}_{frame}.webp
    tiers: string[];                  // sorted tier names (low | medium | high)
    frames: string[];                 // available snapshot ids (YYYYMMDDHH, sorted ascending); frontend picks the closest to simulation time
    source: string;
    organisation: string;
    type: string;                     // always "clouds_overlay" today
    attribution?: string;
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
  nut_prec?: {                        // SPICE PCK nutation/precession sums (paired with `nut_prec_angles` in /v1/systems/global.json)
    // α += Σ ra[i]  · sin(θ_i(T)),  δ += Σ dec[i] · cos(θ_i(T)),  W += Σ pm[i] · sin(θ_i(T))
    ra: number[]; dec: number[]; pm: number[];
  };
  radii?: {                           // SPICE PCK triaxial radii (km, body-fixed X/Y/Z)
    a: number; b: number; c: number;
  };
  gm?: number;                        // SPICE PCK gravitational parameter (km^3/s^2)
  orbit?: {
    epoch_jd: number; e: number; i: number;
    om: number; w: number;
    scale: "planet" | "system";
    /** Full parent `Object.id` (e.g. `"naif-399"`, `"spkid-2000004"`). */
    parent_id: string;
    source: "horizons" | "sbdb" | "celestrak" | "spice" | "sbdb_moons";
    // Keplerian (standard orbits):
    a?: number; ma?: number; n?: number;
    // Parabolic (e=1 comets):
    q?: number; tp?: number;
    // SGP4 init fields (CelesTrak-sourced earth sats only) — feed into
    // satellite.js `json2satrec` so URL-navigated sats can build a satrec
    // before their element file arrives.
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

  // Notable moons of this body, picked at export time, ordered by
  // (image_available, sitelinks_count, diameter desc, id). Present on the
  // planet/dwarf-planet (a planet's moons are gathered from its barycenter)
  // and on asteroids with satellites. Denormalized so the strip + moons list
  // render without per-moon fetches; per-language label overrides live in
  // LocalizedObjectData.notable_moon_names. Shares the NotableEntry shape
  // with GlobalGroupData.notable_members.
  notable_moons?: NotableEntry[];
  moon_count?: number;                // total moons of this body (drives the "+N more" tile); present iff notable_moons is
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
language. The binary `has_localized` column/byte tells the frontend whether
*any* language has data, gating the fetch attempt; on a 404 (locale has no
bundle for this object) the frontend gives up — there is no English fallback
tier.

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
  notable_moon_names?: Record<string, string>; // notable-moon Object.id → localized label, only where it differs from the global name
}

interface EntityRef { name: string; short_name?: string; wikipedia?: string; }
```

## Group detail files

Aggregation entities behind `/g/<slug>` pages (constellations, operators,
launch sites, manufacturers, countries, orbit classes, and small-body
flags). Group bundles use the **same hash-bucketing scheme as object
bundles** (sha256 first-4-bytes BE, mod N) so the frontend reuses
`hashBucket` for slug → bundle resolution.

Bucket counts ship in `metadata.json` under `group_bundles` as
`{ global: N, <lang>: N, ... }`. Target bundle sizes: `K_global = 1000`,
`K_localized = 600`. Source: `data/src/space_map_data/export/groups/`.

### `groups/__index__.json`

Small, **ungzipped** map written once. Loaded eagerly to validate
`/g/<slug>` URLs and render group listings without a bundle fetch:

```typescript
interface GroupIndexEntry {
  type: GroupType;            // "constellation" | "operator" | "launch_site" | "manufacturer" | "country" | "orbit_class" | "small_body_flag"
  applies_to: GroupCategory;  // "earth_sat" | "small_body"
  n: number;                  // member count
}
// File body: Record<slug, GroupIndexEntry>
```

### Global (`groups/__global__/{bucket}.json.gz`)

Written for every group. `bucket = sha256(slug)[:4] % N_global`. Each
bundle is a JSON object `{ "<slug>": GlobalGroupData, ... }`.

A `NotableEntry` is a denormalized record for the detail-page strip + list,
shared by group `notable_members` and object `notable_moons`:

```typescript
interface NotableEntry {
  name: string;                     // English Wikidata label (matching object bundles), or the DB fallback name
  id: string;                       // full Object.id; route /<type>/<id> (e.g. spkid-2000004, naif-502)
  diameter_km?: number;             // equivalent-sphere diameter (members) / mean PCK-radii diameter (moons)
  first_obs?: string;               // discovery proxy — YYYY-MM-DD or YYYY (members only; moons omit it)
  thumbnail?: { file: string; label: "s" | "m" | "xl"; ext: string }; // smallest emitted variant, same picker as search cards
}
```

```typescript
interface GlobalGroupData {
  slug: string;
  type: GroupType;
  applies_to: GroupCategory;
  member_count: number;
  wikidata_qid?: string;
  url?: string;                     // Fallback external URL when no Wikidata QID
  website?: string;                 // Wikidata P856
  categories?: SatelliteCategory[]; // Constellation-only; top-level use cases (communications, navigation, ...)

  // Earth-sat groups (constellation / operator / launch_site / manufacturer / country).
  // Computed from SATCAT; absent on small-body groups. Also present on the
  // Satellites category, summed over the primary shape classes (LEO/MEO/...).
  launch_histogram?: Record<string, number>;  // year string → count, sorted ascending
  first_launch_date?: string;                 // Earliest SATCAT launch_date among members (ISO date string)
  active_count?: number;                      // Members with ops_status operational/partial/extended and no decay
  decayed_count?: number;                     // Members with a SATCAT decay_date

  // Small-body groups (orbit_class / small_body_flag).
  // Computed from SBDB.first_obs (YYYY-MM-DD or partial YYYY).
  // Rows lacking a parseable year are excluded from the histogram but
  // still count in member_count. NEO/PHA flags overlap with the orbit
  // class an object belongs to, so the same row contributes to multiple
  // small-body histograms. Also present on the Asteroids and Comets
  // categories, summed over their constituent orbit classes (flags excluded).
  discovery_histogram?: Record<string, number>;  // year string → count, sorted ascending

  // Member with the largest SBDB.diameter; absent when no member has a
  // measured diameter. Present on orbit_class groups and on flag-neo/flag-pha.
  largest_body?: {
    name: string;        // SBDB full_name (fallback: name, pdes, spkid)
    diameter_km: number; // equivalent-sphere diameter
    primary_type: "spkid";
    primary_id: string;  // SBDB.spkid; route /o/spkid-<id>
  };

  // PHA member count for orbit_class groups; absent when 0 and on flag-pha
  // itself (self-link suppressed). NEO is intentionally not shipped — by
  // definition it's 100 % on IEO/ATE/APO/AMO and 0 % on every other class.
  pha?: { n: number; primary_type: "group"; primary_id: "flag-pha" };

  // Top 20 members picked at export time, ordered by
  // (image_available, sitelinks_count, diameter desc, H asc, spkid).
  // Present on orbit_class groups and flag-neo/flag-pha. Denormalized so
  // the strip + members list render without per-object bundle fetches.
  // Names are the English Wikidata label (matching object bundles), with
  // per-language overrides in LocalizedGroupData.notable_member_names.
  // Shares the NotableEntry shape with GlobalObjectData.notable_moons.
  notable_members?: NotableEntry[];

  inception?: string;               // Wikidata P571 — programme/operator inception (ISO date)
  dissolved?: string;               // Wikidata P576 — programme dissolution (ISO date)
  images?: ObjectImage[];           // Same pipeline / layout as GlobalObjectData.images
}
```

### `groups/__orbit_samples__.json.gz`

Shared sample set for the orbit-class scatter plot shown on small-body
group pages. Fetched once and cached. Population per orbit class is read
from `__index__.json` (the `n` field) — counts are not duplicated here.

Allocation is sqrt-weighted by class population with a per-class floor of
`5` (or the class's population, whichever is smaller). No upper cap, so
MBA naturally dominates the chart. Target total ≈ 1000; actual count
typically lands in the 1000–1100 range. Source:
`build_orbit_class_samples` in
`data/src/space_map_data/export/groups/small_body.py`.

```typescript
interface OrbitClassSample {
  slug: string;        // class-<OrbitClass.name>, e.g. "class-Main-belt"
  name: string;        // SBDB full_name → name → pdes fallback
  a: number | null;    // Semi-major axis [AU]; null for parabolic (e = 1) comets
  e: number;           // Eccentricity
  q: number;           // Perihelion distance [AU]
  i: number | null;    // Inclination to ecliptic [deg]
  neo: boolean;
  pha: boolean;
}
interface OrbitSamplesFile {
  samples: OrbitClassSample[];
}
```

### `groups/__sat_orbit_samples__.json.gz`

Earth-sat scatter samples. Same role as `__orbit_samples__.json.gz` but for
the 17-zone Earth orbit-class chart (`class-LEO` … `class-EQU`). Sampled
per shape class (one per sat: VLEO/LEO/MEO/HEO/GSO/GEO/IGSO/GRA/MOL/TUN/
GTO/CIS/VHEO, most specific wins) with sqrt-weighted allocation and a
per-class floor; total ≈ 1000. Each dot also carries its inclination band
(SSO/Polar/Retrograde/Equatorial, low orbits only) via `classes` so band
zones light up the same dots when focused. Source:
`build_earth_orbit_classes` in
`data/src/space_map_data/export/groups/earth_sat.py`.

Source data:
- Perigee/apogee (km altitude above Earth surface) from CelesTrak SATCAT
  (`satcat.perigee`, `satcat.apogee`).
- Inclination from the latest CelesTrak GP snapshot on disk
  (`gp-active.csv` + `groups/*.csv`); ~45 % of currently-active SATCAT
  rows have no GP entry and therefore no inclination — those park in the
  apogee/perigee-driven fallbacks (GSO/GTO/HEO instead of GEO/IGSO/MOL/
  TUN) and carry no inclination band. Space-Track ingest is planned to
  close that gap.
- Decayed sats (`decay_date` set) and non-Earth-centred orbits
  (`orbit_center != EARTH`) are excluded.

```typescript
interface EarthOrbitSample {
  slug: string;                  // Shape class slug, e.g. "class-LEO"
  name: string;                  // SATCAT OBJECT_NAME → Object.name fallback
  perigee_km: number;            // km above Earth surface
  apogee_km: number;             // km above Earth surface
  inclination_deg: number | null; // deg; null when no GP row
  classes: string[];             // Shape class + optional inclination band
}
interface EarthOrbitSamplesFile {
  samples: EarthOrbitSample[];
}
```

### Earth-sat orbit-class groups (`class-LEO`, `class-SSO`, …)

The 17 Earth orbit zones from
`data/src/space_map_data/constants/earth_sats/orbit_class.py` ship as
`GroupType.EARTH_ORBIT_CLASS` groups with bundles, membership entries in
`membership/earth.json.gz`, and bucket pages under `groups/__global__/`
and `groups/{lang}/` — the same shape as constellation/operator/etc.
groups. Per-class bundles carry `launch_histogram`, `first_launch_date`,
`active_count`, plus a localized `constellations` cross-link table
(no `launch_sites` breakdown). An object holds exactly one shape class plus at most
one inclination band (e.g. VLEO + SSO) — membership rules in
`classify_earth_orbit`.

### Localized (`groups/{lang}/{bucket}.json.gz`)

Per-language bundles. `bucket = sha256(slug)[:4] % N_{lang}` where
`N_{lang}` is that language's count in `metadata.group_bundles`. A group
appears in a language only when it has Wikidata/Wikipedia data for that
language. On a 404 the frontend gives up — there is no English fallback
tier.

```typescript
interface LocalizedGroupData {
  name?: string;
  description?: string;
  wikipedia?: { extract?: string; description?: string; url?: string };
  operators?: EntityRef[];            // Constellation operators (constants, not Wikidata P137)
  manufacturers?: EntityRef[];        // Constellation hardware primes
  country_of_origin?: EntityRef[];    // Omitted on country pages (would be self)
  instance_of?: EntityRef[];
  launch_sites?: { name: string; n: number; primary_type: "group"; primary_id: string }[];   // Top sites by member count
  constellations?: { name: string; n: number; primary_type: "group"; primary_id: string }[]; // Top constellations represented
  related_groups?: { name: string; primary_type: "group"; primary_id: string; role: GroupType }[]; // Sibling groups sharing the same QID across roles
  notable_member_names?: Record<string, string>; // notable-member Object.id → localized label, only where it differs from the global name
}
```

## IAU planetary nomenclature

Surface features (craters, maria, valles, …) live in two tiers so the marker
render path stays cheap.

### Marker tier (eager, per body)

Loaded when a body's surface comes into view. Two files per body that has any
feature:

- `nomenclature/positions/{body_id}.bin.gz` — **SMNF** binary
  (`feature_id` + center lat/lon + diameter + 2-letter IAU type code per
  record; see `data/src/space_map_data/export/nomenclature/format.py`).
- `nomenclature/__global__/{body_id}.json.gz` — gzipped JSON, keyed by
  string `feature_id`:

  ```typescript
  interface NomenclatureGlobalEntry {
    name: string;
    approval_date?: string;       // ISO date
    origin?: string;              // IAU "Named for ..." prose
    parent_feature_id?: number;   // IAU satellite-feature parent
  }
  ```

Features missing `object_id`, `center_lat`/`center_lon`, or `feature_type_code`
are dropped at build time (with a single aggregate log line per cause).

### Detail tier (lazy, hash-bucketed)

Fetched on drawer open. Bucket key is `{body_id}:{feature_id}` so features on
the same body cluster — opening one warms the bundle for its neighbours. Bucket
counts ship in `metadata.json → feature_bundles` so a frontend can recompute
the bucket from a URL.

- `nomenclature/details/__global__/{bucket}.json.gz` — global per-feature
  enrichment (image manifest with `kind: 'photo' | 'locator'`, Wikidata
  cross-link, physical-quantity claims):

  ```typescript
  interface FeatureGlobalData {
    wikidata_qid?: string;
    images?: ObjectImage[];        // P18 → 'photo', P242 → 'locator'
    wikidata?: {
      length?: QuantityWithUnit;
      width?: QuantityWithUnit;
      height?: QuantityWithUnit;
      area?: QuantityWithUnit;
      elevation?: QuantityWithUnit;
      vertical_depth?: QuantityWithUnit;
    };
  }
  ```

- `nomenclature/details/{lang}/{bucket}.json.gz` — per-language overlay; a
  feature appears here only when it has at least one localized field in that
  language.

  ```typescript
  interface FeatureLocalizedData {
    name?: string;                 // only when Wikidata's label differs
                                   // from the IAU canonical (`unicode_name`)
    description?: string;
    aliases?: string[];
    instance_of?: EntityRef[];     // resolved P31 refs
    named_after?: EntityRef[];     // resolved P138 refs
    location?: EntityRef[];        // resolved P276 refs
    located_on_physical_feature?: EntityRef;
    wikipedia?: { extract?: string; description?: string; url?: string };
  }
  ```

The IAU `parent_feature_id` graph (from the satellite-feature matching pass)
takes priority over Wikidata `P706` as the canonical "this feature sits on
that one" link — `P706` is much sparser (~1%) and is included as supplemental
metadata via `located_on_physical_feature` rather than as the authoritative
parent.

## Images

Sourced from Wikimedia Commons (Wikidata P18 image + P154 logo for objects; P18 image + P242 locator map for IAU nomenclature features) and Wikipedia pageimages across all supported languages. Downloaded during the `commons` download step; the export step generates per-image thumbnail bundles.

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
  schema: number;        // bumped when variant rules or payload fields change; stale bundles are regenerated
  source_url: string;    // Commons file page URL
  variants: { [label: string]: string };  // mirrors ObjectImage.variants
  width?: number;        // source pixel dimensions (omitted for SVG/WebM passthrough)
  height?: number;
  license?: { name?: string; url?: string };       // from Commons extmetadata
  artist?: string | { [lang: string]: string };    // multilang or bare string
  description?: string | { [lang: string]: string };
  date?: string;         // ISO-truncated creation date: "YYYY-MM-DD" | "YYYY-MM" | "YYYY"
  depicts?: string[];    // Wikidata QIDs from Commons SDC P180 ("depicts")
}
```

`artist` and `description` are aggregated across the chosen image's derivative tree (chosen-file values win; tree members reachable via Commons `{{derived from}}` / `{{Other versions}}` fill in missing entries — per-locale for multilang dicts). `date` and `depicts` are also tree-aware but use whole-value fallback: the chosen file wins outright if it has any value, otherwise the closest tree member with one supplies it. `date` prefers the structured SDC P571 inception (truncated to its declared precision) and falls back to free-form `DateTimeOriginal`.

Not cleaned on re-export — bundles are reused across runs. Schema mismatches trigger per-image regeneration; to force a full rebuild, wipe `v1/images/`.

## Textures

Generated during ingest (not export) and written directly to the export directory. An object's `map_texture_available` flag in its global JSON signals whether a texture exists.

**Path:** `textures/{id}/{tier}.webp` (single-frame, default) or `textures/{id}/{tier}_{NN}.webp` (monthly).

| Tier   | Max dimension | Size target | Quality                              | Condition        |
|--------|---------------|-------------|--------------------------------------|------------------|
| low    | 2048 px       | 300 KiB     | lossy 80                             | always generated |
| medium | 8192 px       | 2 MiB       | lossy 80                             | source > 2048 px |
| high   | 16383 px      | 6 MiB       | lossy 80 or lossless if small enough | source > 8192 px |

16,383 px is the WebP hard limit per dimension.

The size is a target, not a hard limit. Some textures go over it.

### Texture type

The `type` field in the metadata (and mirrored to `systems/{bary}.json` / `credits.json`) discriminates how the renderer should consume the export bundle:

- **`cylindrical`** — single equirectangular frame; one `{tier}.webp` per tier.
- **`cylindrical_monthly`** — twelve-frame seasonal cycle. Files are suffixed with the 1-based month (`{tier}_{NN}.webp`, `NN` = `01`..`frames`); the metadata's `exports` map is nested `{frame: {tier: rec}}`. Earth ships under this type; the renderer picks the frame by calendar month of the simulation date.
- **`clouds_overlay`** — multi-frame cloud-cover overlay, ingested as a separate bundle from the surface texture and refreshed from a real-time source (Earth's case: EUMETSAT-derived snapshot, 3h cadence). Every snapshot the downloader has on disk is exported; files carry a sortable `YYYYMMDDHH` frame suffix (`{tier}_{frame}.webp`). The bundle lives at `textures/{host_id}_clouds/` so it can be served and credited independently; the renderer composites it on top of the surface texture and picks a frame by simulation time. The `_clouds` directory-name suffix is the export-tree convention — in the systems/credits/object payloads the bundle is exposed under its own `clouds` key on the host body (`naif-399`), keyed by host id rather than the suffixed export id.
- **`cylindrical_specular`** — single-frame specular/roughness mask for the host body, derived from a bathymetry or land/water source (Earth's case: GEBCO bathymetry → binary ocean mask, land=0 / ocean=255). Ships as a sibling bundle at `textures/{host_id}_specular/{tier}.webp` so it can be served and credited independently from the surface texture; the renderer routes it into whichever material slot (roughness, specular intensity) it sees fit. In the systems payload it surfaces as a `specular` key on the host body, keyed by host id.

### Texture metadata (`textures/{id}/metadata.json`)

Single-frame (`type: cylindrical`):

```json
{
  "id": "naif-499",
  "source": "https://example.com/mars.tif",
  "organisation": "NASA",
  "attribution": "NASA/JPL-Caltech/MSSS. …",
  "description": "Mars surface map",
  "type": "cylindrical",
  "source_file": "mars_color.tif",
  "source_dimensions": [8192, 4096],
  "processed_at": "2025-01-01T00:00:00+00:00",
  "exports": {
    "low":    { "file": "low.webp",    "width": 2048, "height": 1024, "size_bytes": 290000, "lossless": false },
    "medium": { "file": "medium.webp", "width": 8192, "height": 4096, "size_bytes": 1800000, "lossless": false }
  }
}
```

Monthly (`type: cylindrical_monthly`):

```json
{
  "id": "naif-399",
  "source": "https://science.nasa.gov/earth/earth-observatory/blue-marble-next-generation/",
  "organisation": "NASA",
  "attribution": "NASA Earth Observatory — Blue Marble: Next Generation monthly composites (2004).",
  "type": "cylindrical_monthly",
  "frames": 12,
  "source_file": "world.2004{month:02d}.3x21600x10800_geo.tif",
  "source_dimensions": [21600, 10800],
  "processed_at": "2026-05-11T00:00:00+00:00",
  "exports": {
    "01": {
      "low":    { "file": "low_01.webp",    "width": 2048,  "height": 1024, "size_bytes": 134000, "lossless": false },
      "medium": { "file": "medium_01.webp", "width": 8192,  "height": 4096, "size_bytes": 1550000, "lossless": false },
      "high":   { "file": "high_01.webp",   "width": 16383, "height": 8191, "size_bytes": 5300000, "lossless": false }
    },
    "02": { "...": "..." }
  }
}
```

- `source` — the page URL the texture was obtained from.
- `organisation` — short canonical label used for deduplicated UI attribution (e.g. `"NASA"`, `"USGS"`, `"ESA/DLR/FU Berlin"`, `"The Planetary Society"`, `"Björn Jónsson"`).
- `attribution` — optional long-form credit string. Populated from `download-metadata.yaml` where provided; for NASA/USGS-hosted textures this is expected to be auto-filled from the source page at ingest time. Omitted entirely when unavailable.
- `frames` — only on `cylindrical_monthly`; the number of monthly composites (always 12 today). Mirrored into the `systems/{bary}.json` texture block.

Cloud overlay (`type: clouds_overlay`): one bundle per host body covering every snapshot the downloader has on disk. The `id` carries the `_clouds` suffix and the frontend composes URLs as `/v1/textures/{clouds.id}/{tier}_{frame}.webp`. Per-frame `size_bytes` / `source_file` / `exports` records are intentionally omitted — the snapshot count grows over time (one per ~3 h) and the tier set is identical across frames, so a flat `tiers` + `frames` pair is the useful summary.

```json
{
  "id": "naif-399_clouds",
  "source": "https://clouds.matteason.co.uk/images/8192x4096/clouds-alpha.png",
  "organisation": "EUMETSAT",
  "attribution": "Contains modified EUMETSAT data",
  "description": "Near-real-time cloud-cover overlay (3-hour cadence).",
  "type": "clouds_overlay",
  "tiers": ["low", "medium"],
  "frames": ["2026050100", "2026050103", "2026050106", "..."],
  "processed_at": "2026-05-11T00:00:00+00:00"
}
```

Specular (`type: cylindrical_specular`): single-frame mask sibling to the surface texture. The `id` carries the `_specular` suffix and the frontend composes URLs as `/v1/textures/{specular.id}/{tier}.webp`. Layout matches the single-frame `cylindrical` shape; only the directory naming and the `specular` key in the systems payload distinguish it.

```json
{
  "id": "naif-399_specular",
  "source": "https://science.nasa.gov/earth/earth-observatory/blue-marble-next-generation/topography-bathymetry-maps/",
  "organisation": "NASA",
  "attribution": "NASA Earth Observatory — Blue Marble: Next Generation topography/bathymetry maps. Bathymetry derived from GEBCO.",
  "description": "Ocean specular mask derived from GEBCO bathymetry — bright over water, matte over land.",
  "type": "cylindrical_specular",
  "source_file": "gebco_08_rev_bath_21600x10800.tif",
  "source_dimensions": [21600, 10800],
  "processed_at": "2026-05-12T00:00:00+00:00",
  "exports": {
    "low":    { "file": "low.webp",    "width": 2048,  "height": 1024, "size_bytes": 10000,  "lossless": false },
    "medium": { "file": "medium.webp", "width": 8192,  "height": 4096, "size_bytes": 80000,  "lossless": false },
    "high":   { "file": "high.webp",   "width": 16383, "height": 8191, "size_bytes": 250000, "lossless": false }
  }
}
```

## Rings

Generated during ingest (not export) and written directly to the export directory. Each ringed body's `has_rings` flag in its global JSON signals that a ring bundle exists; the per-system metadata (below) carries the renderer-facing block with channel URLs and geometry constants.

**Path:** `rings/{id}/{channel}.webp`

Each channel is a 1-D radial profile rendered as a 1×N lossless WebP image. Channels are sampled uniformly between `inner_radius_km` and `outer_radius_km`; `sample_count` (= image width) is fixed per source dataset. Pillow promotes single-channel inputs to RGB on save, so consumers should sample `.r` for scalar channels and `.rgb` for `color`.

| Channel            | Type   | Meaning                                                      |
|--------------------|--------|--------------------------------------------------------------|
| `backscattered`    | scalar | Brightness on the sun-lit side (phase angle ≈ 0°).            |
| `forwardscattered` | scalar | Brightness at high phase (≈ 139°).                            |
| `unlitside`        | scalar | Brightness on the un-lit side (back-lit transmission).        |
| `transparency`     | scalar | Per-radius opacity (1 = transparent, 0 = opaque).             |
| `color`            | RGB    | Color tint (multiplied with the brightness channel).          |

The renderer blends `backscattered`/`forwardscattered` by phase angle, swaps in `unlitside` when the sun-side ray to a fragment is occluded by the host body, multiplies by `color`, and uses `transparency` for the alpha component (and for the host body's surface shader, which samples the same channel along the sun ray to project a ring shadow onto the planet).

### Ring metadata (`rings/{id}/metadata.json`)

```json
{
  "id": "naif-699",
  "source": "https://bjj.mmedia.is/data/s_rings/index.html",
  "organisation": "Björn Jónsson",
  "attribution": "Saturn ring profiles created by Björn Jónsson …",
  "description": "1-D radial profiles of Saturn's main rings: …",
  "inner_radius_km": 74510.0,
  "outer_radius_km": 140390.0,
  "sample_count": 13177,
  "color_space": "srgb",
  "processed_at": "2026-05-10T16:31:15+00:00",
  "channels": {
    "backscattered":   { "file": "backscattered.webp",   "width": 13177, "height": 1, "size_bytes": 2588 },
    "forwardscattered":{ "file": "forwardscattered.webp","width": 13177, "height": 1, "size_bytes": 1850 },
    "unlitside":       { "file": "unlitside.webp",       "width": 13177, "height": 1, "size_bytes": 2616 },
    "transparency":    { "file": "transparency.webp",    "width": 13177, "height": 1, "size_bytes": 8788 },
    "color":           { "file": "color.webp",           "width": 13177, "height": 1, "size_bytes": 2508 }
  }
}
```

- `inner_radius_km` / `outer_radius_km` — radial domain (km from the host body's centre) the profile spans. Samples are uniformly distributed across the closed interval.
- `color_space` — color space for the `color` channel; `"srgb"` today.
- `attribution` / `description` — optional; when present they propagate to `systems/{bary}.json` and `credits.json`.

## Models

3D meshes of spacecraft and satellites, sourced from the NASA-3D-Resources repo and ESA SciFleet. Generated by the `models` ingest provider from the YAML manifests under `sources/models/` and written directly to the export directory. Bundles are keyed by a human-readable `slug` (the model's name on disk), and each Object row whose mission is depicted by that model carries the slug in its `model_name` field. Many objects may share one slug (Viking 1/2 orbiter, Cluster II constellation).

**Path:** `models/{slug}/{tier}.glb`

Two tiers — `low` and `high` — both as glTF 2.0 binary (.glb). Optimised by [`@gltf-transform/cli optimize`](https://gltf-transform.dev/cli): geometry is Meshopt-compressed (faster decode than Draco, supports morph targets) and textures are re-encoded as WebP. When a manifest entry ships ≥ 2 hand-authored variants the smallest convertible one becomes `low` (if it's ≤ 50% the high tier's size); otherwise `low` is synthesised from `high` by downsampling textures to 1024 px and simplifying geometry to 50% of the original triangle count.

Source formats: pre-existing `.glb` is passed through; `.fbx`, `.blend`, `.obj`, `.3ds` are converted via Blender headless first. `.lwo` and `.7z` are skipped today.

Slugs are globally unique across catalogs — a duplicate slug raises `SlugConflictError` at ingest time. A single mission may have multiple candidate slugs (e.g. "cassini" and "cassini-with-huygens" both depict the Cassini probe); in that case the first slug encountered wins and a warning is logged. TODO: explicit per-mission canonical selection once the frontend's variant-picking rule is known.

### Model metadata (`models/{slug}/metadata.json`)

Shipped publicly (lives in `EXPORT_DIR`, not the build-only mirror) so clients can introspect a model's source catalog, mission list, and per-tier glTF stats without parsing the GLB header.

```json
{
  "slug": "curiosity-rover-msl",
  "schema": 4,
  "kind": "lander",
  "missions": [
    { "object_id": "probe-100265984", "name": "Curiosity (MSL)" }
  ],
  "tiers": ["high", "low"],
  "exports": {
    "high": {
      "size_bytes": 1057528,
      "sha256": "abc123…",
      "source_type": "glb",
      "credit": {
        "name": "NASA",
        "url": "https://science.nasa.gov/resource/curiosity-rover-3d-model/"
      },
      "stats": { "triangles": 51305, "meshes": 1, "nodes": 1, "textures": 7, "animations": 0 }
    },
    "low": {
      "size_bytes": 648820,
      "sha256": "def456…",
      "source_type": "blend",
      "credit": {
        "name": "NASA",
        "url": "https://www.nasa.gov/3d-resources/"
      },
      "catalog": "NASA-3D-Resources",
      "downloaded_at": "2025-06-03T09:00:30-07:00",
      "stats": { "triangles": 50228, "meshes": 6, "nodes": 6, "textures": 2, "animations": 0 }
    }
  },
  "processed_at": "2026-06-04T12:37:45+00:00"
}
```

- `kind` — coarse category from the manifest (`probe`, `earth_sat`, `station`, `lander`, `rocket`, `asteroid`, `astronomical_object`, `ground_infrastructure`, `equipment`, `instrument`, `subassembly`, `aircraft`, `submersible`, `robot`, `generic_sat`, `concept`). Lets the frontend filter the model browser without re-deriving from mission data.
- `missions` — every Object whose `model_name` points at this slug; `name` is whatever the manifest entry supplied. Mission resolution priority: `probe_id` → `naif_id` → `norad_cat_id` → `spkid` (the last for asteroids).
- `exports.{tier}.source_type` — the original file format the tier was converted from (`"glb"`, `"fbx"`, `"blend"`, `"obj"`, `"3ds"`). `"glb"` means pass-through, anything else means a Blender import happened.
- `exports.{tier}.credit` — the display text and link target for the attribution bar/popover. `name` is always the attribution (`"NASA"`, `"ESA / scifleet.esa.int"`, `"NASA (via Google Arts & Culture)"`, …) so chips stay consistent across catalogs. `url` is the specific resource page when one was given inline in the manifest, else the catalog's landing page.
- `exports.{tier}.catalog` — present only when the file came from a key in `MODEL_CATALOGS` (`"NASA-3D-Resources"`, `"ESA SciFleet"`). The credits page uses the union across all tiers to pick which primary catalogs to surface; one-off resources (NASA Science pages, Google rehosts) omit this and credit through `credit.name` alone.
- `exports.{tier}.downloaded_at` — when the source bytes were last fetched, when known. ESA's downloader stamps this when it writes the per-root `metadata.yaml`; NASA falls back to the git HEAD commit time of the `NASA-3D-Resources` checkout.
- `exports.{tier}.stats` — content stats parsed from the .glb's JSON chunk: `triangles` counts only primitives with mode 4 (TRIANGLES); the rest are top-level array lengths. A handy LOD-impact sanity check (high vs low triangle counts) and a cheap "deployable parts?" hint via `animations > 0`.
- Real-world scale (metres) is **not** persisted today — source models use arbitrary authoring units and there's no reliable auto-conversion. A future iteration will add an optional `scale_meters` override in the YAML manifest for frontends that need to size the mesh against scene units.

## Systems global (`systems/global.json`)

A single tiny top-level file fetched once at app start, paired with the per-system files below. Holds context-independent lookups the frontend needs regardless of which system the user is viewing.

```json
{
  "gm": {
    "0": 1.32712440041e11,
    "10": 1.32712440041e11,
    "3": 4.0350323562548e5,
    "399": 3.98600435507e5,
    "5": 1.267127641e8
  },
  "nut_prec_angles": {
    "1": [174.791086, 4.092335, 349.582171, 8.184670],
    "3": [125.045, -0.0529921, 250.089, -0.1059842],
    "5": [73.32, 91472.9, 24.62, 45137.2]
  }
}
```

- **`gm`** — gravitational parameters (km³/s²) per body NAIF id, sourced from SPICE PCK (`gm_de440.tpc`). Includes a synthesized SSB row (`"0"`) reusing the Sun's GM so chebyshev-only bodies that orbit SSB resolve correctly. Used by the chebyshev trail-buffer sizing path to estimate orbital periods via Kepler's third law (`n = √(GM/a³)`) for any parent NAIF id.
- **`nut_prec_angles`** — IAU nutation/precession angle pairs `(θ₀, θ₁)` per "owner" body — typically the planetary system barycenter. Bodies derive their owner as `naif_id // 100` if `naif_id ≥ 100`, else `naif_id`. Each owner's array is a flat `[θ₀_1, θ₁_1, θ₀_2, θ₁_2, …]` in degrees and degrees/century. Combined with each body's `nut_prec` coefficient arrays:

  ```
  θ_i(T) = angles[2i] + angles[2i+1]·T          (T = Julian centuries since J2000)
  α(T)  += Σ nut_prec.ra[i]  · sin(θ_i(T))
  δ(T)  += Σ nut_prec.dec[i] · cos(θ_i(T))
  W(d)  += Σ nut_prec.pm[i]  · sin(θ_i(T))
  ```

## System metadata (`systems/{barycenter_id}.json`)

Generated during export (not ingest). One file per planetary system, keyed by barycenter ID (e.g. `naif-3` for Earth-Moon, `naif-5` for Jupiter). Per-body entries carry available texture tiers, texture attribution, SPICE PCK orientation (pole/spin polynomial), nutation/precession coefficients, and triaxial radii when known.

```json
{
  "naif-399": {
    "tiers": ["high", "low", "medium"],
    "texture": {
      "source": "https://science.nasa.gov/earth/earth-observatory/blue-marble-next-generation/",
      "organisation": "NASA",
      "type": "cylindrical_monthly",
      "frames": 12
    },
    "clouds": {
      "id": "naif-399_clouds",
      "tiers": ["low", "medium"],
      "frames": ["2026050100", "2026050103", "..."],
      "source": "https://clouds.matteason.co.uk/images/8192x4096/clouds-alpha.png",
      "organisation": "EUMETSAT",
      "type": "clouds_overlay",
      "attribution": "Contains modified EUMETSAT data"
    },
    "specular": {
      "id": "naif-399_specular",
      "tiers": ["low", "medium", "high"],
      "source": "https://science.nasa.gov/earth/earth-observatory/blue-marble-next-generation/topography-bathymetry-maps/",
      "organisation": "NASA",
      "type": "cylindrical_specular",
      "attribution": "NASA Earth Observatory — Blue Marble: Next Generation topography/bathymetry maps. Bathymetry derived from GEBCO."
    },
    "orientation": {
      "pole_ra_0": 0.0, "pole_ra_1": -0.641,
      "pole_dec_0": 90.0, "pole_dec_1": -0.557,
      "w0": 190.147, "w1": 360.9856235, "w2": 0.0
    },
    "nut_prec": { "ra": [], "dec": [], "pm": [] },
    "radii": { "a": 6378.1366, "b": 6378.1366, "c": 6356.7519 }
  },
  "naif-301": { "tiers": ["low"], "texture": { "source": "…", "organisation": "NASA", "type": "cylindrical" } },
  "naif-699": {
    "rings": {
      "source": "https://bjj.mmedia.is/data/s_rings/index.html",
      "organisation": "Björn Jónsson",
      "attribution": "Saturn ring profiles created by Björn Jónsson …",
      "inner_radius_km": 74510.0,
      "outer_radius_km": 140390.0,
      "sample_count": 13177,
      "color_space": "srgb",
      "channels": {
        "backscattered":    "backscattered.webp",
        "forwardscattered": "forwardscattered.webp",
        "unlitside":        "unlitside.webp",
        "transparency":     "transparency.webp",
        "color":            "color.webp"
      }
    }
  }
}
```

The frontend fetches this when entering a system: it preloads low-res textures for every listed body, applies the full IAU rotation polynomial + nutation sums to meshes, (where `radii` differ) flattens bodies into oblate ellipsoids, and shows per-organisation imagery attribution for bodies currently in view. `texture` mirrors the shape embedded in each body's global detail file.

When a body carries a `rings` block, the frontend builds an annulus aligned to its IAU pole, fetches `${DATA_BASE}/v1/rings/{body_id}/{channels[name]}` for each channel, and routes the credit fields through the same per-organisation attribution path as textures. The `channels` map is flat (channel → filename) rather than tier-nested because rings ship at a single resolution.

## Credits (`credits.json`)

Aggregated attribution manifest read by the standalone `/credits` page. A
single non-gzipped JSON file so the page can render everything in one fetch
without walking per-system or per-body files.

```typescript
interface Credits {
  systems: Array<{
    id: string | null;           // barycenter object ID ("naif-3", …) or null for the standalone bucket
    name: string | null;         // primary-planet name ("Earth", "Jupiter", …); null for standalones
    textures?: Array<{
      body_id: string;           // e.g. "naif-399"
      name: string;              // English display name; localisation is deferred
      source: string;            // attribution source URL
      organisation: string;      // short label, deduplicable (e.g. "NASA", "USGS")
      type: string;              // cylindrical / cylindrical_monthly / cylindrical_tile / …
      frames?: number;           // only on cylindrical_monthly; frame count
      attribution?: string;      // long-form credit line when available
      description?: string;      // optional one-liner about the dataset
    }>;
    rings?: Array<{
      body_id: string;           // real Object.id of the ringed host (e.g. "naif-699"); the array name is the disambiguator, not a synthetic "-rings" suffix
      name: string;              // English display name of the host body
      source: string;
      organisation: string;
      attribution?: string;
      description?: string;
    }>;
    clouds?: Array<{
      body_id: string;           // host body id (e.g. "naif-399"), NOT the "_clouds"-suffixed export id; same disambiguation as rings
      name: string;              // English display name of the host body
      source: string;
      organisation: string;
      attribution?: string;
      description?: string;
    }>;
  }>;
  models?: Array<{               // 3D-model source catalogs (one entry per catalog with ≥ 1 bundle)
    name: string;                // "NASA-3D-Resources", "ESA SciFleet"
    url: string;                 // user-facing catalog landing page
  }>;
  skybox?: {                     // whole-sky cubemap backdrop — single global asset, no host body
    source: string;
    organisation: string;
    attribution?: string;
    description?: string;
  };
}
```

Systems are ordered Mercury → Pluto by barycenter NAIF ID; a final `id: null`
bucket collects standalones (sun-orbiting dwarf planets or asteroids such as
Ceres and Bennu). Each system's `textures` and `rings` lists are alphabetised
by body name; either array is omitted entirely when no entries exist for
that bucket. Only bodies whose `metadata.json` exists on disk (under
`textures/` or `rings/`) are included. Static credits (orbital providers,
SPICE/IAU rotation kernels, Wikidata, Wikipedia, Wikimedia Commons, IAU
nomenclature) live in the frontend page itself and don't need to be emitted
here. The top-level `skybox` block is emitted whenever a cubemap-skybox bundle
exists under `textures/stars/` and mirrors the credit fields from its metadata.

The top-level `models` array credits each 3D-model source catalog (NASA-3D-Resources,
ESA SciFleet, …) with one entry per catalog whose attribution matched at least
one model bundle under `models/{slug}/`. The catalog license is what matters, not
per-body attribution, so no item list is emitted. Models whose `attribution`
doesn't match a known catalog log a warning during export so the catalog list
stays maintained.

## Consuming the data

1. Fetch `metadata.json` to discover available zones and shapes.
2. Fetch `labels/{lang}.gz` once on app start (and on locale change) to get
   the pre-interaction label set: split by newline, parse `{id}\x1f{name}`
   per line, build a `Map<id, name>`. The keys *are* the promoted set —
   there's no separate frontend list.
3. For each (zone, zoom), dispatch on `shape`:
   - `parted` → fetch `position/{zone}/{zoom}/{part}.bin.gz`
   - `chunked-parted` → pick a label (date for `earth`, chunk index for
     `moons`) then fetch `position/{zone}/{zoom}/{label}/{part}.bin.gz`
   - `chunked` (chebyshev) → compute the chunk index from JD and fetch
     `position/{zone}/{zoom}/{chunk}.bin.gz`
4. Parse the file: read the common header, dispatch on the format byte at
   offset 6 to either the elements columnar reader or the chebyshev per-body
   reader. Rebuild full IDs from the id-type byte (elements) or the per-body
   `id_type` (chebyshev).
5. For elements rows, propagate at the target date with Kepler's equation
   (or Barker's for parabolic, or `json2satrec` + SGP4 for SGP4). For
   chebyshev bodies, evaluate the segment covering the target JD via
   Clenshaw's recursion to get a parent-relative position in km, then walk
   up the parent chain to your reference frame.
6. Read `has_localized` (last column on elements, byte 19 of the chebyshev
   per-body header) to gate localized object-detail fetches. Always fetch
   `objects/__global__/{bucket}.json.gz` where
   `bucket = sha256(id)[:4] % N_global`; only fetch
   `objects/{lang}/{bucket}.json.gz` when `has_localized` is `1`. On a 404,
   give up — there's no English fallback tier.
