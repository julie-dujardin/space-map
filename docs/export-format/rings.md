# Rings

Generated during ingest (not export) and written directly to the export directory. Each ringed body's `has_rings` flag in its global JSON signals that at least one ring bundle exists; the per-system metadata (below) carries the renderer-facing blocks with strip URLs and geometry constants.

**Path:** `rings/{id}/{bundle}/strip.webp`

A body owns one or more *bundles* — radially disjoint groups of rings, each with its own sample density and scales. Saturn has three (`inner` = D ring, `primary` = the measured Cassini profiles of the main rings, `outer` = the tenuous G/E system); the other ringed giants have one, named `primary`. Bundles exist because a single 8-bit strip cannot span Saturn's range: its B ring reaches τ ≈ 5 while its E ring is τ ≈ 5e-6, and a shared `intensity_scale` would quantize the E ring to nothing. Splitting also keeps 5 km/sample across the main rings without exceeding WebP's 16 383 px dimension cap over the full 66 900–480 000 km extent.

One lossless RGB WebP per bundle, N×5 (or N×6): each row is a 1-D radial profile (channel), sampled uniformly between `inner_radius_km` and `outer_radius_km`; `sample_count` (= image width) is fixed per bundle. Scalar channels are replicated across RGB. The single file keeps loading to one request; the client splits the rows back into separate 1-px textures after decode (row-per-channel in one texture would let mipmaps bleed channels into each other), sampling `.r` for scalar channels and `.rgb` for `color`.

| Row (`strip_rows`) | Channel            | Type   | Meaning                                                |
|--------------------|--------------------|--------|--------------------------------------------------------|
| 0                  | `color`            | RGB    | Color tint (multiplied with the brightness channel).   |
| 1                  | `backscattered`    | scalar | Brightness on the sun-lit side (phase angle ≈ 0°).      |
| 2                  | `forwardscattered` | scalar | Brightness at high phase (≈ 139°).                      |
| 3                  | `unlitside`        | scalar | Brightness on the un-lit side (back-lit transmission).  |
| 4                  | `transparency`     | scalar | Per-radius opacity (1 = transparent, 0 = opaque).       |
| 5 (optional)       | `thickness`        | scalar | Vertical extent, × `thickness_scale_km` = km. Only present when the bundle tabulates thickness; absent → the bundle renders flat. |

The renderer blends `backscattered`/`forwardscattered` by phase angle, swaps in `unlitside` when the sun-side ray to a fragment is occluded by the host body, multiplies by `color`, and uses `transparency` for the alpha component (and for the host body's surface shader, which samples the same channel along the sun ray to project a ring shadow onto the planet). Only the densest bundle casts that shadow — the ray-march handles one annulus, and the faint bundles would darken nothing.

## Ring metadata (`rings/{id}/{bundle}/metadata.json`)

```json
{
  "id": "naif-699",
  "bundle": "primary",
  "sources": [
    {
      "source": "https://bjj.mmedia.is/data/s_rings/index.html",
      "organisation": "Björn Jónsson",
      "license": "Free use with attribution",
      "work": "Saturn ring profiles",
      "contribution": "back-scattered, forward-scattered and unlit-side brightness, transparency and colour of the main rings, measured from NASA PDS Cassini imaging"
    },
    {
      "source": "https://web.archive.org/web/20241206102306/https://nssdc.gsfc.nasa.gov/planetary/factsheet/satringfact.html",
      "organisation": "NASA",
      "license": "Public domain",
      "work": "NSSDCA Saturnian Rings Fact Sheet",
      "contribution": "vertical thickness of the C, B, Cassini Division and A regions …"
    }
  ],
  "description": "1-D radial profiles of Saturn's main rings: …",
  "inner_radius_km": 74510.0,
  "outer_radius_km": 140390.0,
  "sample_count": 13177,
  "intensity_scale": 1.0,
  "thickness_scale_km": 0.02,
  "color_space": "srgb",
  "processed_at": "2026-05-10T16:31:15+00:00",
  "strip": {
    "file": "strip.webp",
    "width": 13177,
    "height": 6,
    "size_bytes": 18350,
    "rows": {
      "color": 0,
      "backscattered": 1,
      "forwardscattered": 2,
      "unlitside": 3,
      "transparency": 4,
      "thickness": 5
    }
  }
}
```

- `bundle` — name of this bundle within the body, and its sub-directory. In `systems/{bary}.json` the body's `rings` is an **array** of these blocks ordered inner → outer, and each block's `strip` is bundle-relative (`"primary/strip.webp"`), so the URL is `/v1/rings/{id}/{strip}`.
- `inner_radius_km` / `outer_radius_km` — radial domain (km from the host body's centre) the bundle spans. Samples are uniformly distributed across the closed interval. Bundles of one body never overlap.
- `intensity_scale` — multiply stored scalar-channel values (and `1 − transparency`) by this to recover physical brightness/opacity. `1.0` for measured data (Saturn's main rings); synthetic bundles store channels normalised to their physical maximum because 8-bit cannot hold optical depths of ~1e-6 directly. The renderer must apply it — those bundles are *supposed* to render extremely faint. It doubles as the opacity ranking that picks the shadow-casting bundle.
- `thickness_scale_km` — km per unit of the optional `thickness` row; `0` when the bundle has no thickness data (renders as a flat sheet). The renderer spreads the ring material vertically over the per-radius extent, collapsing back to a single sheet whenever the stack spans less than about a pixel.
- `color_space` — color space for the `color` channel; `"srgb"` today.
- `sources` — every work the bundle draws on, each naming what it contributed. Bundles routinely mix provenance: Saturn's measured strips are Björn Jónsson's photometry with NSSDCA vertical extents. `organisation` is deliberately short ("NASA", not "NASA PDS Ring-Moon Systems Node / NSSDCA") so one body reads as one name across the credit UI; the specific work goes in `work`, and `contribution` is a lowercase noun phrase. `synthesised` marks a work whose tabulated numbers we rebuilt profiles from rather than shipping its own measurements.

  `credits.json` merges these across a body's bundles into one row per (URL, organisation), joining the contributions — Saturn's bundles all cite the NSSDCA fact sheet for different things, and listing it three times or keeping only the first would both misrepresent it. The in-scene attribution popover collapses further still, to one line per body and imagery kind with the organisations joined.
- `description` — optional; propagates to `systems/{bary}.json` and `credits.json`.
