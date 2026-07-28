# Rings

Generated during ingest (not export) and written directly to the export directory. Each ringed body's `has_rings` flag in its global JSON signals that a ring bundle exists; the per-system metadata (below) carries the renderer-facing block with channel URLs and geometry constants.

**Path:** `rings/{id}/strip.webp`

One lossless RGB WebP per body, N×5: each row is a 1-D radial profile (channel), sampled uniformly between `inner_radius_km` and `outer_radius_km`; `sample_count` (= image width) is fixed per source dataset. Scalar channels are replicated across RGB. The single file keeps loading to one request; the client splits the rows back into separate 1-px textures after decode (row-per-channel in one texture would let mipmaps bleed channels into each other), sampling `.r` for scalar channels and `.rgb` for `color`.

| Row (`strip_rows`) | Channel            | Type   | Meaning                                                |
|--------------------|--------------------|--------|--------------------------------------------------------|
| 0                  | `color`            | RGB    | Color tint (multiplied with the brightness channel).   |
| 1                  | `backscattered`    | scalar | Brightness on the sun-lit side (phase angle ≈ 0°).      |
| 2                  | `forwardscattered` | scalar | Brightness at high phase (≈ 139°).                      |
| 3                  | `unlitside`        | scalar | Brightness on the un-lit side (back-lit transmission).  |
| 4                  | `transparency`     | scalar | Per-radius opacity (1 = transparent, 0 = opaque).       |
| 5 (optional)       | `thickness`        | scalar | Vertical extent, × `thickness_scale_km` = km. Only present when the bundle tabulates thickness (Jupiter); absent → rings render flat. |

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
  "intensity_scale": 1.0,
  "color_space": "srgb",
  "processed_at": "2026-05-10T16:31:15+00:00",
  "strip": {
    "file": "strip.webp",
    "width": 13177,
    "height": 5,
    "size_bytes": 18350,
    "rows": {
      "color": 0,
      "backscattered": 1,
      "forwardscattered": 2,
      "unlitside": 3,
      "transparency": 4
    }
  }
}
```

- `inner_radius_km` / `outer_radius_km` — radial domain (km from the host body's centre) the profile spans. Samples are uniformly distributed across the closed interval.
- `intensity_scale` — multiply stored scalar-channel values (and `1 − transparency`) by this to recover physical brightness/opacity. `1.0` for measured data (Saturn); the synthetic tenuous systems (Jupiter/Uranus/Neptune) store channels normalised to their physical maximum because 8-bit cannot hold optical depths of ~1e-6 directly. The renderer must apply it — these systems are *supposed* to render extremely faint.
- `thickness_scale_km` — km per unit of the optional `thickness` row; `0` when the bundle has no thickness data (rings render as a flat sheet). The renderer spreads the ring material vertically over the per-radius extent (Jupiter's halo torus vs its thin main ring).
- `color_space` — color space for the `color` channel; `"srgb"` today.
- `attribution` / `description` — optional; when present they propagate to `systems/{bary}.json` and `credits.json`.
