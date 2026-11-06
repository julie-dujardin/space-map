# Catalogue light grid (`v1/glow/`)

The light of the Milky Way render tree as a 3D grid, so a client can draw as a glow the stars it does not draw as points, and the model light the catalogue lacks, so the glow holds the whole Galaxy. `space-map-glow` builds the grid from the exported tree and dust nest, `space-map-galaxy` builds the model against that grid, and `space-map-export --only glow` writes both. The files sit beside the star tree in the same stored export, under the same base URL, `PUBLIC_EXTRASOLAR_URL`. The model is smooth light from published structure, labelled as model: no mock stars.

## Directory structure

```
v1/glow/
  metadata.json          (not gzipped) entry point: frame, grid, edges, table, credits
  high/a.bin.gz          the first texture of tier high
  high/b.bin.gz          the second texture of tier high
  low/a.bin.gz, b.bin.gz the same for tier low
  high/model-inner.bin.gz the model's inner box, tier high
  high/model-outer.bin.gz the model's outer box, tier high
  low/model-inner.bin.gz, model-outer.bin.gz the same for tier low
  high/halpha.bin.gz     H-alpha near the Sun, tier high
  high/scatter.bin.gz    J, the light that dust scatters, tier high
  low/halpha.bin.gz, scatter.bin.gz the same for tier low
  regions.bin.gz         the far H II regions, both tiers
```

A build with no model writes the grid alone and no `model` key; a client then draws the catalogue only. A build with no emission writes no `emission` key and none of its files; the emission goes only with a model, since its scattered light takes the model's light.

## Volume files

Each `.bin.gz` is gzip around one payload in the container of [extrasolar.md](extrasolar.md), with kind `5` (volume). The info block has 8 bytes: uint16 `width`, `height`, `shells`, uint8 texture (`0` is `a`, `1` is `b`), uint8 tier (`0` `high`, `1` `low`).

One column, `texels`, of type `uint16`, holds four values per texel in the order of `texImage3D`: x fastest, then y, then z. Each value is the bits of a half float. Upload it as it stands: internal format `RGBA16F`, format `RGBA`, type `HALF_FLOAT`, min and mag filter `LINEAR`, `CLAMP_TO_EDGE`. The textures are interleaved because the values of a voxel often repeat, and gzip takes about 40% more off that way than with a column per channel.

Every file repeats the token of `metadata.json`. A client fetches `{PUBLIC_EXTRASOLAR_URL}/v1/glow/{path}?v={token}`.

## Grid

A texel is one octahedral cell of the sky as seen from the Sun, the same map as a dust sky map: +z, the north Galactic pole, is the centre of the square, and a ring of one texel past the edge holds the rays past the fold. The third axis is a shell, even in `log(1 + r / scale)`.

| Tier | Cells | Shells | `scale` | `reach` | GPU | Cell at the plane |
|---|---|---|---|---|---|---|
| `high` | 256² | 60 | 20 pc | 400 kpc | 60 MiB | 0.6° to 1° |
| `low` | 128² | 60 | 20 pc | 400 kpc | 15 MiB | 1.2° to 2° |

A shell is about 3 pc at the Sun, 17% of the radius past 1 kpc, and 1.3 kpc at 8 kpc. That is about the distance error of a star at those distances, so a finer shell would draw the error. A voxel spans the same solid angle at every distance, so one texture covers all of the catalogue. Sampling a position `p` in pc on nest axes:

```
r = length(p)
u, v = octahedral cell of p / r, as dustOctUv with this tier's size
w = log(1 + r / scale) / log(1 + reach / scale)
```

Past `reach` there is no light. `tiers.<tier>.size` and `shells` give the sizes.

## Frame

As the dust nest ([dust.md](dust.md)): Sun-centred Galactic Cartesian, in pc. `frame.rotation_to_icrs` is the matrix `M` with `v_icrs = M · v_grid`, as rows.

## Values

A voxel holds eight values:

| | r | g | b | a |
|---|---|---|---|---|
| `a` | `L(all)` | `L(M0 > -5)` | `L(M0 > -2)` | `L(M0 > 0)` |
| `b` | `L(M0 > 1)` | `L(M0 > 3)` | `L(M0 > 5)` | `tint` |

`L` is the sum of R + G + B of the stars fainter than an edge, over the volume of the voxel, in flux of M = 0 at 10 pc per pc³, times `texture_scale`. A star's R, G, B come from its colour as the app draws it (largest channel 1), so a star of M = 0 and colour white has flux 3. It falls with M in every voxel, and a filtered read of such values still falls, so `LINEAR` is exact and no decode is needed. `tint` is B / (R + B) of `L(M0 > 0)`, `neutral_tint` where the voxel holds no such light.

`M0` is the star's absolute G with the Sun's dust taken out:

```
exact = max(0, min((BP - RP + 0.3) / 0.447, (mag + 10) / k_g)), 0 for a star with no colour
bound = round(min(exact, 16) / 16 · 255) / 255 · 16, the round taking a half up
taken = min(A(Sun → star), bound)
M0    = mag - k_g · taken
flux  = colour · 10^(-0.4 · (mag - k_rgb · taken))
```

