# Textures

Generated during ingest (not export) and written directly to the export directory. An object's `map_texture_available` flag in its global JSON signals whether a texture exists.

**Path:** `textures/{id}/{tier}.webp` (single-frame, default) or `textures/{id}/{tier}_{NN}.webp` (monthly).

| Tier   | Max dimension | Size target | Quality                              | Condition        |
|--------|---------------|-------------|--------------------------------------|------------------|
| low    | 2048 px       | 300 KiB     | lossy 80                             | always generated |
| medium | 8192 px       | 2 MiB       | lossy 80                             | source > 2048 px |
| high   | 16383 px      | 6 MiB       | lossy 80 or lossless if small enough | source > 8192 px |

16,383 px is the WebP hard limit per dimension.

The size is a target, not a hard limit. Some textures go over it.

## Texture type

The `type` field in the metadata (and mirrored to `systems/{bary}.json` / `credits.json`) discriminates how the renderer should consume the export bundle:

- **`cylindrical`** — single equirectangular frame; one `{tier}.webp` per tier.
- **`cylindrical_monthly`** — twelve-frame seasonal cycle. Files are suffixed with the 1-based month (`{tier}_{NN}.webp`, `NN` = `01`..`frames`); the metadata's `exports` map is nested `{frame: {tier: rec}}`. Earth ships under this type; the renderer picks the frame by calendar month of the simulation date.
- **`clouds_overlay`** — multi-frame cloud-cover overlay, ingested as a separate bundle from the surface texture and refreshed from a real-time source (Earth's case: EUMETSAT-derived snapshot, 3h cadence). Every snapshot the downloader has on disk is exported; files carry a sortable `YYYYMMDDHH` frame suffix (`{tier}_{frame}.webp`). The bundle lives at `textures/{host_id}_clouds/` so it can be served and credited independently; the renderer composites it on top of the surface texture and picks a frame by simulation time. The `_clouds` directory-name suffix is the export-tree convention — in the systems/credits/object payloads the bundle is exposed under its own `clouds` key on the host body (`naif-399`), keyed by host id rather than the suffixed export id.
- **`cylindrical_specular`** — single-frame specular/roughness mask for the host body, derived from a bathymetry or land/water source (Earth's case: GEBCO bathymetry → binary ocean mask, land=0 / ocean=255). Ships as a sibling bundle at `textures/{host_id}_specular/{tier}.webp` so it can be served and credited independently from the surface texture; the renderer routes it into whichever material slot (roughness, specular intensity) it sees fit. In the systems payload it surfaces as a `specular` key on the host body, keyed by host id.
- **`cylindrical_displacement`** — single-frame height map for the host body, derived from a topography source (the Moon's case: LRO LOLA, signed half-metres relative to a 1737.4 km reference sphere). The source elevation is stretched to an 8-bit grayscale tile; the km that pixel 0 and 255 reconstruct to are recorded as `displacement_bias_km` / `displacement_scale_km` so the renderer can drive `material.displacementMap` at true physical scale. Ships as a sibling bundle at `textures/{host_id}_displacement/{tier}.webp`, exposed under a `displacement` key on the host body, keyed by host id.

## Texture metadata (`textures/{id}/metadata.json`)

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
- `attribution` — optional long-form credit string. Populated from the texture manifests in `data/src/space_map_data/constants/manifests/textures/` where provided; for NASA/USGS-hosted textures this is expected to be auto-filled from the source page at ingest time. Omitted entirely when unavailable.
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

Displacement (`type: cylindrical_displacement`): single-frame height map sibling to the surface texture. The `id` carries the `_displacement` suffix and the frontend composes URLs as `/v1/textures/{displacement.id}/{tier}.webp`. Beyond the single-frame `cylindrical` shape it adds `displacement_bias_km` / `displacement_scale_km`, the km that texel 0 and 1 reconstruct to (`km = bias + scale · texel`), so the renderer scales `material.displacementMap` to true relief. `absolute_radius` marks grids whose value is radius-from-centre rather than elevation (e.g. the Vesta/Ceres DTMs); the renderer then subtracts the body's sphere radius and skips triaxial flattening so the DEM carries the whole shape.

```json
{
  "id": "naif-301_displacement",
  "source": "https://svs.gsfc.nasa.gov/4720/#media_group_322785",
  "organisation": "NASA",
  "attribution": "NASA's Scientific Visualization Studio. Elevation: Lunar Orbiter Laser Altimeter (LOLA), LRO. Reference sphere radius 1737.4 km.",
  "type": "cylindrical_displacement",
  "displacement_bias_km": -9.13,
  "displacement_scale_km": 19.9,
  "absolute_radius": false,
  "source_file": "ldem_64.tif",
  "source_dimensions": [23040, 11520],
  "processed_at": "2026-06-29T00:00:00+00:00",
  "exports": {
    "low":    { "file": "low.webp",    "width": 2048,  "height": 1024, "size_bytes": 10000,  "lossless": false },
    "medium": { "file": "medium.webp", "width": 8192,  "height": 4096, "size_bytes": 80000,  "lossless": false },
    "high":   { "file": "high.webp",   "width": 16383, "height": 8191, "size_bytes": 250000, "lossless": false }
  }
}
```
