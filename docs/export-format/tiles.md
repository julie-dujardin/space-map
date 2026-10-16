# Surface tiles

A tile pyramid holds one surface layer of a body at the full detail of its source. The renderer fetches only the tiles that its camera needs.

Each surface layer of each body has a pyramid: the colour map (one pyramid for each month of a monthly map), the height map, the night-lights map and the specular mask. Cloud overlays and the star map do not have one.

Ingest builds the pyramids (`space-map-ingest --targets tiles`). They are not part of the export directory: a pyramid is thousands of files, and the host of the export has a file limit. They are written to `space-map-tiles/`, which has the same `v1/` layout as the export. The tile host (`infrastructure/tiles/`) serves that directory as it is, so a pyramid is public when its build ends.

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

## Patches

A landing site can have a mosaic that is much sharper than the map of its body. A patch holds such a mosaic: it continues the pyramid past `max_level`, but only over the ground that the mosaic covers.

A patch uses the grid and the paths of the map: `tiles/{id}/{z}/{x}/{y}.webp`, with `z` from `max_level + 1` to the `max_level` of the patch. At its finest level, the patch has the tiles from column `x[0]` to `x[1]` and from row `y[0]` to `y[1]`. At a level `n` levels above that, it has the tiles from `x[0] >> n` to `x[1] >> n` and from `y[0] >> n` to `y[1] >> n`. No other tile of these levels exists, and a renderer must not ask for one.

The builder makes a patch from the finest tiles of the pyramid and from the mosaic. The colour and the tone at large scales are those of the tiles, so a patch joins the map around it without a step. All detail below a set scale comes from the mosaic alone. The map and a mosaic of another team can disagree on the position of a feature by some pixels of the map, and a mix of their detail would show the feature twice. At the edge of the mosaic the patch fades into the map. A tile of a patch that the mosaic covers only in part shows the enlarged map in the remaining part.

A patch also shows in the finest levels of the pyramid: `map_levels` of them, from `max_level` of the pyramid up. Without this, a view that goes in would change one picture of the ground for another at the first level of the patch. The builder draws the patch over each tile of these levels that the mosaic touches, with the same fade at the edge of the mosaic. The scale below which the mosaic gives the detail is half as many pixels at each coarser level. `map_levels` is the number of levels where this scale is more than one pixel: 4 levels for the default of 16 pixels, and none for 1 pixel or less. A patch of a height pyramid has none: its tiles hold heights in three bytes, which cannot be mixed as colours are. These tiles keep their paths. The builder keeps the tile that the pyramid made in `.map/{z}/{x}/{y}.webp` and the picture that each patch draws over it in `.over/{patch id}/{z}/{x}/{y}.webp`, both in the directory of the pyramid. It makes the tile again from these when a patch changes, and puts the tile of the pyramid back when no patch touches it. A renderer does not read these two directories.

Two patches of one pyramid have no tile in common past `max_level` of the pyramid. At the first level of a patch a tile is large, so two mosaics that are near each other can touch the same tile. The builder refuses the second of two such patches: mosaics that are this near belong in one patch.

A renderer draws the levels of a patch when a window of that level reaches the tiles of the patch, also from a point beside the patch. These levels have no tiles around the patch, so a renderer keeps some windows on the levels of the pyramid for the ground there.

A height pyramid can have patches too. Such a patch holds a terrain model of the site, and the builder makes it in the same way, with sums in place of ratios. The heights at large scales are those of the pyramid. The terrain model gives the relief below the set scale. A terrain model and the map of its body are tied to the body by different measurements, and one can be some metres above the other. The builder thus measures the difference between them at the set scale and removes it. Two terrain models of one patch can also be some decimetres apart where they meet. A later model thus replaces an earlier one gradually, across 16 pixels of the finest level from each edge of its data. A height patch of a site usually has the `id` of the colour patch of that site, but the two are not related: each has its own tile ranges and its own `max_level`.

