# Surface tiles

A tile pyramid holds one surface layer of a body at the full detail of its source. The renderer fetches only the tiles that its camera needs.

Each surface layer of each body has a pyramid: the colour map (one pyramid for each month of a monthly map), the height map, the night-lights map and the specular mask. Cloud overlays and the star map do not have one.

Ingest builds the pyramids (`space-map-ingest --targets tiles`). They are not part of the export directory: a pyramid is thousands of files, and the host of the export has a file limit. They are written to `space-map-tiles/`, which has the same `v1/` layout as the export, and `infrastructure/deploy/deploy-tiles.sh` publishes them to object storage.

**Path:** `tiles/{id}/{z}/{x}/{y}.webp` for the map, and `tiles/{id}/{cap}/{z}/{x}/{y}.webp` for a polar cap (`cap` = `north` or `south`). A monthly map has one such tree for each month, in `tiles/{id}/{NN}/` (`NN` = `01`..`frames`).

`id` is the id of the [texture](textures.md) bundle of the same layer: `naif-499` for the colour map of Mars, `naif-499_displacement` for its height map. The tiers of that bundle stay in the export and are the fallback when the tile host is not available.

## Grid

All pyramids use the same grid. A tile is 1024 × 1024 px. Level `z` covers the body with `2^(z+1)` columns and `2^z` rows of tiles, in the equirectangular projection and the alignment of the tiers: 180°W at the left edge, east to the right, north at the top.

| Level | Tiles     | Full size (px)   |
|-------|-----------|------------------|
| 0     | 2 × 1     | 2048 × 1024      |
| 1     | 4 × 2     | 4096 × 2048      |
| 2     | 8 × 4     | 8192 × 4096      |
| `z`   | `2^(z+1)` × `2^z` | `2048·2^z` × `1024·2^z` |

`x` counts columns to the east from 180°W. `y` counts rows to the south from the north pole. Tile `(z, x, y)` covers the same area as the four tiles `(z+1, 2x..2x+1, 2y..2y+1)`.

The finest level (`max_level`) is the first one that is as wide as the finest source. A source that is less than 10% wider than a level is resampled down to that level. Each level below the finest is the 2 × 2 average of the level above it. Tiles do not overlap, and a level joins without a seam across the ±180° meridian.

## Polar caps

Near a pole the columns of the grid come together, and a tile is much narrower on the ground than it is high. Thus each pyramid also has a cap for each pole, in a projection that does not stretch there. The renderer uses the caps at latitudes above approximately 60°.

A cap is a square in the polar stereographic projection, with the pole at its centre. The middle of each side touches latitude 45°, and the corners are at latitude 29°. The cap shows the ground as seen from above its pole, with the prime meridian to the right. East is counter-clockwise on the north cap and clockwise on the south cap.

Level `z` of a cap has `2^(z-1)` × `2^(z-1)` tiles, from level 1 (one tile) to `max_level`. A pyramid with `max_level` 0 has no caps. `x` counts columns from the left and `y` counts rows from the top. At a level, a cap has 1/8 of the tiles of the map, so the two caps add 25% to a pyramid.

For a point at latitude `φ` and east longitude `λ`:

```
r = tan((90° − |φ|) / 2) / tan(22.5°)
u = (1 + r·cos λ) / 2
v = (1 − r·sin λ) / 2      north cap
v = (1 + r·sin λ) / 2      south cap
```

`u` and `v` are fractions of the width and the height of the cap, from its top-left corner. Tile `(z, x, y)` covers `u` from `x / 2^(z-1)` to `(x + 1) / 2^(z-1)`, and `v` from `y / 2^(z-1)` to `(y + 1) / 2^(z-1)`.

At the pole, a pixel of a cap is 5% larger on the ground than a pixel of the map at the same level. Away from the pole it becomes smaller, by 15% at the middle of a side.

## Tile content

- **Colour** (`cylindrical`, `cylindrical_monthly`, `cylindrical_night_lights`, `cylindrical_specular`): lossy WebP, quality 80, RGB.
- **Height** (`cylindrical_displacement`): lossless WebP that holds a 16-bit value. Red is the high byte and green is the low byte. Blue is 0.

  ```
  km = bias_km + scale_km · (256·R + G) / 65535
  ```

  `bias_km` and `scale_km` apply to all tiles of the pyramid, so adjacent tiles and adjacent levels agree. They are not the values of the tier bundle, which has 8 bits. The step is the smallest height difference that the source can state (1 m for the Mars DEM, 0.5 m for the lunar DEMs), unless the height range needs a larger one to fit in 16 bits. A decoder must read the bytes unchanged: no colour-space conversion and no premultiplied alpha.

## Sources of a pyramid

By default a pyramid comes from the same file as the tiers of its bundle. A manifest entry with `tiles: only` replaces that file for the pyramid, and the tiers do not change. Such an entry can combine files:

- **Insets** replace the first file over a band of latitude, with a blend 1° wide at each edge that is not a pole. A later inset goes over an earlier one. Where an inset has no data, the map under it shows. The lunar height pyramid uses LOLA for the whole body and SLDEM2015 between 60°S and 60°N.
- **Brightness layers** give a colour map the detail that it is too coarse to hold. The builder divides the brightness map by a copy of itself that is blurred to the resolution of the colour map. The result holds only the detail that the colour map cannot show. The builder then multiplies the colour map by this ratio in linear light. The tone and the colour stay those of the colour map, so the coarse levels agree with the tiers. Where the brightness map has no data, the colour map does not change. Where two brightness layers overlap, the later one is used where it has data. The lunar colour pyramid uses the 400 m colour map and the 100 m LROC wide-angle mosaic, which is normalised to one lighting and thus has no cast shadows.

