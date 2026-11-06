# Dust nest (`v1/dust/`)

The 3D dust of the Milky Way, as a static nest of Sun-centred textures. `space-map-dust` builds it from the dust maps, and `space-map-export --only dust` writes it. The files sit beside the star tree in `space-map-extrasolar/`, under the same base URL, `PUBLIC_EXTRASOLAR_URL`. They have their own directory because the star tree's export replaces `v1/x/` whole.

## Directory structure

```
v1/dust/
  metadata.json          (not gzipped) entry point: frame, levels, encoding, layers, credits
  high/l{n}.bin.gz       the `high` texture of level n
  low/l{n}.bin.gz        the `low` texture of level n
  high/far.bin.gz        the `high` texture of the far volume
  low/far.bin.gz         the `low` texture of the far volume
```

## Volume files

Each `.bin.gz` is gzip around one payload in the container of [extrasolar.md](extrasolar.md), with kind `5` (volume). The info block has 8 bytes: uint16 `nx`, `ny`, `nz`, uint8 level (`4` for the far volume), uint8 tier (`0` high, `1` low). The payload has one `uint8` column, `codes`, with `nx · ny · nz` rows, in the order that `texImage3D` reads: `index = ix + nx · (iy + ny · iz)`. The first buffer starts at a multiple of 8 bytes, so a client passes it to `texImage3D` as a `Uint8Array` with format `RED` and internal format `R8`.

Every file repeats the token of `metadata.json`, as a star tree file repeats its table's token. A client fetches `{PUBLIC_EXTRASOLAR_URL}/v1/dust/{path}?v={token}`.

## Levels

| Level | Half extent (pc) | `high` | `low` | `high` voxel (pc) |
|---|---|---|---|---|
| 0 | 20,000 × 20,000 × 2,000 | 512 × 512 × 64 | 256 × 256 × 32 | 78.1 × 78.1 × 62.5 |
| 1 | 3,000 | 256³ | 128³ | 23.4 |
| 2 | 1,250 | 256³ | 128³ | 9.8 |
| 3 | 250 | 256³ | 128³ | 1.95 |

The boxes are centred on the Sun. Level 1 is taller than level 0, so a point at 2 kpc < |z| < 3 kpc is in level 1 only. Each level holds its whole box, also the part that a finer level covers.

From a position `p` in pc in the frame of the nest, the texture coordinate of a level is `(p + half) / (2 · half)`, per axis. Texel `i` covers `[i, i + 1] / size`, as in WebGL. The finest level whose box holds `p` has the most detail.

## Far volume

Level 0 ends 20 kpc from the Sun, 11.7 kpc past the Galactic centre. The far volume holds the `rest` layer past that face, so the dust lane goes on where the model light does. It has the same field as the `rest` layer: the sightline scale times the model's dust shape. No observed layer reaches a face of level 0, so the two volumes agree there.

| Tier | Size | Texel at the plane |
|---|---|---|
| `high` | 256 × 256 × 32 | 187.5 × 187.5 × 35 pc |
| `low` | 128 × 128 × 16 | 375 × 375 × 69 pc |

The box is about `far.centre_pc`, the Galactic centre at (8,277, 0, -21) pc on nest axes, with `far.half_extent_pc` 24,000 × 24,000 × 3,000 pc. It is the inner box of the model light in [glow.md](glow.md), so one texture coordinate serves both. Height maps through asinh with `far.z_scale_pc`. With `d = p - centre_pc` and `half` the half extent:

```
u = 0.5 + 0.5 d.x / half.x
v = 0.5 + 0.5 d.y / half.y
w = 0.5 + 0.5 asinh(d.z / z_scale) / asinh(half.z / z_scale)
```

The codes decode as those of a level, with `far.floor` and `far.top`, and are compensated for `LINEAR` in the same way. **Read the far volume only where level 0 does not hold the point**, and inside its box. Texels deep in level 0 hold 0. A texel within one `low` texel of a face of level 0 holds the field, so a filtered read just outside a face reads no zeros. Where level 1 alone holds a point (2 < |z| < 3 kpc near the Sun), the far volume holds under 1e-7 mag/pc, so a reader may take either.

## Frame