The polar caps have no patches.

## Tile content

- **Colour** (`cylindrical`, `cylindrical_monthly`, `cylindrical_night_lights`, `cylindrical_specular`): lossy WebP, quality 80, RGB.
- **Height** (`cylindrical_displacement`): lossless WebP that holds a 16-bit value. Red is the high byte and green is the low byte. Blue counts 256ths of one step of that value.

  ```
  km = bias_km + scale_km · (256·R + G + B/256) / 65535
  ```

  `bias_km` and `scale_km` apply to all tiles of the pyramid and of its patches, so adjacent tiles and adjacent levels agree. They are not the values of the tier bundle, which has 8 bits. The step is the smallest height difference that the source can state (1 m for the Mars DEM, 0.5 m for the lunar DEMs), unless the height range needs a larger one to fit in 16 bits. A decoder must read the bytes unchanged: no colour-space conversion and no premultiplied alpha.

  In the tiles of the pyramid, blue is 0. Only the tiles of a patch use it. A pixel of a patch can be 100 times smaller than a pixel of the pyramid, and a full step between two such pixels would show as a staircase. A tile that is `n` levels below `max_level` of the pyramid states its heights to `1/2^n` of a step, and to 1/256 from 8 levels down. The step thus has the same ratio to the pixel at each level. A decoder that ignores blue gets the height rounded down to a full step.

## Sources of a pyramid

By default a pyramid comes from the same file as the tiers of its bundle. A manifest entry with `tiles: only` replaces that entry for the pyramid, and the tiers do not change. It refines the bundle whose tiers come from the file that it names, which can be the best map of the body or an alternate one. If no bundle comes from that file, it refines the best map. Such an entry can combine files:

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
    { "file": "lroc_color_poles.tif", "source": "https://…", "dimensions": [27360, 13680], "full_width": 27360, "lat_range": null },
    { "files": ["WAC_EMP_643NM_E300N0450_304P.IMG", "…"], "source": "https://…", "dimensions": [109440, 36480], "full_width": 109440, "lat_range": [-60, 60], "role": "brightness" }
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
- `layers` — the source files. The first one covers the whole body. An entry with no `role` after it is an inset. An entry with `"role": "brightness"` is a brightness layer. `dimensions` is the size of the files in pixels. `full_width` is the width that a map of the whole body has at the pixel size of the layer: for an equirectangular layer it is the width of the files, and for a polar stereographic image it follows from the pixel size at the pole.
- `levels` — the tiles of the map. `cap_levels` — the tiles of the two caps together, from level 1.
- `frames` — monthly maps only: the number of frames. `levels` and `cap_levels` count the tiles of all frames.
- `patches` — present when the pyramid has patches. Each has an `id`, a display `name`, its own credit fields (`source`, `organisation`, `license`, `attribution`), a `version`, its `max_level`, the tile ranges `x` and `y` at that level, its `map_levels`, its source `files` and its `levels`. `full_width` is that of its finest file, as on a layer. `bounds` are the `west`, `east`, `south` and `north` edges of its files together, in degrees.
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

A pyramid with patches has a `patches` array in the block. Each patch has `id`, `max_level`, `map_levels`, `x`, `y`, `version` and its credit fields:

```json
"patches": [
  {
    "id": "jezero",
    "max_level": 16,
    "map_levels": 4,
    "x": [93652, 93783],
    "y": [25970, 26102],
    "version": "5c0a91d2e7",
    "source": "https://…",
    "organisation": "USGS",
    "license": "Public domain",
    "attribution": "…"
  }
]
```

The tiles of a patch use the `version` of the patch in `?v=`, not that of the pyramid. A patch also changes tiles of the pyramid: the tiles of the map that are in its range at the last `map_levels` levels of the pyramid, with the range found as for the levels of the patch. Such a tile uses the versions of the patches that have it, in the order of the array, with a `.` between them. The caps have no such tiles.