A brightness layer can be one file, a grid of adjacent files, or a polar stereographic image of one cap (PDS3 label), which the builder reprojects. The Mars colour pyramid uses the 925 m Viking colour map and the 3,960 quads of the 5 m CTX mosaic.

## Build

The builder resamples the finest level from the sources one row of tiles at a time. It makes each level below from the level above.

A level wider than 524,288 px (level 9 and up) is too large to hold one row of. The builder makes it in blocks of 16 × 16 tiles. Each block gives its tiles for four levels, and one tile of the fifth level down. A row of these tiles then continues as a normal row. After each row of blocks the builder saves its progress. If the build stops, the next run continues from the last saved row, as long as the sources did not change.

The builder makes each cap from the sources, not from the tiles of the map, so a cap is as sharp as the map. It reads an equirectangular source in patches that become narrower towards the pole, where the source has many more columns than the cap has pixels. A polar stereographic source goes into a cap with a rotation and a scale only. Brightness layers are applied on the grid of the cap, where the blur has the same width on the ground in all directions.

The map and the two caps of a pyramid are built one after the other. A part that is complete is not built again when a stopped build continues.

## Descriptor (`tiles/{id}/metadata.json`)

Build metadata. It is in the metadata mirror, not in the tile tree.

```json
{
  "id": "naif-301",
  "source": "https://data.lroc.im-ldi.com/lroc/view_rdr/WAC_EMP",
  "organisation": "NASA",
  "license": "Public domain",
  "attribution": "NASA/GSFC/Arizona State University. Detail: LROC Wide Angle Camera …",
  "type": "cylindrical",
  "version": "88ef1344cc",
  "tile_size": 1024,
  "max_level": 6,
  "layers": [
    { "file": "lroc_color_poles.tif", "source": "https://…", "dimensions": [27360, 13680], "lat_range": null },
    { "files": ["WAC_EMP_643NM_E300N0450_304P.IMG", "…"], "source": "https://…", "dimensions": [109440, 36480], "lat_range": [-60, 60], "role": "brightness" }
  ],
  "levels": [
    { "level": 0, "tiles": 2, "size_bytes": 220000 },
    { "level": 1, "tiles": 8, "size_bytes": 790000 }
  ],
  "cap_levels": [
    { "level": 1, "tiles": 2, "size_bytes": 190000 }
  ],
  "processed_at": "2026-10-07T00:00:00+00:00"
}
```

- `version` — a digest of the inputs that decide the bytes of the tiles: source files, alignment, level limit and the build recipe. The renderer appends it to each tile URL as `?v=`, so tiles can be cached with no expiry.
- `layers` — the source files. The first one covers the whole body. An entry with no `role` after it is an inset. An entry with `"role": "brightness"` is a brightness layer.
- `levels` — the tiles of the map. `cap_levels` — the tiles of the two caps together, from level 1.
- `frames` — monthly maps only: the number of frames. `levels` and `cap_levels` count the tiles of all frames.
- `displacement_bias_km`, `displacement_scale_km`, `absolute_radius` — height pyramids only. See *Tile content*.

The export copies the fields that the renderer needs into a `tiles` block, inside the block of the layer (`texture`, `displacement`, `night`, `specular`) in `systems/{bary}.json`, in the object bundle and in `credits.json`:

```json
"displacement": {
  "id": "naif-499_displacement",
  "tiers": ["high", "low", "medium"],
  "scale_km": 29.44,
  "bias_km": -8.2,
  "tiles": {
    "id": "naif-499_displacement",
    "tile_size": 1024,
    "max_level": 6,
    "version": "316261e010",
    "scale_km": 65.535,
    "bias_km": -8.528,
    "source": "https://…",
    "organisation": "USGS",
    "license": "Public domain",
    "attribution": "…"
  }
}
```

The `tiles` block has its own credit fields because a pyramid can come from a different source than the tiers. `scale_km` and `bias_km` are present for height pyramids only, and `frames` for monthly maps only. `distribution` is present when the source has a restricted licence, with the same meaning as on a texture.

## Manifest fields

No field is necessary to get a pyramid. These fields change how it is built:

- `tiles: only` — the entry is the source of the pyramid of its body, in place of the entry that the tiers come from. It makes no tiers.
- `tiles_max_level` — limit on the finest level.
- `sharpen_sigma` — width of the blur that separates the detail of the brightness layers from the colour map, in pixels of the colour map. The default is 0.7. Use a larger value when the colour map is much softer than its pixel size.
- `insets` — list of finer maps, each with `file`, `source` and `lat_range: [south, north]`.
- `brightness` — list of brightness layers (colour maps only). Each has `source`, `lat_range`, and one of:
  - `file` — one equirectangular raster (PDS3 `.IMG` or greyscale TIFF),
  - `grid` — rows of adjacent files of one size, north to south, each row west to east,
  - `file` with `projection: polar_stereographic` — a PDS3 image of one cap,
  - `quads` — a regular grid of square files, each named by its south-west corner: `step_deg`, a `file` name pattern, and optionally an `archive` URL pattern for a zip that holds the file. `{lon}` and `{lat}` are the corner in whole degrees, padded with zeros, with a minus sign for west and south.

  `dir` is a directory below the source directory of the entry that holds the files. `gamma` is the display curve of integer samples that are stretched for viewing, such as 2.2; the builder removes it. `lon_at_left_deg` and `west_positive` state the alignment of the layer, as on an entry.
- `download_url` — direct link to a file, on an entry, an inset or a brightness layer. A `grid` uses `download_dir`, the URL of the directory that holds its files, and `quads` use `archive`. `space-map-download --sources texture_files` fetches the linked files, four at a time, and can resume a partial download.
