# Extrasolar objects (`v1/x/`)

The objects outside the solar system: their record tiles, one tree per table, the Milky Way render tree, and the constellation figures of the sky cultures. `space-map-export --only extrasolar` builds them from the extrasolar registry and its tables. They are not part of the main export: the stars alone are over half a million files, and the host of the main export has a file limit. They are written to `space-map-extrasolar/v1/x/` and are served from their own base URL, `PUBLIC_EXTRASOLAR_URL`. Without that URL a client has no stars and no `/x/` pages.

An object has one ID for all its files. The ID, its URL form and its check are in the design of the registry: `id = serial·2^29 + table·2^24 + cell`, with `cell` the HEALPix level-10 nested cell (ICRS) and `table` the home table. A client decodes it with division, never with bit operators: `cell = id % 2^24`, `table = floor(id / 2^24) % 32`, `serial = floor(id / 2^29)`.

## Directory structure

```
v1/x/
  metadata.json                          (not gzipped) entry point: format, tokens, tables, trees, credits
  metadata/split.bin.gz                  split table of the Metadata tiles
  metadata/{level}/{pixel}.bin.gz        Metadata record tiles
  point-source/split.bin.gz              split table of the Point source tiles
  point-source/{level}/{pixel}.bin.gz    Point source record tiles (table 1)
  mw/node/{name}.bin.gz                  Milky Way render nodes
  mw/id/{name}.bin.gz                    the ID column of each render node
  skycultures/{key}.json.gz              a sky culture: figures, members and star names
```

Each `.bin.gz` file is gzip around one payload in the container format below. A `.json.gz` file is gzip around UTF-8 JSON. The server sends it as `application/octet-stream` with no `Content-Encoding`, and the client decodes it with `DecompressionStream('gzip')`. A client fetches each file as `{PUBLIC_EXTRASOLAR_URL}/v1/x/{path}?v={token}`, with the token of its table or tree.

## Container

All numbers are little-endian. The payload starts with a header of 32 bytes:

| Offset | Type     | Field |
|--------|----------|-------|
| 0      | char[4]  | Magic `SMXS` |
| 4      | uint16   | Format version (1) |
| 6      | uint8    | Kind: `1` record tile, `2` split table, `3` render node, `4` render IDs |
| 7      | uint8    | 0 |
| 8      | char[16] | Token of the table or tree, 16 ASCII hex digits |
| 24     | uint32   | Row count `n` |
| 28     | uint16   | Column count |
| 30     | uint16   | Info length `h`, a multiple of 8 |
| 32     | `h` bytes | Info block of the kind (below) |

The column directory follows the info block. For each column:

| Type | Field |
|------|-------|
| uint8 | Type code (below) |
| uint8 | Flags. Bit 0: the first buffer is a validity bitmap |
| uint8 | Buffer count `b` |
| uint8 | Name length `L` |
| `L` bytes | Column name, UTF-8 |
| `b` × (uint32, uint32) | Byte offset and byte length of each buffer, from the start of the payload |

The directory entries are not aligned; read them with a `DataView`. Each buffer starts at a multiple of 8 bytes from the start of the payload. If the payload is the start of its own `ArrayBuffer`, as `await response.arrayBuffer()` gives, a client makes each buffer a typed array without a copy: `new Float32Array(buffer, offset, length / 4)`.

The validity bitmap has `ceil(n / 8)` bytes. Row `i` has a value when bit `i & 7` of byte `i >> 3` is 1. When there is no bitmap, every row has a value. A float with no value is also NaN in the data, and an integer with no value is 0.

| Code | Type | Buffers after the bitmap | Read as |
|------|------|--------------------------|---------|
| 1 | `bool` | `n` bytes, 0 or 1 | `Uint8Array` |
| 2 | `int8` | `n` values | `Int8Array` |
| 3 | `int16` | `n` values | `Int16Array` |
| 4 | `int32` | `n` values | `Int32Array` |
| 5 | `uint8` | `n` values | `Uint8Array` |
| 6 | `uint16` | `n` values | `Uint16Array` |
| 7 | `uint32` | `n` values | `Uint32Array` |
| 8 | `float32` | `n` values | `Float32Array` |
| 9 | `float64` | `n` values | `Float64Array` |
| 10 | `id` | `n` float64 values, each an integer below 2^53 | `Float64Array`: exact JS numbers, no BigInt |
| 11 | `string` | offsets (`n + 1` × uint32), UTF-8 bytes | row `i` is bytes `offsets[i]` to `offsets[i + 1]`, through `TextDecoder` |
| 12 | `dict` | codes (`n` × uint16), dictionary offsets (`k + 1` × uint32), dictionary UTF-8 | row `i` is dictionary string `codes[i]` |
| 13 | `cross_ids` | list offsets (`n + 1` × uint32), codes (`m` × uint16), id offsets (`m + 1` × uint32), id UTF-8, pair offsets (`2k + 1` × uint32), pair UTF-8 | see below |
| 14 | `bits` | `ceil(n / 8)` bytes, bit `i & 7` of byte `i >> 3` | the split table |