The `tiles` block has its own credit fields because a pyramid can come from a different source than the tiers. `scale_km` and `bias_km` are present for height pyramids only, and `frames` for monthly maps only. `distribution` is present when the source has a restricted licence, with the same meaning as on a texture.

## Manifest fields

No field is necessary to get a pyramid. These fields change how it is built:

- `tiles: only` — the entry is the source of the pyramid of its body, in place of the entry that the tiers come from. It makes no tiers.
- `tiles_max_level` — limit on the finest level.
- `sharpen_sigma` — width of the blur that separates the detail of the brightness layers from the colour map, in pixels of the colour map. The default is 0.7. Use a larger value when the colour map is much softer than its pixel size.
- `soften_colour` — blurs the colour map by `sharpen_sigma` before the brightness layers go on it. Use it when the colour map and a brightness layer disagree on the position of features by some pixels of the colour map: the colour map then gives the tint only, and no feature shows twice. It has no effect on an entry without brightness layers.
- `insets` — list of finer maps, each with `file`, `source` and `lat_range: [south, north]`.
- `brightness` — list of brightness layers (colour maps only). Each has `source`, `lat_range`, and one of:
  - `file` — one equirectangular raster (PDS3 `.IMG` or greyscale TIFF),
  - `grid` — rows of adjacent files of one size, north to south, each row west to east,
  - `file` with `projection: polar_stereographic` — a PDS3 image of one cap,
  - `quads` — a regular grid of square files, each named by its south-west corner: `step_deg`, a `file` name pattern, and optionally an `archive` URL pattern for a zip that holds the file. `{lon}` and `{lat}` are the corner in whole degrees, padded with zeros, with a minus sign for west and south.

  `dir` is a directory below the source directory of the entry that holds the files. `gamma` is the display curve of integer samples that are stretched for viewing, such as 2.2; the builder removes it. `lon_at_left_deg` and `west_positive` state the alignment of the layer, as on an entry.
- `patches` — list of patches (colour maps and height maps). Each has an `id`, a display `name`, credit fields, and `files`: a list of greyscale rasters in the equirectangular projection (GeoTIFF, compressed or not, or PDS3 image with an attached label), each with `file` and optionally `dir`, `download_url` and `gamma`. A later file goes over an earlier one, so mosaics that overlap belong in one patch, and so do mosaics that touch the same tile at the level after the finest level of the pyramid. `sharpen_sigma` is the scale below which the files give all the detail, in pixels of the finest level of the pyramid (default 16). `tiles_max_level` limits the finest level of the patch. A change to a patch does not rebuild the pyramid, and the tiles of the patch stay until the new ones are complete.

  A GeoTIFF must count metres from the equator and the central meridian, with its tiepoint at the first pixel, and its samples must be a grey scale with black at zero. A PDS3 image must count longitude east. In integer samples, zero means no data. In float samples, only the null value of the file means no data: a value at or below zero is ground in shadow. The builder refuses a file that does not obey these rules, and builds the other patches.

  The files of a patch of a height map are terrain models, in the same projection and file formats. Each can have `height_unit`, `height_scale`, `height_offset` and `height_nodata`, with the same meaning as on the entry. The default is the value of the entry, then the value that the file states, and metres for the unit. A file with integer samples must have a value for no data. `gamma` does not apply. Some terrain models fill their gaps with a coarser model, enlarged to square blocks of one height. Each block edge is then a step in the ground. `fill_block` gives the side of these blocks in pixels, with the blocks aligned to the first pixel of the file. The builder reads a pixel that has the height of a neighbour in its row and of a neighbour in its column as the smooth surface through the means of the blocks.
- `download_url` — direct link to a file, on an entry, an inset, a brightness layer or a file of a patch. A `grid` uses `download_dir`, the URL of the directory that holds its files, and `quads` use `archive`. `space-map-download --sources texture_files` fetches the linked files, four at a time, and can resume a partial download.