The bound is the most A0 a star can gain from a viewpoint with less dust than the Sun: no more than its colour shows it lost, and no more than takes it to M = -10, which no real star passes. The star shader holds it as one byte of 0 to 16 A0 per star, so the grid takes out the same byte.

`A(Sun → star)` is the column a star reads from the Sun's sky map, built as the client builds it: the `high` nest, its step law and its eight passes.

## Reading

A cut `M_cut` gives a `place` and a colour from `table`, linear between entries:

```
place, colour = table at M_cut
L    = sum over k of values[k] · max(1 - abs(place - k), 0), for k in 0 .. 6
t    = clamp(tint, 0.001, 0.999)
rgb  = colour · ((1 - t) / (1 - neutral_tint), 1, t / neutral_tint)
j    = L · rgb / (r + g + b of rgb) / texture_scale
```

`place` runs from 0 to 7, and at 7 the light is 0. It comes from the summed light of all stars at that M, so the sum over all voxels is exact at each M. `place_soft` is the same for light weighted by `1 - fade`, for a client whose stars fade in over a magnitude.

`j` is flux per pc³. Toward a direction, the flux per sr is `100 ∫ j · 10^(-0.4 · k_rgb · A(s)) ds`, with `s` and `ds` in pc: the 100 is (10 pc)². A star of apparent magnitude `m` and colour `c` holds the flux `c · 10^(-0.4 m)` in the same unit.

## `metadata.json`

- `format`: the container version. `token`: the token of all texture files, computed as for a table of the star tree.
- `inputs`: the tokens of the tree and the nest that the grid holds. There is no time in this file, so a rerun on the same inputs writes the same bytes.
- `distribution`: the strictest tier of the tree, the nest and the emission's sources, with the meaning that it has on a texture ([textures.md](textures.md)). An `undecided` tier is never served: the export refuses it at the served root.
- `quantity`, `frame`: as above. `texture_scale`: the factor in the textures, a power of two.
- `edges`: the M of each `L`, `null` for `L(all)`. `tint_edge`, `neutral_tint`: as above.
- `extinction`: `k_g`, `k_rgb`, `bluest_bp_rp`, `reddening`, `brightest_m0`.
- `table`: `magnitudes`, `place`, `place_soft`, and `colour` as the share of R, G and B, every 0.5 mag.
- `tiers`: for each tier `size`, `shells`, `scale_pc`, `reach_pc`, `mebibytes`, and `files` with `path` and `bytes`.
- `stars`: `rows`, `light` and `observed` per channel, `past_the_cap_rows`, `past_the_cap_light` and `no_colour_rows`.
- `model`: the model light, below. Absent when the export holds none.
- `emission`: H-alpha and scattered starlight, below. Absent when the export holds none.
- `credits`: the papers and datasets of the model and of the emission, with the fields of a dust source; empty when the export holds neither. The tree and the nest credit the grid's sources in their own metadata. The nest also lists the papers of the rest layer's shape, which the model reads too.

## Which stars

Every row of the tree, once. The Sun has no row: the app draws it on its own path. An exact star keeps its row in the grid: the app hides the row at run time, and a voxel cannot, so a star that is focused and fainter than the cut counts twice. Its light is one star's. A row with no Gaia astrometry that sits within 1.5″ and 0.75 mag of a Gaia row repeats that star, and is left out.

## Model light (`model`)

`j_glow = j_cat(fainter than M_cut) + residual`, where `residual = max(0, j_model - j_cat,total)`, voxel by voxel: the model's light less the light of all stars of this grid, where the model holds more. The residual has no cut: it holds stars the catalogue does not have, which never draw as points. One token covers grid and model, because the residual is defined against this grid.

The model has two boxes on nest axes, about `model.centre_pc`, the Galactic centre at (R0, 0, -z0). A sample reads the inner box where it holds the point, else the outer one, else nothing: one fetch.

| Box | Half extent | `high` | `low` | Height map |
|---|---|---|---|---|
| inner | 24 x 24 x 3 kpc | 512 x 512 x 32, 16 MiB | 256 x 256 x 16, 2 MiB | asinh, 150 pc |
| outer | 64 kpc cube | 128³, 4 MiB | 64³, 0.5 MiB | linear |

Each file is kind `5`, info block uint16 width, height, depth, uint8 texture (`2` inner, `3` outer), uint8 tier; one column `texels`, `uint16`, the bits of one half float per texel, x fastest. Upload as `R16F`, `RED`, `HALF_FLOAT`, `LINEAR`, `CLAMP_TO_EDGE`. A texel is R + G + B display flux density per pc³, in flux of M = 0 at 10 pc, with no dust, times `model.texture_scale`.

Texture coordinates of a position `p` (pc, nest axes), with `d = p - centre_pc` and `half` the box's `half_extent_pc`:

```
u = 0.5 + 0.5 d.x / half.x
v = 0.5 + 0.5 d.y / half.y
w = 0.5 + 0.5 asinh(d.z / z_scale) / asinh(half.z / z_scale)   (inner)
w = 0.5 + 0.5 d.z / half.z                                      (outer)
```