A `cross_ids` column lists the catalogue ids of each row, as (catalogue, release, catalogue id). The entries of row `i` are `j = list[i]` to `list[i + 1] − 1`. Entry `j` has catalogue `pair[2·codes[j]]`, release `pair[2·codes[j] + 1]` and catalogue id string `j` of the id strings. `pair` is the string list of the last two buffers. The entries of a row are sorted by catalogue, release and catalogue id.

The bytes are deterministic: gzip with mtime 0 and level 9. The first 32 bytes of the payload sit in a stored deflate block of their own.

### Kinds

| Kind | Info block | Columns |
|------|------------|---------|
| 1 record tile | 8 bytes: uint32 pixel, uint8 level, uint8 table number (0 for Metadata), 2 bytes 0 | every column of the table, in the order that `metadata.json` lists |
| 2 split table | none | `split` (`bits`), one row per pixel of the tile tree |
| 3 render node | 80 bytes, below | `x`, `y`, `z`, `range`, `mag`, `colour` (`float32`), `class` (`uint8`) |
| 4 render IDs | none | `id` (`id`), the rows of its node in the same order |

Info block of a render node:

| Offset | Type | Field |
|--------|------|-------|
| 0 | float64 × 3 | Centre of the node's box (pc) |
| 24 | float64 | Half size: distance from the centre to each face (pc) |
| 32 | float32 | Smallest visibility range of the node's rows (pc) |
| 36 | float32 | Largest visibility range of the node's rows (pc) |
| 40 | float32 × 8 | For child octant `k`, the largest visibility range in its subtree, 0 when there is no child |
| 72 | uint8 | Depth (root 0) |
| 73 | uint8 | Child mask: bit `k` is set when child `k` exists |
| 74 | 6 bytes | 0 |

## Tokens

Each table and each tree has a token: the first 16 hex digits of SHA-256 over, for each of its files sorted by path, the path relative to `v1/x/`, a zero byte and the SHA-256 of the payload with the token field set to zeros. The split table is one of the files of its table, and the ID files are files of their tree. `metadata.json` is not in any token.

`metadata.json` lists the tokens, every URL carries its token as `?v=`, and every file repeats it in its header. A file whose header token is not the one that the client expects comes from another export: the client shows the reload prompt. This also catches an edge cache that serves a new file under an old URL. A table that did not change keeps its token, and its files stay cached. A table that changed gets a new token and new URLs for all its files.

## Record tiles

A table is cut into HEALPix nested pixels, ICRS. A tile at level `L` (0 to 10) and pixel `p` holds the rows whose ID has its cell (level 10) in that pixel: cells `p · 4^(10 − L)` to `(p + 1) · 4^(10 − L) − 1`. The 12 level-0 pixels are the roots. A pixel splits into its four children `4p` to `4p + 3` at level `L + 1` while it holds more rows than `max_rows` of the table, down to level 10, the level of the cells. A leaf of this tree is a tile. Every leaf has a file, also a leaf with no rows.

The split table has one bit per pixel of the tree, also for the leaves and the level-10 pixels. The bits are in pre-order: root 0, then the subtrees of its children if it splits, then root 1, and so on to root 11. A client walks the bits once when it loads the split table:

```ts
const leaves: { level: number; pixel: number; first: number }[] = [];
let at = 0;
function visit(level: number, pixel: number) {
	const split = (bits[at >> 3] >> (at & 7)) & 1;
	at++;
	if (split) for (let k = 0; k < 4; k++) visit(level + 1, 4 * pixel + k);
	else leaves.push({ level, pixel, first: pixel * 4 ** (10 - level) });
}
for (let root = 0; root < 12; root++) visit(0, root);
// at === row count of the split table
```