Sun-centred Galactic Cartesian, in pc: x to the Galactic centre, y to l = 90°, z to the north Galactic pole. `frame.rotation_to_icrs` is the matrix `M` with `v_icrs = M · v_nest`, as rows. The star tree is ICRS, so a client turns a tree position `v` around the Sun into nest axes with the transpose of `M`.

## Encoding

The nest holds the mean extinction density over each voxel, as A0 at 550 nm in mag/pc. So a ray integral through the textures is the extinction in magnitudes. An R8 code decodes with the `floor` and `top` of the level:

```
density = floor * (exp(code / 255 * log(1 + top / floor)) - 1)
```

`code` here is the value that the texture returns times 255. Code 0 is no dust. A level has one `floor` and one `top` for both tiers, and `low` is the mean of `high` over 2 × 2 × 2 blocks, so `low` can serve as the first mip of `high`. Do not build mips with `generateMipmap`: that averages codes, and the decode is not linear.

The hardware filter works on codes, before the decode, and the decode is convex. So the build moves the codes until a `LINEAR` fetch keeps the mean of a linear filter on density. Read the textures with `LINEAR`. A `NEAREST` fetch of the same codes reads a little high.

## `metadata.json`

- `format`: the container version. `exported`: the time of the export. `token`: the token of all volume files, computed as for a table of the star tree.
- `variant`: `open` or `vergely`. Only `open` goes to the served root.
- `distribution`: the strictest tier of the sources whose values the files hold, with the meaning that it has on a texture ([textures.md](textures.md)).
- `quantity`, `frame`, `encoding`: as above.
- `calibration`: the factor from each cumulative disc map to A0 at 550 nm, fitted in the overlap with the Edenhofer maps.
- `handovers`: the bands in pc where one layer fades into the next. `local_pc` and `regional_pc` are distances from the Sun. The cube bands of `vergely` are box faces and heights.
- `levels`: for each level `level`, `half_extent_pc`, `floor`, `top`, then `high` and `low`, each with `path`, `size` and `bytes`.
- `far`: the far volume: `centre_pc`, `half_extent_pc`, `z_map` (`asinh`), `z_scale_pc`, `floor`, `top`, `read` (where a reader takes it), then `high` and `low` as for a level.
- `layers`: the four layers, `local`, `regional`, `disc` and `rest`, with `sources`, `distribution` and `model`. `model` is true on `rest`: that layer has no observed 3D position. Its shape is the model Galaxy's dust disc, which shares the young light's arms, warp and flare (`space_map_data.galaxy.geometry`). `share_of_sun_column_by_level` is its share in the part of the Sun-view column that each level serves. `shape`, `scale` and `unplaced_share_of_remainder` describe it: `scale.base_sigma_deg` is the Gaussian of the base in l and b, `scale.near_room_share` the window of the sightline's factor as shares of its room, `scale.max_near_factor` the largest factor.
- `credits`: every source with `key`, `name`, `citation`, `source`, `license`, `distribution`, and `attribution` where the source asks for a text; then the papers of the rest layer's shape, with no `license`.

## Layers

| Layer | Reach | Source |
|---|---|---|
| `local` | to 1,050 pc, fades out to 1,240 pc | Edenhofer 2024 mean × 2.680. Its integrated inner 69 pc column is spread along each ray. |
| `regional` | to 1,500 pc, fades out to 1,950 pc | The Edenhofer 2 kpc map. In `vergely`, the Vergely 2022 v2 cubes lie over it, to ±3 kpc and ±5 kpc, at \|z\| < 400 pc. |
| `disc` | in the reliable range of each sightline, from `DM_reliable_min` to `DM_reliable_max`, each faded over 0.5 mag | Bayestar19 and DECaPS, as density per distance bin. A radial spoke is expected here: a distance bin is far longer than a pixel is wide. |
| `rest` | the share that the others leave, and the far volume past level 0 | The Planck total minus the observed column, along Drimmel & Spergel's dust disc and arms on the young arms of Reid et al. 2019 and Drimmel et al. 2025. The scale of a sightline is a base, smooth on the sky, times the sightline's own factor on the near part of its room: the first `near_room_share[0]` of the room, faded out by `near_room_share[1]`. So the column from the Sun is that of the sightline, and from outside the far disc shows no radial spokes. |
