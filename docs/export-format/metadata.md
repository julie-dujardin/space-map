# metadata.json

Entry point. Each `position.zones[zone]` entry carries a `shape`
discriminator that tells the URL builder which path template to use.
Multi-zoom zones (`major`, `small_bodies/{class}`) nest their shapes under a
`zooms` map and gain a `{zoom}` path segment; all other zones carry the shape
fields directly at zone level and are flat (no `{zoom}` segment):

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
        "shape": "parted",
        "parts": 1,
        "parent_id_type": "spkid"
      },
      "earth": {
        "shape": "chunked-parted",
        "label": "date",
        "start_date": "2024-01-01",
        "end_date": "2026-04-26",
        "parts": 3,
        "parts_by_date": { "2024-01-01": 3, "2026-04-26": 2 }
      },
      "moons": {
        "shape": "chunked-parted",
        "label": "index",
        "chunks": 200,
        "chunk_years": 0.5,
        "start_jd": 2433282.5,
        "parts": 1
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
        "shape": "chunked",
        "chunks": 200,
        "chunk_years": 0.5,
        "start_jd": 2433282.5,
        "end_jd": 2469807.5
      },
      "probes/interplanetary": {
        "shape": "probes",
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
  "versions": {
    "position": "a1b2c3d4e5f60718", "objects": "…", "nomenclature": "…",
    "textures": "…", "rings": "…", "models": "…", "images": "…", "membership": "…"
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

## Caching & versioning

`versions` maps a content class to a 16-hex content-hash token (sha256 over
each file's path + bytes under that class dir, `0` for an absent dir). The
frontend appends it as `?v={token}` on every URL it builds for that class, so
a content change produces a fresh URL and an unchanged class keeps its cached
copy. Because the tokens are content hashes, a deterministic re-export with no
data change leaves them — and the client's cache — untouched. Nondeterministic
contents only churn the token (weaker caching), never correctness.

The eight versioned classes — `position`, `objects`, `nomenclature`,
`textures`, `rings`, `models`, `images`, `membership` — are served under an
immutable `Cache-Control` rule (`infrastructure/deploy/_headers`). The
remaining roots (`metadata.json`, `credits.json`, `labels/`, `systems/`,
`groups/`, `attitude/`) carry no token and fall through to Cloudflare Pages'
revalidating default; `metadata.json` is the single always-fresh entry point that pins
every other URL. `_headers` rules must stay non-overlapping: Pages joins a
header set by multiple matching rules with a comma, so a revalidating file
must never also match an immutable glob.

## Shape → URL

The `{zoom}` segment below is present **only** for the multi-zoom zones
(`major`, `small_bodies/{class}`) — the ones whose manifest entry has a
`zooms` wrapper. Flat zones omit it.

| `shape`           | URL                                              | Used by                              |
|-------------------|--------------------------------------------------|--------------------------------------|
| `parted`          | `position/{zone}/[{zoom}/]{part}.bin.gz`         | `small_bodies/{class}` zones (zoomed), Earth-orbit spacecraft, `small_body_moons`, major/1 (horizons-sourced dwarves), major/2 (SBDB dwarves) |
| `chunked-parted`  | `position/{zone}/[{zoom}/]{label}/{part}.bin.gz` | `earth` (label = ISO date), `moons` (label = chunk index) — both flat |
| `chunked`         | `position/{zone}/[{zoom}/]{chunk}.bin.gz`        | every chebyshev zone; only `major` is zoomed, the flat cheby zones (`major_asteroids`, `moons/{parent}`) omit the segment |
| `probes`          | `position/{zone}/{chunk}.bin.gz`                 | probe zones (`probes/*`) — always flat; a distinct tag from flat `chunked` cheby zones |

`chunked-parted` carries an extra `label` discriminator: `"date"` for ISO
dates (`earth`), `"index"` for numeric chunk indices (`moons` Method-C secular
elements). Clients dispatch on `label` to format the path segment.

For the date-segmented `earth` zone the available snapshot dates are sparse and
irregular — recent CelesTrak dailies plus historical Space-Track weekly
snapshots — so part counts vary per date (historical weeks carry the full
decayed catalog; recent dailies fewer). The entry therefore ships
`parts_by_date` (a `{date: parts}` map whose **keys are exactly the exported
snapshots**, doubling as the date index) alongside `start_date`/`end_date`;
`parts` is the max as a convenience bound. Clients snap a sim time to the
nearest key and load that date's part count. The `"index"` (moons) variant
keeps a single uniform `parts`.

The `chunked` shape carries `chunks` and `chunk_years`; clients compute
`chunk_idx = floor((jd - start_jd) / (chunk_years * 365.25))`. There's no
parts axis on chebyshev — files are tuned to ~200 KB by adjusting
`chunk_years` per zone.

Probe zones carry the distinct `probes` shape (so they're told apart from the
flat `chunked` cheby zones, which also sit at zone level). Like every flat
zone the entry has no `zooms` wrapper and the URL omits the zoom segment:
`position/probes/interplanetary/47.bin.gz`. The chunk layout matches `chunked`
otherwise. Probes never need multi-resolution tiers — per-zone routing already
picks the right detail level.

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