The leaves come out in cell order, so the tile of a cell is the last leaf whose `first` is not above the cell: a binary search on `first`. The tile is at `{slug}/{level}/{pixel}.bin.gz`.

The rows of a tile are sorted by ID, so a client finds a row by binary search on the `id` column. Each tile holds every column of its table; `metadata.json` lists them with their types.

### Metadata

Every live ID has a row. The ID is in the `id` column; there is no table number.

| Column | Type | |
|--------|------|-|
| `id` | id | |
| `name` | string | IAU proper name, else the English label of its Wikidata item when that is no bare catalogue number ("T Tauri", "Teegarden's Star", "Gliese 105"), else a Bayer or Flamsteed designation with the Greek letter spelled out ("Alpha Canis Majoris"), else `HD n`, `HIP n` or `Gaia DR3 n` |
| `name_source` | dict | the source of the name: `iau-wgsn`, `wikidata`, `hipparcos-2007` (designations from XHIP), `gaia-dr3` |
| `class` | dict | what the object is: `star` for every row now |
| `class_source` | dict | |
| `cross_ids` | cross_ids | every catalogue id of the object: catalogues `gaia/dr3`, `hip/2007`, `hd/1949`, `iau/wgsn`, `wikidata/qid` now. An object has at most one `wikidata/qid` id: of the items that reach one star, the item with the most articles in the site's languages keeps it, then the lowest QID |
| `mask` | uint32 | bit `n` is set when data table `n` has a row for the ID |
| `object` | bool | true when the site's object bundles hold an entry `x-<id>` for the ID ([objects.md](objects.md)): today, when it has a `wikidata/qid` id |
| `alias_target` | id | null for a live ID |

An alias is a row at the alias's own cell with only `id`, `mask` 0 and `alias_target`, which is the live ID at the end of its chain: a chain A → B → C is written A → C. A retired ID has no row, and its URL is a 404. An alias whose chain ends at an ID that is not live has no row either.

### Point source (table 1)

Gaia DR3 and Hipparcos, with every field and its uncertainty. The columns come in groups. Each group comes from one source, named in its `*_source` column; all columns of a group are null when no source has a value. Units: positions in degrees (ICRS at `epoch`, a Julian year: 2016.0 for Gaia, 1991.25 for Hipparcos), position errors in mas (`ra_error` on ra·cos dec), parallax in mas, proper motion in mas/yr (`pmra` on ra·cos dec), magnitudes in mag, radial velocity and broadening in km/s, temperature in K, `logg` in log(cm/s²), metallicity in dex, GSP-Phot distance in pc and radius in nominal solar radii (695,700 km), `nu_eff_used_in_astrometry` and `pseudocolour` in 1/µm. `*_lower` and `*_upper` are the 16th and 84th percentiles. `fidelity_v2` under 0.5 marks a likely spurious astrometric solution (Rybizki et al. 2022). `metadata.json` lists the columns in order.

`radius_gspphot` and its bounds come from Gaia DR3's `astrophysical_parameters`, joined to `gaia_source` by `source_id`; their provenance is `gspphot_source`. They are model estimates, not resolved measurements. Missing radii stay null. Close rendering uses the radius and `teff_gspphot` for a smooth, limb-darkened photosphere, with photometric colour as a fallback. Stars without a radius remain points. Existing exports need an extrasolar ingest and export before these columns are available.

## Lookup of an ID

For a URL `/x/{id}/{name}` or a click:

1. Load `metadata.json` once.
2. Check the ID: a bare decimal with no leading zero, under 2^53, with a cell under 12,582,912 and a table whose number `metadata.json` lists. Anything else is a 404.
3. Take `cell = id % 2^24` and `table = floor(id / 2^24) % 32`. The home table is the one with that `number`.
4. Load the split tables of Metadata and of the home table once each, and find the leaf of the cell in each.
5. Fetch the two tiles in parallel. Check the token in each header against `metadata.json`; a mismatch shows the reload prompt.
6. Find the ID in the Metadata tile by binary search. No row: 404.
7. A row with an `alias_target`: go on with that ID (redirect to its URL). The target is live, so there is at most one redirect.
8. Find the ID in the home tile. For each other bit `n` set in `mask`, fetch the tile of the same cell from table `n` in parallel and find the ID there.

Most objects have rows only in their home table, so a lookup is one round trip after the split tables.

## Milky Way render tree (`mw`)

An octree by visibility range for the objects of the Milky Way. It holds the stars of Point source with a distance.