The colour comes from `model.colour`: `rgb` rows sum to 1. Rows `0 .. radii·heights - 1` are a grid in cylindrical radius from the centre (`radius_step_pc`, `radii` nodes from 0) and height from the plane (`height_step_pc`, `heights` nodes from 0), read bilinearly with both clamped, row `j·radii + i`. Past `reach_pc` from the centre (spherical) a row per shell holds instead: `radii·heights + k`, with `k` the number of `shells_pc` edges below the radius. The light times that row is `j` per channel.

`model.far_side_arms` is the contrast of the young arms past the Galactic centre in this build: 1 draws the published geometry, 0 their mean over azimuth. `catalogue_fade_pc` is `null`, or the distances from the Sun over which a client fades the grid's light to 0, as the residual was built. `components` gives each component's G flux and BP - RP. `boxes` and `tiers` give the sizes and paths.

## Emission (`emission`)

Light that is not starlight, in the unit of the model: R + G + B display flux density per pc³, in flux of M = 0 at 10 pc, with no dust. Every part is a model or an estimate scaled to an observed total, and is labelled `model`. One token covers it with the grid and the model, because the scattered light is defined against both and against the nest. An export refuses an emission build made on another nest, grid or model, or from a WISE catalogue or Finkbeiner map that has changed since, and leaves the emission out when it serves no model. Every value of this block comes from the emission build's `encoding.json`, so it describes the files as they were encoded.

**Lines.** H-alpha with [N II] 6584 at 0.25 of it and 6548 at a third of that, and H-beta at 1/2.87 (case B). Its colour is `emission.lines.colour` (rows sum to 1); the red channel holds the 656 nm lines and the green and blue channels H-beta, so each channel dims at its own line: transmission `10^(-0.4 · k_rgb[c] · A0)` with `emission.lines.k_rgb`, not the stars' `k_rgb`.

**H-alpha near the Sun (`halpha`).** McCallum et al. 2025's cube, scaled per sightline so that, seen from the Sun through the nest, it meets Finkbeiner 2003 less the far regions and a scattered share. A cube about the Sun of half extent `half_extent_pc` (1,250 pc), the box of the nest's level 2: `high` 256³ (16 MiB), `low` 128³ (2 MiB). Kind `5`, info block uint16 width, height, depth, uint8 texture `4`, uint8 tier; one column `codes`, `uint8`, x fastest. Upload as `R8`, `RED`, `UNSIGNED_BYTE`, `UNPACK_ALIGNMENT` 1, `LINEAR`, `CLAMP_TO_EDGE`, and decode after the fetch: `floor · (exp(texel · log(1 + top / floor)) - 1)`, with `floor` and `top` of the tier. Codes are compensated for `LINEAR`, as the nest's are. Texture coordinates: `(p + half) / (2 half)`, read only where the box holds `p`.

**Scattered light (`scatter`).** The isotropic single-scattering source is, per channel,

```
j_scat = albedo[c] · k_rgb[c] · density / 1.0857 · J · colour[c] · shield(density)
```

with `density` the nest's A0 per pc at the step, `k_rgb` the stars' (`extinction.k_rgb`), `albedo` of `scatter.albedo`, and `J` the mean intensity of the glow's light with no cut, stored as R + G + B, in flux of M = 0 at 10 pc per pc² (so `j_scat` is in the glow's unit). It takes the stars' transmission. The box is the model's inner box (`centre_pc`, `half_extent_pc`, asinh height with `z_scale_pc`), so the model's texture coordinates serve: `high` 128 x 128 x 16, `low` 64 x 64 x 8. Kind `5`, texture `5`, one column `texels` of half-float bits times `form.texture_scale`; upload as `R16F`, `RED`, `HALF_FLOAT`, `LINEAR`, `CLAMP_TO_EDGE`; 0 outside the box.

- `form.colour`: a table of `distances` x `radii` RGB rows (each sums to 1), `rgb[k][i]`. `i` is even in cylindrical radius from the Galactic centre, 0 to `r_max_pc`; `k` is even in `log(1 + d / d_scale_pc)` with `d` the distance from the Sun, 0 to `d_max_pc`; read bilinearly with both clamped, as an `RGBA16F` 2D texture of `radii` x `distances` would be.
- `form.shield`: J inside dust over the grid's J, at `log10_density_nodes` (A0 mag/pc); linear between nodes, held past the ends. The grid's J is a voxel mean; dense dust shields itself from it.

**Far H II regions (`regions`).** The WISE Catalog of Galactic H II Regions V3.0, the rows with a distance outside 1,250 pc. Kind `6` (table), no info block, one row a region, columns `x`, `y`, `z` (pc, nest axes), `sigma_pc`, `light` (`float32`) and `source` (`uint8`: 0 radio, 1 infrared, 2 the mean rate at the region's size, an estimate). Each is a Gaussian ball of `sigma_pc` with `light` of R + G + B display flux at 10 pc, intrinsic: the client dims it by the column from the camera, per channel at `lines.k_rgb`.
