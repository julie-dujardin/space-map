# Catalogue light grid (`v1/glow/`)

The light of the Milky Way render tree as a 3D grid, so a client can draw as a glow the stars it does not draw as points. `space-map-glow` builds it from the exported tree and dust nest, and `space-map-export --only glow` writes it. The files sit beside the star tree in the same stored export, under the same base URL, `PUBLIC_EXTRASOLAR_URL`. It holds catalogue light only: no model and no mock stars.

## Directory structure

```
v1/glow/
  metadata.json          (not gzipped) entry point: frame, grid, edges, table, credits
  high/a.bin.gz          the first texture of tier high
  high/b.bin.gz          the second texture of tier high
  low/a.bin.gz, b.bin.gz the same for tier low
```

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
- `distribution`: the stricter tier of the tree and the nest, with the meaning that it has on a texture ([textures.md](textures.md)). An `undecided` tier is never served: the export refuses it at the served root.
- `quantity`, `frame`: as above. `texture_scale`: the factor in the textures, a power of two.
- `edges`: the M of each `L`, `null` for `L(all)`. `tint_edge`, `neutral_tint`: as above.
- `extinction`: `k_g`, `k_rgb`, `bluest_bp_rp`, `reddening`, `brightest_m0`.
- `table`: `magnitudes`, `place`, `place_soft`, and `colour` as the share of R, G and B, every 0.5 mag.
- `tiers`: for each tier `size`, `shells`, `scale_pc`, `reach_pc`, `mebibytes`, and `files` with `path` and `bytes`.
- `stars`: `rows`, `light` and `observed` per channel, `past_the_cap_rows`, `past_the_cap_light` and `no_colour_rows`.
- `credits`: empty. The tree and the nest credit the grid's sources in their own metadata.

## Which stars

Every row of the tree, once. The Sun has no row: the app draws it on its own path. An exact star keeps its row in the grid: the app hides the row at run time, and a voxel cannot, so a star that is focused and fainter than the cut counts twice. Its light is one star's. A row with no Gaia astrometry that sits within 1.5″ and 0.75 mag of a Gaia row repeats that star, and is left out.