- **Frame.** Positions are in parsecs, in ICRS equatorial axes, with the origin at the solar system barycentre, at epoch J2016.0: x to RA 0° Dec 0°, y to RA 90° Dec 0°, z to Dec +90°. The client rotates them to its own frame.
- **Root.** A cube with `half_size` 262,144 pc (2^18) from the centre to each face. Its `centre` is 87,381.33203125 pc on each axis (`half_size` / 3 to the nearest 1/256 pc), not the barycentre. So the Sun is about a third of a node from each face of its node at every depth, because 1/3 is 0.0101… in binary. With the root at the barycentre, the Sun would be on a corner of 8 nodes at every depth, and all of them would load from the solar system. The root holds from −174,762.67 pc to +349,525.33 pc on each axis, and every node centre is exact in float64.
- **Children.** Child octant `k` of a node has bit 0 set when it is on the +x side of the centre, bit 1 the +y side, bit 2 the +z side. Its centre is the parent's centre ± half/2 on each axis, and its half size is half of the parent's.
- **Names.** The root is `r`. A child adds its digit `k` (0 to 7) to the name of its parent: `r`, `r0` … `r7`, `r00` … The node is at `mw/node/{name}.bin.gz` and its IDs at `mw/id/{name}.bin.gz`. There is no index: the client knows the root and reads the children from each header.
- **Selection.** A node keeps the `node_rows` (10,000) objects with the largest visibility range of the objects in its box that no ancestor keeps, and passes the rest to its children. Ties go by the order of the Point source table. A node at depth 21 would keep all its rows. So every object of a child has a range no larger than the smallest range of its parent.
- **Rows.** In order of visibility range, the largest first, then by ID.

| Column | Type | |
|--------|------|-|
| `x`, `y`, `z` | float32 | position relative to the node's centre (pc) |
| `range` | float32 | visibility range (pc) |
| `mag` | float32 | absolute magnitude in Gaia G, a multiple of 1/1024 mag |
| `colour` | float32 | Gaia BP − RP (mag), a multiple of 1/1024 mag; NaN when unknown |
| `class` | uint8 | `1` star, from `classes` in `metadata.json` |

- **Visibility range.** For a light source, the distance at which its apparent magnitude reaches `range_limit_mag` (6.5): `range = 10 pc · 10^((6.5 − mag) / 5)`. A client that draws objects down to another limit `m` multiplies every range, in the files and the headers, by `10^((m − 6.5) / 5)`.
- **Loading.** The client loads the root. It loads child `k` of a loaded node when the distance from the camera to the child's box is at most `child_range[k]` (scaled as above). It can drop a node when the camera is farther than that from its box.
- **IDs.** The ID file of a node has the same token and row count as the node file. A client loads it on the first click in the node; row `i` of both files is the same object.
- **Precision.** A float32 position relative to the centre is off by up to half · 2^-24: about 13 AU for a star in a node of half size 1,024 pc, 0.8 AU in a node of half size 64 pc. A client that goes near one star takes its position from the star's record.

Which stars are drawn: `parallax / parallax_error > 5`, and `fidelity_v2 ≥ 0.5`, or no fidelity, or a Hipparcos match (`hipparcos_photometry_source` not null), and a magnitude. Positions are at J2016.0: Hipparcos stars are moved from J1991.25 by their proper motion. Distance is `1000 / parallax`. The absolute magnitude comes from `phot_g_mean_mag`, or for a star without Gaia photometry from the estimate of G from V and B − V that the ingest uses for matching (`g_estimate` of the Hipparcos source), with no correction for extinction. The colour is `phot_bp_mean_mag − phot_rp_mean_mag`, or for a star without Gaia colours BP − RP from the Hipparcos V − I (Riello et al. 2021, Table C.2: −0.01612 + 1.274 x − 0.08143 x², x = V − I from −0.5 to 3.5). A star without a distance has an ID and a record, but no render row.

## Sky cultures (`skycultures`)

The constellations and asterisms of the sky cultures, with their lines and the star names of each culture. One file per culture, at `skycultures/{key}.json.gz`. `skycultures` in `metadata.json` lists them, and the `dataset` of each says where it comes from: `stellarium` (Stellarium desktop's sky cultures) or `bucur` (Doina Bucur's constellation-lines dataset). Stellarium's international star names, which a culture with `fallback_to_international_names` falls back to, are in `skycultures/common_star_names.json.gz`, a file with names and no figures.

