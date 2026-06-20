# Rings

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

## Ring metadata (`rings/{id}/metadata.json`)

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