All files share one directory, so a key names one culture:

- A Bucur culture with the key of a Stellarium culture, in any case, is left out: Stellarium's wins.
- A Bucur culture that is a copy of a Stellarium culture under another key is left out. A copy shares at least half of its line segments with the Stellarium culture (Jaccard: shared segments over all segments of the two), and the Stellarium culture has at least half of its figure names (English or native, in any case). A Bucur culture that adds figures of its own shares less and stays.

The export logs each culture that it leaves out, with the reason and the two shares. The matched cultures of the ingest keep them all. In the export of 2026-10-24, three Bucur cultures are copies: `anuta` of `anutan` (0.78 of the segments, 0.81 of the names), `iau` of `modern_iau` (0.98, 0.99) and `romania` of `romanian` (0.83, 0.66). Each of their figures has a figure of the same name in the Stellarium culture, and the segments they do not share join other stars within those figures. No other Bucur culture shares more than 0.38 of its segments with a Stellarium culture.

A file is gzip around one JSON object:

```json
{
  "token": "495f0eea0c17aae7",
  "dataset": "stellarium",
  "key": "modern",
  "name": "Modern",
  "members": [
    { "id": 24592883, "position": [6.517253887958679, -11.840880957963618, 1.517162498208393] },
    { "id": 26486783 },
    { "ref": "DSO:M44", "reason": "deep-sky", "designation": "M44" },
    { "ra_hours": 19.43791, "dec": -23.807 }
  ],
  "figures": [
    {
      "id": "CON modern Aql",
      "kind": "constellation",
      "names": [{ "native": "Aquila", "english": "Eagle" }],
      "lines": [[0, 1, 2], [1, 3]]
    }
  ],
  "names": [{ "member": 0, "names": [{ "native": "Altair", "english": "Altair" }] }]
}
```

- **`members`.** Each object that a figure or a star name points to, once, in order of first use. It is one of:
  - a star: `id` is its extrasolar ID, and `position` its position in parsecs, in the frame of the render tree (ICRS axes, origin at the barycentre, J2016.0), as float64. The position is the one that the tree build computes for the star, from the same code over the same rows, so a line ends on the rendered star: it is the float64 value that the node stores as the node's centre plus a float32 offset. A star that the tree does not draw (no 5-sigma parallax, a flagged fidelity, no magnitude) has an `id` and no `position`.
  - an object with no ID: `ref` as the source writes it, `reason` (below), and `designation` for a deep-sky object or a planet. A line that passes through it keeps its index, so no line is cut; a client skips the segments to a member without a position.
  - a point of the sky that a Stellarium figure gives in place of a star: `ra_hours` and `dec` (degrees) as published. It has no distance.
- **`figures`.** `kind` is `constellation` or `asterism`. `names` lists the names of the figure, each with the fields that the source gives of `native` (in the culture's script), `english`, `pronounce`, `transliteration` and `IPA`. `lines` is a list of chains; each chain is a list of member indexes, joined in order. A Bucur figure can have `group`, member indexes of a star group with no lines, and `iau`, the IAU constellation that holds a figure whose stars are not known. A Stellarium asterism with `ray_helper` is a line that helps find stars (a pointer), which Stellarium draws apart from the figures.
- **`names`.** The star names of the culture: `member` is a member index, and `names` lists its names with the same fields as a figure's.

| `reason` | |
|----------|-|
| `deep-sky` | a cluster, nebula or galaxy; the registry has no deep-sky objects yet |
| `solar-system` | the Sun, the Moon or a planet |
| `not-in-registry` | a HIP, Gaia DR3 or HD number with no live ID: not in Hipparcos 2007, or a Gaia source with no 5-sigma parallax |
| `component` | a component letter other than A after a HIP number |
| `not-in-simbad` | SIMBAD has no object with this identifier |
| `no-star-number` | a SIMBAD star with no HIP, Gaia DR3 or HD number |
| `unknown-designation` | a designation of no known form |

The matching runs at ingest: the `extrasolar` target of `space-map-ingest` ends with it, and `--targets skycultures` runs it alone. A HIP number goes through the registry's `hip/2007` catalogue ids and a Gaia DR3 source_id through `gaia/dr3`. Bucur names stars by SIMBAD identifier; SIMBAD gives the star's HIP number, else its Gaia DR3 or HD number, else the HIP number of the star system that holds it.

The token of `skycultures` covers all its files: SHA-256 over each file's path, a zero byte and the SHA-256 of its JSON with `token` set to 16 zeros (`"0000000000000000"`), as for the containers. Each file's `token` field holds the token; a client checks it as it checks a container header.

## `metadata.json`

```json
{
  "format": 1,
  "exported": "2026-10-23T08:45:48+00:00",
  "registry": { "ingest": 2, "host": "tycho" },
  "tables": {
    "metadata": {
      "number": null,
      "token": "fff783096c2f5daf",
      "split": "metadata/split.bin.gz",
      "tile": "metadata/{level}/{pixel}.bin.gz",
      "max_rows": 7500,
      "rows": 180949689,
      "tiles": 52206,
      "columns": [{ "name": "id", "type": "id" }, { "name": "name", "type": "string" }, "…"],
      "distribution": "non-commercial"
    },
    "point-source": { "number": 1, "…": "…" }
  },
  "trees": {
    "mw": {
      "token": "dba0e081a896895f",
      "root": "mw/node/r.bin.gz",
      "node": "mw/node/{name}.bin.gz",
      "ids": "mw/id/{name}.bin.gz",
      "centre": [87381.33203125, 87381.33203125, 87381.33203125],
      "half_size": 262144,
      "node_rows": 10000,
      "range_limit_mag": 6.5,
      "units": "pc",
      "frame": "ICRS equatorial axes, origin at the solar system barycentre, epoch J2016.0",
      "classes": { "star": 1 },
      "nodes": 61487,
      "depth": 14,
      "rows": 180923672,
      "columns": [{ "name": "x", "type": "float32" }, "…"],
      "id_columns": [{ "name": "id", "type": "id" }],
      "distribution": "non-commercial"
    }
  },
  "skycultures": {
    "token": "495f0eea0c17aae7",
    "file": "skycultures/{key}.json.gz",
    "international_names": "skycultures/common_star_names.json.gz",
    "international_names_distribution": "non-commercial",
    "units": "pc",
    "frame": "ICRS equatorial axes, origin at the solar system barycentre, epoch J2016.0",
    "commits": { "stellarium": "0d956aacee305c29a92498860bc394ed21e0e731", "bucur": "711e06943f342e9340807885016b4ea14e2fe45e" },
    "cultures": [
      {
        "dataset": "stellarium",
        "key": "modern_chinese",
        "name": "Modern (Chinese)",
        "region": "Eastern Asia",
        "subregion": null,
        "packaged": true,
        "fallback_to_international_names": false,
        "file": "skycultures/modern_chinese.json.gz",
        "licence": {
          "parts": [{ "applies_to": "data", "licence": "CC BY-SA 4.0" }, { "applies_to": "illustrations", "licence": "Free Art License" }],
          "distribution": "open"
        },
        "distribution": "non-commercial",
        "flags": [],
        "credit": { "name": "Modern (Chinese)", "organisation": "Stellarium", "source": "https://github.com/Stellarium/stellarium/tree/0d956aa…/skycultures/modern_chinese", "license": "CC BY-SA 4.0 (data); Free Art License (illustrations)", "authors": ["Sun Shuwei"] },
        "figures": 415,
        "members": 3131,
        "positioned": 3095,
        "unresolved": 11
      },
      "…"
    ],
    "credits": [{ "name": "Stellarium sky cultures", "…": "…" }, { "name": "Constellation line figures in sky cultures across the world", "…": "…" }, { "name": "SIMBAD astronomical database", "…": "…" }]
  },
  "credits": [
    { "name": "Gaia Data Release 3", "organisation": "ESA/Gaia/DPAC", "source": "https://www.cosmos.esa.int/web/gaia/dr3", "license": "CC BY-NC 3.0 IGO", "attribution": "…", "citation": "…" },
    "…"
  ]
}
```

- `tables`: keyed by slug. `number` is the table number in the IDs, null for Metadata. `max_rows` is the split threshold. `rows` counts the rows of all tiles.
- `trees`: keyed by name; `mw` is the Milky Way.
- `distribution`: who may serve the data, with the meaning that it has on a texture ([textures.md](textures.md)). Gaia DR3 is CC BY-NC 3.0 IGO, and every table and tree holds Gaia values, so all are `non-commercial`.
- `credits`: each source with `name`, `organisation`, `source` (URL), and `license`, `attribution` and `citation` when known: Gaia DR3, Rybizki et al. 2022, Hipparcos I/311 and I/239, XHIP V/137D, the IAU Catalog of Star Names, Wikidata.
- `skycultures`: absent when the export had no matched cultures. `file` is the path pattern, and `cultures` lists each culture with its file:
  - `licence`: the licence of the culture's data and illustrations as it states it (`applies_to` is `all`, `data` or `illustrations`; the files hold no illustrations yet), and the tier that this licence alone allows. A culture that states no licence has no parts and the tier `non-commercial`, with the flag `no-licence`. A statement that the ingest cannot read gives the tier `undecided`, which no client may serve.
  - `distribution`: the tier of the file, the strictest of the culture's licence and of Gaia DR3 (`non-commercial`), because the positions come from Gaia. `undecided` stays `undecided`.
  - `flags`: `no-derivatives` (a CC ND licence: only unchanged copies), `non-commercial` (a CC NC licence or a Traditional Knowledge NC label), `tk-labels` (Traditional Knowledge labels add terms to the licence), `no-licence` (the culture states no licence, so it is non-commercial), `unknown-licence`.
  - `packaged`: false for a culture that Stellarium leaves out of its standard package.
  - `credit`: the culture's own credit: its source at the pinned commit, its licence, and for Stellarium `authors`, the plain names of the people that the culture's description names as its makers, with no Markdown, addresses or links.
  - `figures`, `members`, `positioned` (members with a position) and `unresolved` (members with no ID, sky points left out).
  - `credits` of the section: Stellarium, Bucur's dataset and SIMBAD, which matched Bucur's identifiers.

## Sizes

The export of 2026-10-23 (registry ingest 2, 180,949,689 IDs, all live):

| Part | Files | Size | Median file | p90 | Max |
|------|-------|------|-------------|-----|-----|
| Metadata tiles (`max_rows` 7,500) | 52,206 | 4.3 GB | 73 kB, 3,063 rows | 133 kB | 175 kB |
| Point source tiles (`max_rows` 900) | 437,445 | 32.7 GB | 64 kB, 349 rows | 125 kB | 162 kB |
| Split tables | 2 | 1.7 kB and 11.6 kB (69,604 and 583,256 bits) | | | |
| Render nodes | 61,487 | 2.8 GB | 24 kB, 1,372 rows | 141 kB | 160 kB |
| Render IDs | 61,487 | 0.63 GB | 5 kB | 34 kB | 42 kB |

The sky cultures of registry ingest 4 (Stellarium at `0d956aa`, Bucur at `711e069`): 101 culture files (64 from Stellarium, 37 from Bucur) and the international names, 1.76 MB together. The median culture file is 3.7 kB; the largest are `chinese` (166 kB, 312 figures, 3,079 members) and `modern_chinese` (141 kB). 4,820 of the 4,864 stars of all cultures have a position.

A full render node of 10,000 stars is about 143 kB, of which the float32 positions take about 107 kB. 180,923,672 stars are in the tree, at depths 0 to 14. A plain octree gives 61,487 nodes against a minimum of 18,093; 7,761 nodes are full and 26,246 hold under 1,000 rows.

With a limit of 7.5 mag, a client at the barycentre loads 59 nodes and 581,094 stars by the loading rule above. At 10 pc from it, it loads 57 to 62 nodes, and at 1 kpc, 22 to 47 nodes (0.21 M to 0.45 M stars), depending on the direction.

## Checks before the files go live

The export builds into `v1/.x-staging/` and replaces `v1/x/` only when all checks pass:

- no ingest of the registry has merges that no one has reviewed (`space-map-extrasolar review`);
- every row holds an ID that the registry has, with the status that the row shows (live, or alias for an alias row), and every alias target is live;
- every ID that the previous export serves is still served with all its catalogue ids, or is an alias or retired in the registry. The `wikidata/qid` ids are not checked: each ingest links the Wikidata items again, so an item can move to another star. The previous export stands for the live site until the serving is decided;
- the matched sky cultures come from the registry ingest that the export reads. Each extrasolar ingest matches them at its end, so this fails only when that step failed; `space-map-ingest --targets skycultures` matches them again.

A failed run leaves the served export as it was.

The export holds a shared lock on `registry/lock` for the whole run, and an ingest holds the same lock exclusively. So an export does not start while an ingest runs, an ingest does not start while an export runs, and every file comes from the registry state that `registry` in `metadata.json` names.
