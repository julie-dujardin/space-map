# Extrasolar objects (`v1/x/`)

The objects outside the solar system: their record tiles, one tree per table, the Milky Way render tree, the constellation figures of the sky cultures, and the exoplanets with one file per planetary system. The star systems are a table of their own: a binary is a system of two, and the pairs inside a system are systems too. `space-map-export --only extrasolar` builds them from the extrasolar registry and its tables. They are not part of the main export: the stars alone are over half a million files, and the host of the main export has a file limit. They are written to `space-map-extrasolar/v1/x/` and are served from their own base URL, `PUBLIC_EXTRASOLAR_URL`. Without that URL a client has no stars and no `/x/` pages.

An object has one ID for all its files. The ID, its URL form and its check are in the design of the registry: `id = serial·2^29 + table·2^24 + cell`, with `cell` the HEALPix level-10 nested cell (ICRS) and `table` the home table. A client decodes it with division, never with bit operators: `cell = id % 2^24`, `table = floor(id / 2^24) % 32`, `serial = floor(id / 2^29)`.

## Directory structure

```
v1/x/
  metadata.json                          (not gzipped) entry point: format, tokens, tables, trees, credits
  families.json                          (not gzipped) the brightest stars of each family, for the main export; clients do not read it
  metadata/split.bin.gz                  split table of the Metadata tiles
  metadata/{level}/{pixel}.bin.gz        Metadata record tiles
  point-source/split.bin.gz              split table of the Point source tiles
  point-source/{level}/{pixel}.bin.gz    Point source record tiles (table 1)
  binary-orbit/split.bin.gz              split table of the Binary orbit tiles
  binary-orbit/{level}/{pixel}.bin.gz    Binary orbit record tiles (table 2)
  system/split.bin.gz                    split table of the System tiles
  system/{level}/{pixel}.bin.gz          System record tiles (table 3): the star systems
  mw/node/{name}.bin.gz                  Milky Way render nodes
  mw/id/{name}.bin.gz                    the ID column of each render node
  skycultures/{key}.json.gz              a sky culture: figures, members and star names
  skycultures/stars/{shard}.json.gz      the figures of each star, in every culture
  planets/index.json.gz                  every planet host: its system, planet numbers, place and outer orbit
  planets/{key}.json.gz                  one planetary system: its hosts and planets, with orbits in the scene's frame
  systems/index.json.gz                  the star systems that a page draws up close, with their held stars
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
| 15 | `uint64` | `n` values | `BigUint64Array`: exact integers past 2^53, as BigInt |
| 16 | `float32_list` | offsets (`n + 1` × uint32), values (`m` × float32) | row `i` is values `offsets[i]` to `offsets[i + 1]`: `values.subarray(offsets[i], offsets[i + 1])` |
| 17 | `list` | offsets (`n + 1` × uint32) | row `i` is items `offsets[i]` to `offsets[i + 1] − 1` of its item columns (below) |

A `list` column holds only the item offsets of its rows; `m = offsets[n]` is its item count. Its items are the columns that follow it in the directory, named with a dot after its name: `<list>.<field>` for each field of a struct item (`members.id`, `members.kind`, …), or `<list>.item` for a list of plain values (`sources.item`). An item column is a column of any type with `m` rows, and has its own validity bitmap of `ceil(m / 8)` bytes. It can be a `list` in turn: `members.known` lists the words of each member, in `members.known.item`. A client reads an item column with the reader of its type, at item rows: the members of row `i` are rows `offsets[i]` to `offsets[i + 1] − 1` of `members.id`, `members.kind` and the other `members.` columns. A null row has no items. `metadata.json` lists the item columns after their list, in file order.

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

Each table and each tree has a token: the first 16 hex digits of SHA-256 over, for each of its files sorted by path, the path relative to `v1/x/`, a zero byte and the SHA-256 of the payload with the token field set to zeros. The split table is one of the files of its table, and the ID files are files of their tree. `metadata.json` and `families.json` are not in any token.

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
| `name` | string | IAU proper name (the WGSN list, which holds the NameExoWorlds star names; a NameExoWorlds star name outside that list comes with the host rows), else for a planet host the name in its exoplanet catalogue, else the English label of its Wikidata item when that is no catalogue number ("T Tauri", "Teegarden's Star", "Gliese 105"), else a Bayer or Flamsteed designation with the Greek letter spelled out ("Alpha Canis Majoris"), a WR number, a GCVS name, the designation of the star system that the star alone stands for (a SIMBAD system with one point), `HD n` or `HIP n` (the star's, else those of the system whose primary it is, within 10″), a SIMBAD NAME, a designation in a cluster where SIMBAD's main identifier is from a survey, SIMBAD's main identifier, a Wikidata label that is a catalogue number (HD, HR, HIP, BD, CD, TYC, UCAC, 2MASS, IRAS and the like: "2MASS J03140344+1603056", `name_source` `wikidata`), or `Gaia DR3 n`. A Wikidata label that is a Gaia id or a SIMBAD identifier names nothing. A star with a Gaia DR3 id takes `Gaia DR3 n` over a main identifier from a survey (2MASS, Tycho, UCAC, WISE …). A name has no SIMBAD prefix: no `NAME` and no object type (`V*`, `**`, `EM*`, `Cl*`). Where the object type is the whole catalogue acronym (`C* 2905`), the identifier keeps it. A resolved star system (System, below) takes the label of the Wikidata item about it, else SIMBAD's designation of the system object without a component letter ("Alpha Centauri", "Castor"), else `WDS J<WDS id><letters>`, else none: a client then composes a name from its primary. A point keeps its own name. An IAU name is the component's that the WGSN list names: Castor is the point that holds Castor Aa and Ab |
| `name_source` | dict | the source of the name: `iau-wgsn`, `nasa-exoplanet-archive`, `exoplanet-eu`, `open-exoplanet-catalogue`, `wikidata`, `star-systems` (a resolved system's name from its trees), `simbad`, `hipparcos-2007` (designations from XHIP), `hipparcos-1997`, `gaia-dr3`, `gaia-dr3-named` |
| `class` | dict | what the object is: `star`, `white dwarf`, `brown dwarf` or `pulsar`, and for a node of a star system, point or resolved, `binary star` (two stars below it) or `multiple star` (three or more). A node is always `binary star` or `multiple star`, also a point that a catalogue calls a white dwarf, brown dwarf or pulsar: its members tell what its objects are. Any other object takes a specific class from any source first (`white dwarf`, `brown dwarf`, `pulsar`), then `star`, so the default `star` of one source never replaces the specific class of another. A point that holds one object keeps the class of that object |
| `class_source` | dict | the source of the class, in source order within each step of `class`: `star-systems` (the class of a node), the exoplanet catalogues, `simbad` (its object type: `WD*` is a white dwarf, `BD*` a brown dwarf; the candidate types `WD?` and `BD?` give no class), `gaia-dr3`, `hipparcos-2007`, `hipparcos-1997`, `gaia-dr3-named` |
| `system` | id | the root of the ID's star system, for every node but the root and every star of a system; null for a root and for an ID in no system. A client finds the whole system in the root's System row |
| `planets` | list | the planet records that a brown dwarf also is (System, below), each as `<host>/b/<number>`, its page below `/x/`; null for any other ID. A point that holds a pair of brown dwarfs can have two |
| `cross_ids` | cross_ids | every catalogue id of the object: catalogues `gaia/dr3`, `hip/2007`, `hd/1949`, `simbad/oid`, `iau/wgsn`, `wikidata/qid`, `literature/star`, on a star that the WDS gives by position only `wds/component` (`<WDS id> <letter>`; never on the object of a WDS node that holds it, or of a component near it in its WDS system, such as the point that holds its pair), on a star that the MSC gives by position only `msc/component` (alike), and on a resolved star system its catalogue ids under the catalogue `star-system`, with the catalogue of the id as the release: `star-system/msc` (`14396-6050 AB`), `star-system/wds` (`14396-6050` or `14396-6050 AB`), `star-system/simbad` (the oid of SIMBAD's system object, such as `* alf Cen`), `star-system/el-badry` (the pair, `<source_id>+<source_id>`), and for a system that no catalogue names `star-system/primary` (`<catalogue>/<release>/<id> <rank>`: an id of its primary, and the number of resolved systems of that primary inside it, 0 for the innermost). A star never has a `star-system` id, so the row of a star never takes the ID of a system. A resolved system keeps its ID from one ingest to the next by these ids. An object has at most one `wikidata/qid` id. The classes of an item (P31) tell what it is about: a star, a system, both, or neither; a class that is a kind of star and of star system, such as an eclipsing binary, counts as a star class. Of the items that reach one object, an item about a star wins, then one about neither, then one about both, then one about a system; then the claim by HIP, Gaia DR3 and HD, in this order; then the most articles in the site's languages; then the lowest QID. An item about a star stays on its star. Any other item goes to the node of its system that its ids name (SIMBAD's system object of its HIP or HD number), else to the root of the system of its star, when that node has no item of its own; an item about neither stays on its star when its ids name no node, also when it loses the star to an item that goes to a node and no better item stays on the star. These items stay where their claim leads: the winner of a point that holds several stars, an item whose label names a component ("Alpha Centauri B"), and on a star in no system an item about both or about a system only, until a source gives the star's system (Mira, typed only binary star, with no Mira B in the trees). An item that finds its node taken stays on its star when it is about both and the star has no item, else it is left off. A `literature/star` id is the key of the star in the literature table of the repo (`constants/stars/literature.py`): `gaia/dr3/<source_id>`, `hip/2007/<n>` or `hd/1949/<n>` |
| `mask` | uint32 | bit `n` is set when data table `n` has a row for the ID: bit 3 for a node of a star system |
| `object` | bool | true when the site's object bundles hold an entry `x-<id>` for the ID ([objects.md](objects.md)): today, when it has a `wikidata/qid` or a `literature/star` id |
| `alias_target` | id | null for a live ID |
| `families` | uint64 | the published families of the star: bit `n` is entry `n` of `families` in `metadata.json` (below); 0 for a node of a star system |
| `families_estimated` | uint64 | the families that need an estimate (a Gaia DR3 estimate or the class of a candidate) and are not in `families`; 0 for a node of a star system |
| `spectral_type` | string | the MK spectral type that the families read (Families, below): the first of `simbad_sp_type`, `simbad_system_sp_type`, `sp_type` and `host_spectral_type` of the Point source row that holds, or the `star.spectral_type` of a held star; null where none holds, for a node of a star system and for any other row without a Point source row |

An alias is a row at the alias's own cell with only `id`, `mask` 0 and `alias_target`, which is the live ID at the end of its chain: a chain A → B → C is written A → C. A retired ID has no row, and its URL is a 404. An alias whose chain ends at an ID that is not live has no row either.

#### Families

The export computes the two family masks from the Point source row and the Metadata class of a star; the rules are in `constants/stars/families.py`. A star is in every family that its data supports, and a family adds its parents (a G-type main-sequence star is also `main-sequence` and `dwarf`). Every family is below the root family `classification` (stellar classification), so a star with a published family has it in `families`, and a star with only estimated families has it in `families_estimated`. A node of a star system, point or resolved, is no star. It has 0 in both and a null `spectral_type`, also when a catalogue gives its point a type. Its stars have the families. A held star has no Point source row, so its `star.spectral_type` is its MK spectral type. That type and the Metadata class go through the same rules, and the rules that read other Point source columns give nothing. A star with its own point reads its Point source row. Any other row without a Point source row, such as an alias, has 0 in both. The export writes the MK type that the rules read as `spectral_type`, so a client shows the type that gives the families. A client reads a mask as a `BigUint64Array` and tests bit `n` with `(mask >> BigInt(n)) & 1n`.

A published family comes from catalogued classifications only:

- the MK spectral type, the first of `simbad_sp_type`, `simbad_system_sp_type`, `sp_type` (Hipparcos) and `host_spectral_type`. The letter and the luminosity class give the family (`K2 III` is `giant` and `red-giant`, `M4 V` is `red-dwarf`); a composite type gives its first star. A class without a luminosity class gives only the families of its letter: D (`white-dwarf`), W (`wolf-rayet`), C, R and N (`carbon-star`), S, MS and SC (`s-type-star`), L, T and Y. A white dwarf has no luminosity class: the V of `DAV` marks a pulsating star. `K5+III` is K5 III, SIMBAD's `G2_0` is class 0, `F(6)V` is F6 V and `ON8.5V` is O8.5 V. An Am type gives its hydrogen type: `kA2hA5mA7V` is A5 V. Where only one type comes before the metal type, that type is the hydrogen type: `A0mA1Va` is A0 Va. `Ba` after an F to M type marks a `barium-star`. The star-system trees use the same type;
- `simbad_otype`, `simbad_system_otype` and `host_simbad_otype`, one listed code each (`Mi*` is `mira-variable`, `Psr` is `pulsar`); a candidate type gives an estimate only (below). A stage that the object type gives joins the MK letter as a luminosity class does (`K0` with `MS*` is `k-type-main-sequence`);
- the Metadata class `white dwarf`, `brown dwarf` or `pulsar`;
- `vartype_gcvs`, the GCVS type: UV or UVN, alone, with a subtype in brackets (`UVN(YY)`) or in a combined type (`UV+BY`), is `flare-star`; a type with `:` is uncertain and gives none (`UV:`);
- `type_atnf`, the ATNF pulsar type: the code `AXP`, ATNF's code for a magnetar (an anomalous X-ray pulsar or a soft gamma-ray repeater), is `magnetar`, alone, with its reference in brackets (`AXP[esy+20]`) or among other codes (`AXP,NRAD`); a code with `(?)` is uncertain and gives none (`NRAD,AXP(?)`).

A white-dwarf type in `simbad_system_sp_type` or `simbad_system_otype` gives nothing to a star with BP − RP over 1.4 and `classprob_dsc_combmod_whitedwarf` not over 0.5. In a pair of a white dwarf and an M dwarf, the M dwarf is often the brighter star (`PG 1210+464A`, BP − RP 1.79). Of the catalogued white dwarfs, 1% have BP − RP over 1.4.

Where the object type (or the object type `WD*`, `BD*` or `Psr` of the Metadata class) and the MK class give stages that cannot both hold, the source that independent evidence finds right more often wins, and the stage families of the other source are dropped (an object type keeps `variable-star`). A rule covers some MK letters only where the evidence differs by letter. The evidence is M_G against the main sequence of Mamajek (version 2022.04.16) at the star's BP − RP, both corrected with the extinction of GSP-Phot; the spectroscopic log g of APOGEE, GSP-Spec, LAMOST or ESP-HS; and the CatWISE W1 − W2 excess. For a pre-main-sequence type, the share of stars that are over-luminous (M_G more than 1 mag above the main sequence) or have a W1 − W2 over 0.3 is compared with that of MK stars of the same class and letters without such a type; the share above that background is the share of pre-main-sequence stars. The object type wins:

- `HB*`, `RG*` and `RR*` over V and IV: of the stars with evidence, 222 of 227 `HB*` and 181 of 183 `RG*` with V, 431 of 438 `RG*` and 192 of 195 `HB*` with IV, and 14 of 16 `RR*` with V are evolved (log g under 3.5, or M_G more than 2.5 mag above the main sequence);
- `HB*`, `RG*`, `RR*`, `AB*`, `Mi*` and `WV*` over I and 0: these are low-mass giants, often in globular clusters, and 31 of 35 with M_G are fainter than −3.5;
- `Or*` and `TT*` over V for F to M: 69% of these `Or*` stars and 64% of these `TT*` stars are pre-main-sequence stars;
- `Ae*` over V for B to M (64% for B, 52% for A, 81% for F to M) and over IV for A (64% of 6 stars);
- `BD*` over V for L3 and later, T and Y: from L3 on, a field dwarf is a brown dwarf (Dieterich et al. 2014, AJ 147, 94), and its V marks the gravity. 53 of the 111 `BD*` stars with V are of these types;
- `WR*` over an O or B first star that has a WN class too (`Ofpe/WN9`, `O2If*/WN5`, `O2If*-WN6`, `O2.5If*/WN6+OB`): these are Wolf-Rayet stars of a late WN type (Crowther & Smith 1997; Crowther & Walborn 2011). 28 of the 43 `WR*` stars with an O or B first star have one.

The MK class wins:

- over `Y*O` with V or IV for B to M: 44% (B), none (A) and none (F to M) of the stars with V are pre-main-sequence stars, and at most 10% of those with IV;
- over `Or*` with V for B and A: 45% and 32%;
- over `Or*` and `TT*` with IV for F to M: the background is MK class IV, because a subgiant is over-luminous too. 2% of these `Or*` stars and none of these `TT*` stars are pre-main-sequence stars;
- over `Y*O`, `Or*`, `TT*` and `Ae*` with III to 0: 26 of the 28 O and B stars are more than 1 mag over the main sequence, and 5 of the 7 A to M stars with a log g are giants;
- over `s*b` with II or III: 6 of the 7 stars with M_G are fainter than −5.

Other pairs are both true (`HB*` with III, a Cepheid with I, `BD*` with an L type) or have too little evidence, and keep the families of both: `AB*`, `Mi*` and Cepheids with V (5 stars for MK, 3 for the object type); `BD*` from M7 to L2 with V (58 stars), where the stars and the brown dwarfs meet; pre-main-sequence types of O stars, where the test does not work (the O stars without such a type are over-luminous against the Mamajek sequence too), and letter groups of fewer than 5 stars with evidence; `WR*` with an O or B first star without a WN class (`O3If*`, `B0I+WN`).

An estimated family uses at least one estimate:

- the SIMBAD candidate type `BD?` (`brown-dwarf`) or `WD?` (`white-dwarf`) in `simbad_otype` or `host_simbad_otype`. A `BD?` star with a Gaia M_G under 13 gets none: all 244 `BD*` stars with a parallax are fainter (M_G 13.9 and over), and the 5 `BD?` stars with a G magnitude and a 5σ parallax are brighter (M_G 7.6 to 12.0). M_G comes from a 5σ parallax, else from `distance`, else from `host_distance`: OGLE-2012-BLG-0358L, at 1,760 pc in its exoplanet catalogue, has M_G 6.5. A `WD?` star gets none where Gaia finds it red and not a white dwarf, as for the white-dwarf type of a system (above); none of the 6 `WD?` stars with a colour is. 5 of the 6 `WD?` stars with a colour lie on the white-dwarf sequence;
- the spectral type tag `spectraltype_esphs`, where the second digit of `flags_esphs` is 1 to 4, and 1 for O and B: against catalogued MK letters, 1 agrees for 72–96% of the stars and 5 for 33–53%. O, B and A count only where `in_oba_golden_sample` is true. `CSTAR` counts only with the digit 0, which marks the carbon stars that the validation confirmed;
- the stage of an O or B star (published or estimated letter) from ESP-HS: `main-sequence` where `logg_esphs` is from 3.5 to 4.5, `giant` below 3.5. 3.5 is the lowest log g of the main sequence in the MIST v1.2 solar tracks with rotation (3.41 to 3.55 from 7,500 to 30,000 K). Above 4.5 there is no stage: the MIST main sequence stops at 4.33, and of the O and B stars with an MK class above 4.5, fewer than half are on the main sequence (the others are mostly hot subdwarfs and white dwarfs). ESP-HS gives supergiants the log g of giants, so a supergiant can have the `giant` stage. `teff_esphs` must be in the range of the letter's ESP-ELS tag (Creevey et al. 2023, A&A 674, A26, Table A.1): 9,790 to 30,000 K for B. O goes from 22,500 to 50,000 K (the hottest ESP-HS spectra): ESP-HS fits O stars too cool, and 95% of the MK O stars with ESP-HS values are over 22,500 K (76% over 30,000 K, the edge of the O tag). An emission-line star has no stage, because its emission lowers its log g: `classlabel_espels` `beStar`, `simbad_otype` or `simbad_system_otype` `Be*`, `Be?`, `Em*`, `Ae*` or `Ae?`, or an `e` after the first star of one of the MK types (`B2Ve`, `B(0/3)ne`, `B5+IIIe`). With an MK class V, 33% (`Em*`) to 58% (`beStar`) of these stars have a log g under 3.5, against 6% of the other O and B stars. Against catalogued MK classes, the main-sequence stage is right for 68% of the B stars and 72% of the O stars, the giant stage (classes III to I) for 80% and 76%. FLAME gives these stars no stage. Its models stop at 10 M☉, and its GSP-Phot temperature is too low for hot stars. A star whose O or B tag fails its quality check has no letter, and FLAME gives its stage: on such stars with an MK class, FLAME and ESP-HS give the right stage equally often (62%);
- the FLAME stage of the other stars, from `flame_spec` before `flame`, where the fit holds as the star panel shows it: a mass, and for a giant (first flag digit 1) a mass from 1 to 2 M☉. Below 420 is `main-sequence`, below 490 `subgiant`, then `giant`;
- `classprob_dsc_combmod_whitedwarf` over 0.5 (`white-dwarf`);
- `classlabel_espels`: `TTauri`, `HerbigStar`, `RedDwarfEmStar` (`red-dwarf`), `wC` and `wN` (`wolf-rayet`);
- `class_spicy`: `ClassI` and `FS` (flat spectrum) are `protostar`. SPICY lists candidates.

Of two of these labels that state the same, the first of the candidate type, `classlabel_espels`, `classprob_dsc_combmod_whitedwarf` and `class_spicy` counts: a SPICY protostar with the ESP-ELS label `TTauri` is an estimated `t-tauri`. SIMBAD types a star with both as a pre-main-sequence star (`Y*O`, `Or*`, `TT*`, `Ae*`) or gives it no stage.

Each family states the spectral letter of a star, its stage, both or neither. A published family or MK value stops each estimate of what it states: a star typed `K2 III` gets no estimated letter or stage, and a star typed `K0` can get an estimated stage. An estimate joins the published value of the other: `MS*` with the Gaia tag K is an estimated `k-type-main-sequence`. A variable star states neither, so it stops nothing.

### Point source (table 1)

Gaia DR3, Hipparcos, SIMBAD, the literature table, the distance catalogues, the metallicity catalogues, the class catalogues and the host stars of the exoplanet catalogues, with every field and its uncertainty. The columns come in groups. Each group comes from one source, named in its `*_source` column; all columns of a group are null when no source has a value. Units: positions in degrees (ICRS at `epoch`, a Julian year: 2016.0 for Gaia, 1991.25 for Hipparcos, 2000.0 for SIMBAD), position errors in mas (`ra_error` on ra·cos dec), parallax in mas, proper motion in mas/yr (`pmra` on ra·cos dec), magnitudes in mag, radial velocity and broadening in km/s, temperature in K, `logg` in log(cm/s²), metallicity in dex, GSP-Phot distance in pc, radii in nominal solar radii (695,700 km), FLAME luminosity in nominal solar luminosities (3.828 × 10²⁶ W), mass in solar masses, age in Gyr, gravitational redshift in km/s and bolometric correction in mag, `nu_eff_used_in_astrometry` and `pseudocolour` in 1/µm. Except for distance, whose percentiles are explicit columns, `*_lower` and `*_upper` are the 16th and 84th percentiles. `fidelity_v2` under 0.5 marks a likely spurious astrometric solution (Rybizki et al. 2022). `metadata.json` lists the columns in order.

A planet host also has the group `host_star`, the star as its exoplanet catalogue gives it (`host_star_source`: `nasa-exoplanet-archive`, else `exoplanet-eu`, else `open-exoplanet-catalogue`): `host_name`, `host_distance` and `host_distance_error` (pc, the larger of the two errors), `host_teff` (K), `host_radius` and `host_mass` (solar), `host_metallicity` (dex), `host_logg` (cgs), `host_age` (Gyr), `host_v_mag`, `host_g_mag`, `host_k_mag` (mag), `host_spectral_type` and `host_simbad_otype` (the SIMBAD object type of the host's SIMBAD object from the exoplanet name resolution; the star families read it as they read `simbad_otype`). Every other star has nulls there. A host that no other catalogue gives is a literature star. A host with no Gaia DR3 id or HIP number claims its SIMBAD object when that object has a row and no other host holds it. The host and the row are then one star, which keeps SIMBAD's astrometry group and the `host_star` group. Any other host without a Gaia or Hipparcos row takes its astrometry group from the exoplanet catalogue (`astrometry_source`), before SIMBAD, with RA, Dec, parallax and proper motion as the catalogue gives them and epoch 2015.5 for the archive (its positions are Gaia DR2's) or 2000.0 for exoplanet.eu and OEC. A planet host can also take its Metadata name and class from these catalogues (`name_source`, `class_source`); a literature star's class is `star`, `brown dwarf`, `white dwarf` or `pulsar`.

`radius_gspphot` and its bounds, and the `flame` group, come from Gaia DR3's `astrophysical_parameters`, joined to `gaia_source` by `source_id`. They are model estimates, not resolved measurements, and stay null where Gaia has none. FLAME (Creevey et al. 2023, A&A 674, A26) derives the luminosity from G, `ag_gspphot`, the bolometric correction `bc_flame` and the parallax or the GSP-Phot distance, and the radius from the luminosity and `teff_gspphot`. The mass, the age and `evolstage_flame` come from BaSTI tracks with a solar metallicity, so the age is biased for stars outside −0.5 < [M/H] < +0.5. `evolstage_flame` counts the phases of the BaSTI tracks from 100 at the zero-age main sequence: main sequence below 390, turn-off from 390, subgiant from 420 and giant from 490, where Gaia flags nearly every star as a giant. The tracks end near 1300 at the tip of the red giant branch, but a few values run up to about 1770, and stars without a mass have a stage as well. `flags_flame` is as published. Its first digit is 0, 1 for a giant, whose mass Gaia trusts only from 1 to 2 M☉, or 2 where FLAME gives no mass or age. Its second digit is 0 or 2 where the luminosity rests on the parallax, 1 where it rests on `distance_gspphot`.

The `flame_spec` group is FLAME's second run, on the temperature, gravity and metallicity that GSP-Spec measured on the RVS spectra. It comes from `astrophysical_parameters_supp`, holds about 5 million stars, and has the columns of `flame` with `_spec` added (`radius_flame_spec`, `radius_flame_spec_lower`, …), in the same units. `flags_flame_spec` has one digit, with the meaning of the first digit of `flags_flame`, and `evolstage_flame_spec` is 0 for some stars without a mass.

The `esphs` group holds `teff_esphs` (K) and `logg_esphs` (log(cm/s²)) of ESP-HS from `astrophysical_parameters` (Gaia DR3 documentation, Sect. 11.3.8; Fouesneau et al. 2023, A&A 674, A28). ESP-HS fits the BP/RP spectra, and the RVS spectrum where it is good enough, with a solar composition. It runs on the stars brighter than G = 17.65 that ESP-ELS tags O, B or A, except the emission-line stars other than Be stars; about 1.65 million positionable stars have values. The first digit of `flags_esphs` gives the mode: 0 with the RVS spectrum, 1 with BP/RP only. Against literature values, the temperature below 25,000 K has offsets of a few hundred K and a scatter of 300 K (A stars) to 2,000 K (B stars); above, it is 1,000 to 5,000 K too low. Log g has offsets up to 0.1 dex and a scatter of 0.2 to 0.4 dex. The group has no uncertainties: with the RVS spectrum, Gaia's are 5 to 10 times too small.

Close rendering takes `radius_flame`, else `radius_gspphot`, and `teff_gspphot` for a smooth, limb-darkened photosphere, with photometric colour as a fallback. Stars without a radius remain points.

The `xgboost` group is Table 1 of Andrae, Rix & Chandra (2023, ApJS 267, 8; [Zenodo 7945154](https://doi.org/10.5281/zenodo.7945154), CC BY 4.0), joined to `gaia_source` by `source_id`; its provenance is `xgboost_source`. `mh_xgboost`, `teff_xgboost` and `logg_xgboost` come from XGBoost on the XP spectra, the CatWISE photometry and the parallax, trained on APOGEE DR17. `catwise_w1` and `catwise_w2` are the CatWISE2020 magnitudes (Vega) that it used, and `in_training_sample` marks the stars of its training sample. `in_vetted_rgb_sample` is true for the stars of their Table 2, a vetted sample of red giants with the same values. To remove OBA stars, the authors use the Gaia DR3 golden sample of OBA stars, the `oba_golden_sample` group. The table has no quality cut and no uncertainty for each star. The authors give about 0.1 dex for [M/H] in the training range, 0.2 dex at G ≈ 16 and 0.4 dex at G ≈ 17.65. [M/H] is not valid for OBA stars. On the main sequence it is unbiased for 0.5 < BP − RP < 1.5, about 0.15 dex too low for 1.5 < BP − RP < 2.5, and not valid outside 0.5–2.5. `teff_xgboost` stays near the training range of 3,107 K to 6,867 K (the table spans 2,975 K to 7,076 K), so it cannot mark a hot star (their Sect. 3.5, 3.7 and 4.3). The ingest applies none of these cuts. Of the 180,949,689 stars of ingest 4, 62.8% have a row: 24.8% of those with G < 6.5 and 72.6% of those within 100 pc.

The `gaia_classification` group also holds the class tags of Gaia DR3 from `astrophysical_parameters`, as published: `classprob_dsc_combmod_whitedwarf`, the spectral type tag `spectraltype_esphs` (O to M, `CSTAR` or `unknown`; ESP-ELS gives it, despite its name) with `flags_esphs`, whose second digit is the quality of the tag (1 best to 5, 0 for a confirmed carbon star, 9 for none) and whose first digit is the ESP-HS mode, and the emission-line class `classlabel_espels` with `classlabel_espels_flag` (Creevey et al. 2023, A&A 674, A26, Sect. 6.1.3).

The `oba_golden_sample` group holds `in_oba_golden_sample`. It is true for a star of the Gaia DR3 golden sample of OBA stars (`gold_sample_oba_stars`; Gaia Collaboration, Creevey et al. 2023, A&A 674, A39; all 3,023,388 rows), and false for every other Gaia DR3 star, also a `gaia-dr3-named` star. The sample holds the stars with an ESP-HS or GSP-Phot temperature above 7,500 K, after filters that remove most other kinds of source. Its provenance is `oba_golden_sample_source`. A star without a Gaia DR3 row has null.

Five more groups hold metallicities from spectra. Each group keeps the published values, and the reader applies the quality cuts. `gspspec` comes with the Gaia rows and `xhip_metallicity` with the Hipparcos rows. PASTEL, APOGEE and LAMOST join the Gaia rows by `source_id` at each ingest, and PASTEL also joins the Hipparcos rows by HIP number. A row that joins no star is left out. These three catalogues mint no ID and have no `cross_ids` entry. Their own ids are the columns `pastel_designation`, `apogee_id` and `lamost_id`. `pastel_source`, `apogee_source` and `lamost_source` name the row that the values joined: `gaia-dr3`, `gaia-dr3-named` (a SIMBAD star or a planet host without a 5σ parallax) or `hipparcos-2007`.

- `gspspec`: Gaia DR3 GSP-Spec from the RVS spectra (`astrophysical_parameters`, joined by `source_id`; provenance `gspspec_source`). `mh_gspspec`, `fem_gspspec` and `logg_gspspec` with their percentiles, and `flags_gspspec`, the 41-character flag chain, as published. `mh_gspspec_calibrated` is `mh_gspspec` plus the literature polynomial of Recio-Blanco et al. 2023 (A&A 674, A29, Table 3) in the uncalibrated `logg_gspspec`. `feh_gspspec_calibrated` is `fem_gspspec + mh_gspspec` plus their Fe I polynomial (Table 4), null outside log g 1.01–4.85 or where the flags give extrapol > 0, FeUpLim > 0 or FeUncer > 1. Their medium-quality cut is: each of the first 13 flags at most 1, fluxNoise (the 7th) at most 3, KMgiantPar (the 13th) 0.
- `xhip_metallicity`: the [Fe/H] of XHIP (Anderson & Francis 2012, V/137D) on the Hipparcos rows, provenance `xhip_metallicity_source`. `feh_xhip_error` is null where XHIP gives none. `feh_xhip_quality` is A (calibrated), B (calibrated, no error) or C (uncalibrated).
- `pastel`: PASTEL, 2020 version (Soubiran et al. 2016, B/pastel). A star gives the median of its [Fe/H] determinations (`feh_pastel`), their lowest and highest (`feh_pastel_min`, `feh_pastel_max`), their number (`feh_pastel_count`) and their bibcodes, space-separated (`pastel_bibcodes`). A few determinations are [M/H] or [Fe II/H]; they count as [Fe/H]. A designation gets its star by the first route that holds:
  1. Its HD or HIP number, through the Gaia best neighbour. When SIMBAD puts the name on another Gaia source within 10″ of the Hipparcos star, the SIMBAD source wins. It is the other component of a double. A Hipparcos star without a best neighbour also takes the SIMBAD source. When that source has no Gaia row (no 5σ parallax), the star joins the Hipparcos star by its HIP number, with all of its designations.
  2. Its J2000 position. Gaia and Hipparcos stars move to J2000.0 by their proper motion and must be within 3″. Where PASTEL gives V, the V of the candidate must agree to 0.3 mag; for a Gaia source, V comes from G and BP − RP (Riello et al. 2021). Where PASTEL gives no V, the candidate must be the only one and within 1″. When SIMBAD gives the name a Gaia source that is not a candidate, the match must also be within 1″. Of several candidates, the SIMBAD source wins, else the nearest.
  3. The Gaia DR3 id that SIMBAD gives the name.

  The designations of one star make one row. When SIMBAD has them as different objects, only the designations that SIMBAD puts on the Gaia source of the star stay; with none, the star has no row. `pastel_designation` is the HD or HIP designation where there is one, else the first.
- `apogee`: APOGEE DR17 (Abdurro'uf et al. 2022), the named ASPCAP values of `allStarLite`: `mh_apogee`, `feh_apogee`, `teff_apogee` and `logg_apogee` with their errors, and `snr_apogee`. SDSS leaves them blank where it flags the fit as bad. A star observed more than once keeps its row with the best S/N. A row joins by its Gaia EDR3 id, which APOGEE took from a cross-match of its 2MASS source. In crowded fields that id can name another star. So a row is left out when its G − H is more than 2.0 mag above the median G − H at its BP − RP, or more than 1.0 mag above it with a BP − RP more than 0.35 mag bluer than a dwarf at the ASPCAP Teff (Pecaut & Mamajek 2013).
- `lamost`: the LAMOST DR10 M dwarfs of Zhang, Zhang, Ting et al. 2025 (ApJS 277, 47; Zenodo 14030249, CC BY 4.0): `lamost_id` (the LAMOST designation), `mh_lamost`, `teff_lamost` and `logg_lamost` with their errors, `snr_i_lamost`, `activity_lamost` (Hα emission, for which the authors advise caution) and `vbflag_lamost` (0 none, 1 variable, 2 binary). A spectrum takes its Gaia DR3 id from the LAMOST DR10 v2.0 LRS catalogue of M stars, by `obsid`. A spectrum without one is left out, and so is one where the G of that catalogue differs from the G of Zhang et al. by more than 0.0001 mag: the two then name different sources, and the values belong to the source of Zhang et al. A spectrum without either G is left out too. A star with several spectra keeps the one with the best S/N in i, then the lowest `obsid`.

PASTEL, APOGEE and the LAMOST catalogue of M stars state no licence, so they are `non-commercial`, as the whole table is.

Three groups hold the classes of catalogues that do not measure the star: `gcvs`, `spicy` and `atnf`. `gcvs` and `spicy` join the Gaia rows by `source_id` at each ingest, as PASTEL, APOGEE and LAMOST do, and `gcvs` also joins the Hipparcos rows by HIP number, as PASTEL does. `atnf` joins only the SIMBAD rows, by SIMBAD oid. A row that joins no star is left out, they mint no ID and have no `cross_ids` entry, and `gcvs_source`, `spicy_source` and `atnf_source` name the row that the values joined (`gaia-dr3`, `gaia-dr3-named`, `hipparcos-2007`, `hipparcos-1997` or `simbad`).

- `gcvs`: the General Catalogue of Variable Stars, GCVS 5.1 (Samus et al. 2017, Astronomy Reports 61, 80), from the Sternberg Astronomical Institute. `gcvs_name` is the designation as SIMBAD spells it (`V645 Cen`, `alf02 CVn`, `chi Cyg`, `EQ Peg A`), `vartype_gcvs` the variability type as published (`UV`, `BY+UV`, `M`, `EA/RS` …; `:` marks an uncertain type). The `V*` identifier of an entry names a SIMBAD object, from the SIMBAD star list or else from a query of all GCVS designations. The star is the one SIMBAD row that holds the light of that object: the object, the Gaia or Hipparcos point that holds it, or the only row of a system. A system of several rows is left out, because the GCVS does not say which component varies. The star joins by the Gaia DR3 id of that row, else by its HIP number, its own or the one of a system whose primary it is (within 10″). An object outside the SIMBAD star list joins by its HIP number, unless the Gaia best neighbour of that number is another source, because its Gaia DR3 id can lack a 5σ parallax. An entry without an id or a type, or that the GCVS marks as not existing or as another GCVS entry, is left out; a designation in another galaxy (`=LMC V1970`) does not mark one. Two entries that reach one star, by its Gaia DR3 id or its HIP number, keep the first in GCVS order.
- `spicy`: the Spitzer/IRAC candidate young stellar objects of the inner Galactic midplane, SPICY (Kuhn et al. 2021, ApJS 254, 33; IRSA, doi:10.26131/IRSA556). `spicy_id` is the SPICY number, `class_spicy` the class as published (`ClassI`, `FS` for flat spectrum, `ClassII`, `ClassIII` or `uncertain`), `alpha_spicy` the spectral index of the infrared SED that gives the class. SPICY lists candidates, so some are evolved stars or planetary nebulae with the same infrared excess. A candidate takes the Gaia DR2 counterpart that SPICY gives it, and that id goes to the nearest Gaia DR3 source in `gaiadr3.dr2_neighbourhood`, by angular distance, then magnitude difference. A candidate without one is left out; when two candidates reach one DR3 source, the one whose DR2 source is nearer stays.

- `atnf`: the ATNF Pulsar Catalogue (Manchester et al. 2005, AJ 129, 1993; https://www.atnf.csiro.au/research/pulsar/psrcat). `atnf_name` is the J name of the pulsar (`J0146+6145`, `J0024-7204C`), `type_atnf` its type as published: ATNF's codes (`AXP`, `HE`, `NRAD`, `RRAT`, `XINS`) between commas, each with an optional reference in brackets, and `(?)` for an uncertain code (`AXP,NRAD`, `AXP[esy+20],HE[kdk+20]`, `NRAD,AXP(?)`). A query of SIMBAD resolves the J name and the B name (`PSR J0534+2200`, `PSR B0531+21`) of every pulsar. A pulsar takes the object of its J name, else of its B name. SIMBAD also gives the short form of a J name (`J0537-69`) to the pulsar of the full name (`J0537-6910`), and ATNF can list another pulsar under that short form. So of two pulsars with one object, the one whose J name has more declination digits keeps it; with equal digits, neither does. The pulsar then joins the SIMBAD row of that object. A pulsar whose object is not a row of the SIMBAD star list has no row, so most pulsars have none.

GCVS and SPICY state no licence, so they are `non-commercial` too. The ATNF Pulsar Catalogue is GPL v3 or later, so it is `open`.

The distance group and the SIMBAD photometry:

| Column | Type | |
|---|---|---|
| `distance` | float32 | distance (pc) from a paper, the star's system, a SIMBAD parallax or a distance catalogue |
| `distance_lower`, `distance_upper` | float32 | bounds of the uncertainty (pc); either can be null. For `galaxy`, the error of the galaxy's distance, not its depth. For `system`, the 1σ bounds of the system's distance, wider by the sky radius of each node above the star, so they hold the star |
| `distance_lower_percentile`, `distance_upper_percentile` | float32 | percentile (0–100) of each bound where published; null when a bound is an error or its percentile is unspecified |
| `distance_method` | dict | `parallax`, `photometric`, `cluster` (the distance of the host cluster), `association` (the distance of the star's OB association or cloud), `galaxy` (the distance of the host galaxy), `geometric` (parallax with a Galaxy prior), `expansion` (expansion parallax of a nebula), `dynamical` (parallax from a binary's orbit and masses), `model` (a fit to the object) or `system` (the shared distance of the star's system) |
| `distance_source` | dict | the first of `literature` (a paper chosen for the star, cited in its object entry), `star-systems` (the shared distance of the star's system, step 2 of the placement), `simbad-parallax` (a 5σ parallax that SIMBAD gives a `gaia-dr3-named` star, which has no 5σ Gaia parallax), `reyle-2021` (the 10 pc sample, Reylé et al. 2021), `ultracoolsheet` (Best et al.), `hunt-reffert-2024` (cluster members), `magellanic-clouds` (LMC and SMC members after Luri et al. 2021, at the distances of Pietrzyński et al. 2019 and Graczyk et al. 2020), `bailer-jones-2021` (Bailer-Jones et al. 2021) that has the star. A value under `star-systems` is not kept |
| `simbad_b_mag`, `simbad_v_mag`, `simbad_g_mag` | float32 | B, V and Gaia G that SIMBAD compiles from the literature (mag) |
| `simbad_sp_type` | string | the spectral type as SIMBAD gives it |
| `simbad_otype` | dict | SIMBAD's object type code (`*`, `**`, `V*`, `Em*` …), set for every star that SIMBAD lists |
| `simbad_system_sp_type` | string | the spectral type of the nearest SIMBAD system above the star that has one, when the star has no `simbad_sp_type`, is the brightest component of that system and has a magnitude (`NAME VY CMa A` takes M5Iae from `V* VY CMa`). A system with a composite type (a second star after a `+`, as in `DA2+dM`; `K5+III` is one star) gives none, and a system gives nothing to a Gaia point above it |
| `simbad_system_otype` | dict | the object type of the nearest such system, when it is a type of one star (not `**`, `SB*`, `EB*` or another type below `**` in SIMBAD's tree) and the star's own `simbad_otype` is `*` or a candidate type (`BD?` and `WD?` take only `BD*` and `WD*`) |
| `simbad_photometry_source` | dict | `simbad` for every star that SIMBAD lists |

The distance group is also filled for some stars with a good parallax. The render tree places a star by its parallax first, unless the distance comes from the literature or from its star system, or is a more precise measured parallax; see below.

A star of a star system can have the group `member` (`member_source` `star-systems`). `composite_moved` is true when the star's own spectral type in the catalogues (`simbad_sp_type`, `sp_type`) is the composite type of its system, which then is on the System row. `member_spectral_type` is the star's own type in the trees, null when none gives one. A client shows `member_spectral_type` in place of the catalogue type when `composite_moved` is true. The catalogue columns stay as published.

### Binary orbit (table 2)

The Gaia DR3 orbit of a binary star: one solution of `nss_two_body_orbit` for each star that has one, and the masses of its two stars from `binary_masses` (Gaia Collaboration, Arenou et al. 2023, A&A 674, A34). The table never mints. A row joins its star in the `gaia-dr3` or `gaia-dr3-named` pass by `source_id`, so the row has the star's ID, the home table is 1, and bit 2 of the star's `mask` is set. A solution of a source that is not one of those stars has no row: a source without a 5σ parallax that is no `gaia-dr3-named` row, or one with `fidelity_v2` under 0.5 and no Hipparcos, SIMBAD or exoplanet catalogue match.

Of the 437,275 sources with a solution, 394,046 are positionable stars: 169,096 with an astrometric solution, 179,186 spectroscopic and 45,764 eclipsing, and 195,224 of them with masses. 3,022 of these have `fidelity_v2` under 0.5. The other 43,229 sources have no 5σ parallax; 40,989 of them are eclipsing.

The columns keep the names of the Gaia DR3 documentation of `nss_two_body_orbit` and `binary_masses`, so a reader finds each one there. Two groups: `orbit`, every published column of the solution, with provenance `orbit_source`, and `masses`, with provenance `masses_source`. The solution has its own astrometry at J2016.0, the position, parallax and proper motion of the system's barycentre in the orbit model. Point source holds the single-star solution of `gaia_source` under the same names, so here these columns have the suffix `_nss`: `ra_nss`, `dec_nss`, `parallax_nss`, `pmra_nss`, `pmdec_nss`, each with its `_error` (as `ra_nss_error`).

The distance of a star with an astrometric solution (`Orbital…`, `AstroSpectroSB1`) comes from `parallax_nss`, where `parallax_nss / parallax_nss_error > 5`. The orbit fit takes out the motion of the light centre, which the single-star fit of `gaia_source` takes as noise or as part of the parallax, and its parallax error is about half as large. Where the render tree places the star by its parallax, or a planet host by its catalogue distance, it takes this one, and a client takes the star's distance and absolute magnitude from it too. Point source keeps Gaia's single-star values, and they still decide whether a parallax places the star (see the Milky Way render tree). A star with a spectroscopic or eclipsing solution keeps its Point source parallax.

Units are as published: angles in degrees, times and periods in days, `t_periastron` from J2016.0, Thiele-Innes `A`, `B`, `F`, `G` in mas and `C`, `H` in AU, velocities in km/s, masses in solar masses. A column is `float32` where float32 rounding stays under 1% of each published error. `ra_nss`, `dec_nss`, `period`, `inclination` and `temperature_ratio` are `float64`. `solution_id` and `flags` are `uint64`: `flags` is a bit field that uses bits up to 57, past 2^53. `bit_index` is `uint32`. `corr_vec` is a `float32_list`: the published upper triangle of the correlation matrix, column by column, over the parameters that `bit_index` names, NaN entries included. It has 6 to 190 entries, and it takes about half of the bytes of the table.

A star with more than one solution keeps one. The order is: `AstroSpectroSB1`; `OrbitalTargetedSearchValidated`, `OrbitalAlternativeValidated`, `Orbital`, `OrbitalTargetedSearch`, `OrbitalAlternative`; `SB2`, `SB2C`, `SB1`, `SB1C`; `EclipsingSpectro`; `EclipsingBinary`. Astrometric solutions come first, because only they give the orbit in space. The ingest logs the solutions it leaves out by type pair; most are the `SB1` solution of a star with an `Orbital` one.

`m1`, `m2` and `fluxratio` (the secondary over the primary in G) have bounds `_lower` and `_upper`, for the masses the 16th and 84th percentiles. `combination_method` names the solutions that gave the masses, as `Orbital+M1`: the astrometric orbit with a primary mass from isochrones (`m1_ref` `IsocLum`). Where a source has two mass rows, the row keeps the one whose method names the kept solution. A star can keep masses from another of its solutions: `SB1+M1` beside an `Orbital` solution.

What each kind of solution lets a client draw:

| `nss_solution_type` | Gives | A client can draw |
|---|---|---|
| `Orbital`, `OrbitalAlternative…`, `OrbitalTargetedSearch…` | `a_thiele_innes`, `b_…`, `f_…`, `g_…`, `period`, `t_periastron`, `eccentricity` | the full orbit of the light centre about the barycentre, with its orientation on the sky |
| `AstroSpectroSB1` | the same, and `c_thiele_innes`, `h_thiele_innes`, `center_of_mass_velocity` | the full orbit, with its depth along the line of sight |
| `SB1`, `SB1C`, `SB2`, `SB2C` | `period`, `eccentricity`, `arg_periastron`, `t_periastron`, `semi_amplitude_primary` (and `_secondary` for SB2); `C` forms are circular | the shape and phase of the orbit and its size along the line of sight (a sin i). No orientation on the sky |
| `EclipsingBinary`, `EclipsingSpectro` | the light-curve fit: `period`, `inclination`, `eccentricity`, radii and eclipse times; `EclipsingSpectro` adds the velocities | the inclination; with the velocities also the size. No orientation on the sky |

The astrometric orbit from the Thiele-Innes elements: at time `t` (days from J2016.0), solve `E − e sin E = 2π (t − t_periastron) / period` and take `X = cos E − e`, `Y = √(1 − e²) sin E`. The light centre is then `Δα* = B X + G Y` and `Δδ = A X + F Y` (mas) from the barycentre, and `C X + H Y` (AU) along the line of sight for `AstroSpectroSB1`. Divide by `parallax_nss` (mas) to get AU.

The masses place the companion. With the mass fraction `μ = m2 / (m1 + m2)` and the light fraction `β = fluxratio / (1 + fluxratio)` (0 for a dark companion), the light centre is at `(β − μ)` times the separation from the primary to the secondary. So the primary is at `μ / (μ − β)` times the light-centre offset, and the secondary at `−(1 − μ) / (μ − β)` times it, on the other side of the barycentre.

### System (table 3)

The star systems. A system is a tree, and each node of the tree has a row:

- a **point** that holds two or more stars (Capella, Mizar A, a star with a Gaia DR3 orbit). It keeps the ID of its point, so its home table is 1, and bit 3 of its `mask` is set;
- a **resolved system**, which has no point of its own (α Cen AB; α Cen itself is AB and Proxima). Its ID has home table 3 and the cell of its primary's J2016.0 position. It has no Point source row, so the render tree does not draw it: its stars are drawn;
- a **held star**, a star with no point of its own that has an ID (below). Its ID has home table 3 and the cell of its node's position, its `ra` and `dec` are its node's, and `stars` is 1.

The members of a node are stars (points that hold one star, which have no System row), nodes, held stars and entries. A held star and an entry are stars with no point of their own: a star inside its node's point (Capella Aa and Ab), or one that only a catalogue gives. A held star has an ID because the orbit of its pair is drawn, or because a source gives it a letter or a name and more is known of it: a name of its own (SIMBAD, a planet catalogue), a mass, a radius, a temperature or a spectral type. An entry has no ID. A star that is only a letter of the WDS or the MSC stays an entry, also with a magnitude or a separation, and so do the two stars of a Gaia DR3 orbit that is not drawn, with the masses of the orbit. A client lists an entry as a line of its system, with no page. The name of a held star is the one that SIMBAD or a planet catalogue gives it, unless that is the name of its pair or root, else its root's name and its letter ("Castor Ba"). A held star with no letter is A in its pair when it is the heavier star (the first member when the masses do not tell, the letter that the other member leaves when that one is A or B), else B, and takes its pair's name ("HD 1234 A"). One type covers every level: a binary is a system of two, and a pair inside a system is a node too. A system whose hierarchy no source gives is a flat list of members. A star is a member of one node at most, and every node but the root has one parent. The root's row holds the whole tree, so one record gives the system.

A brown dwarf can be two things at once: a planet record of its host (a planet catalogue lists companions up to 60 MJ) and a star of a star catalogue. The record of class `brown dwarf` stays on its host, and its star stays a member of the system. It takes the component of the MSC or the WDS that lies where it lies from the host, within 7″, so a system has one line for it. A component with no measured separation gives no place. Else it joins the top of the host's system, or the host joins the top of the star's and goes first, as a brown dwarf is no primary. A wide binary of El-Badry that holds the one that joins comes with it. With neither in a system, the two make one, a `binary star`, whose `sources` are the planet catalogues. The record has the star in `star`, and the star's Metadata row has the record in `planets`. A star whose parallax clearly disagrees with its host's is another star, reached by a wrong id: it stays as it is, with no link. A star or a host that a Gaia DR3 orbit or a SIMBAD type shows as a close pair is exempt, as a close orbit can throw off the parallax. A record under the IAU's line (class `planet` or `sub-brown dwarf`) stays a planet only: the star it reaches leaves every tree. No other record brings it back: a brown dwarf record of that star leaves with it, and one hosted on it has no member and no link.

The trees come from these sources, in source order: Tokovinin's Multiple Star Catalogue (MSC), SIMBAD's hierarchy of objects without the objects that are not of a stellar type (the links of a cluster to its members are no hierarchy), the systems of the planet catalogues, the Washington Double Star Catalog (WDS) without the pairs that it notes as optical or bogus, the wide binaries of El-Badry, Rix & Heintz 2021 with a chance-alignment probability under 0.1, and the Gaia DR3 orbits of table 2. A member joins its star by a catalogue id (Gaia DR3 `source_id`, HIP, HD, SIMBAD oid, WDS id), else by position and magnitude, but never the star of a WDS node that holds it, or of a WDS component near it. The MSC and the WDS do not share component letters, so an MSC and a WDS component of one WDS id and letter share a star only when their separations from their primaries agree: the MSC separation is within a factor of 5 of the first and last WDS measures, or 1.5 for a pair that the MSC knows only by common proper motion. A component with no separation shares a star by the letter alone. Before that, an MSC component with no star matches by position and magnitude, within 1.5″ (5σ of an error of 0.3″), as MSC places are Gaia places. One that still has none takes the star of the WDS component of its WDS id at its place, within 1.5″ and at most half the way to the next star, whatever the letters. A component that has its star by place neither takes one by its letter nor lends it. A row of the MSC's `comp.tsv` for a letter with no node of its own (comp A of a tree with only Aa and Ab) gives its place, ids and values to the lowest node above the labels of that letter, when all the stars of that node are of that letter. A node of the MSC matches by position like a component, as the MSC's place sits on the node when its stars are unresolved. A star over 10′ from the WDS id of its member (past the widest separation above that member) and over 60″ from the member's own place is a wrong id, and the member does not take it. Each test allows for the star's motion from J2000. A component of the MSC, the WDS or SIMBAD whose stars all left the trees is a planet (above), no member. A member that reaches no star is an entry. An entry that its sibling's star cannot split from it is inside that star's point, unless it has a period and a visual orbit and the point already holds a pair. It then stays beside the point, so that both orbits can be drawn. An entry is a star of its system when its separation from its primary and its position angle agree with that star's, or when its magnitude agrees and its separation agrees within the motion of an orbit. The best agreement wins. An entry of a node is also the star inside a point of its system that has its WDS component id (the WDS id and letter, as the WDS or the MSC gives it), unless their separations disagree. It is also the star that another source lists inside its primary at its separation: within half the larger separation, at most 2″, or within 5× when both rows know a visual orbit. An entry with a period stays, so that its orbit can be drawn. So does one with a visual orbit, unless the star inside knows that orbit too. So the system lists each star once, and a node left with one member is that member. A point holds several stars when it has a Gaia DR3 orbit whose companion is no planet that the planet catalogues give it (a period within 5%), when a catalogue lists a pair inside it, or when its SIMBAD type is one that only a close pair shows (`EB*`, `SB*` …) and no companion of it is a point of its own. An acceleration solution of Gaia without an orbit adds no member.

A member leaves its node when its parallax and its primary's clearly disagree: both from Gaia or Hipparcos, each over 5σ, apart by more than 5σ (6σ at 4″ and closer) and by more than 10% of the larger one. A Gaia solution with a RUWE over 1.4 does not fit its star, so its error counts multiplied by its RUWE, up to 4 times, in the 5σ tests too: on pairs that radial velocity shows real, the gap stops growing with the RUWE at about 3 raw errors. Of the pairs that this frees, 65% agree in Gaia radial velocity within 5 km/s, against 12% of the pairs that the veto still refutes. This veto applies to every source, El-Badry's pairs too. It skips an orbit pair: an orbit proves a pair. A point that holds a close pair gets no such pass, as the scale covers what a close pair does to its astrometry: of the pairs of such a point that these tests refute, 12% agree in radial velocity, the chance level. A member that its source does not give as physical (a WDS pair with no note that it is physical) stays only when it and its primary pass the bound-pair test of El-Badry, Rix & Heintz 2021 (section 2), or when its primary's point holds it: the source gives a separation that the point cannot split. A dubious member never stays. A member that does not stay waits for another source to give the pair, and keeps its inner system as a system of its own. An interior of such members gives way to a Gaia DR3 orbit, a SIMBAD close type, or another source's interior.

A member also leaves when it is not bound to its primary: when any of its stars is over 2 pc of projected separation away, at the distance of the brighter star (the tidal radius of 2 M☉ is 1.7 pc, Jiang & Tremaine 2010), or when its motion is apart from its primary's by over 8 km/s beyond an orbit plus 3σ. The errors of a Gaia motion count as in the veto. Gaia's and Hipparcos's motions count, a Hipparcos motion only under a 5σ parallax, as a star with none has no distance to turn its motion into km/s. The motion test skips an orbit pair and pairs under 4″, where Gaia's motions are not reliable. A member leaves too when it and its primary are members of one open or globular cluster and any of its stars is over 10,000 AU of projected separation away: in a cluster shared motion is no evidence, because every member has it. A member here is a star of the member list of Hunt & Reffert 2024 (A&A 686, A42) inside the tidal or the Jacobi radius, at any membership probability, as bright stars have low ones. This test skips only an orbit pair, as it reads no astrometry that a close pair can throw off, and applies to El-Badry's pairs too. A moving group is no cluster. A star with no Gaia DR3 row is on no member list, so a pair with such a star never fails it. A primary with no star of its own tests nothing, so the first star of the node that stays stands for it. A refuted member stays an entry when its star is far from the catalogue's separation (over 5 times and 60″): the star is real, and the id reached the wrong one. A separation alone refutes no pair. A point that a source gives to a group beside its members leaves the same way, when it is over 2 pc from the main star, over 10,000 AU from it in one cluster, when its motion is apart from the main star's as above and no member has an orbit, or when its parallax disagrees with a member's.

| Column | Type | |
|---|---|---|
| `id` | id | |
| `point` | bool | true for a point, false for a resolved system or a held star |
| `depth` | int16 | 0 at the root |
| `stars` | int32 | the stars below the node: its member stars, held stars and entries, and those of its member nodes; 1 for a held star |
| `ra`, `dec` | float64 | the ICRS position at J2016.0 of the node's primary point (deg) |
| `label` | string | the component letters (`AB`, `Aab`), or the name that a source gives the pair; a held star's letter |
| `spectral_type` | string | the composite spectral type of the node's stars ("F5IV-V+DQZ") |
| `evidence` | dict | a point: the source that shows that it holds several stars |
| `sources` | list | the trees that list the node, first in source order: `msc`, `simbad`, `planet-catalogues`, `wds`, `el-badry-2021`, `gaia-dr3-orbits`, `simbad-type` (item column `sources.item`, dict) |
| `tree_source` | dict | `star-systems` |
| `parent` | id | the node that lists this one; null at the root |
| `root` | id | the root of the system, its own ID at the root |
| `primary` | id | the primary point of the node; null for a held star |
| `distance` | float64 | the node's shared distance (pc, step 2 of the placement), else the distance of the primary point; a held star has its node's. With `ra` and `dec` it places a row that has no Point source row: a resolved system or a held star. Null when no star of the node has a distance |
| `members` | list | the direct members, in member order: item columns `members.<field>` (below); empty for a held star |
| `tree` | list | in the root's row, every node of the system, sorted by ID; null in every other row: item columns `tree.<field>` (below) |
| `orbit` | list | on a pair whose orbit can be drawn, a node of two members or a point of three stars: one item, the orbit of member `second` about member `first` (item columns `orbit.<field>`, below); null on every other row |
| `star` | list | on a held star: one item, its values (item columns `star.<field>`, below); null on every other row |

The container has no struct type, so `orbit` and `star` are lists of at most one item: row `i` has a value when `offsets[i + 1] > offsets[i]`, and the value is item `offsets[i]` of the item columns.

A member:

| Field | Type | |
|---|---|---|
| `id` | id | the ID of the star, the node or the held star; null for an entry |
| `kind` | dict | `star`, `system`, `held star` or `entry` |
| `letter` | dict | its component letter (`A`, `Ba`); null when another member of the system keeps the letter (below) |
| `inner` | string | for an entry inside a point, its letters within the point (`Ca` of `Cab`) |
| `label` | string | a name that the source gives it |
| `source` | dict | the tree whose values the member has |
| `spectral_type` | string | |
| `v_mag`, `g_mag` | float32 | V and Gaia G (mag) |
| `mass` | float32 | solar masses |
| `separation` | float64 | from the node's primary (arcsec) |
| `position_angle` | float32 | deg |
| `period` | float64 | days |
| `eccentricity` | float32 | |
| `semi_major_axis` | float32 | arcsec |
| `known` | list | how the member is known: `visual`, `visual orbit`, `common proper motion`, `common parallax`, `spectroscopic`, `spectroscopic orbit`, `eclipsing`, `astrometric`, `astrometric orbit`, `occultation`, `catalogue` (item column `members.known.item`, dict) |
| `ids` | cross_ids | the catalogue ids of an entry |

A node of the tree has `id`, `parent` (null at the root), `point`, `stars` and `label` as its own row has them, and `class`, its Metadata class (`star` for a held star).

Component letters are consistent within one system only: the catalogues do not share them. A letter stays with one member of a system, an entry too. A star keeps it before a node, whose letter is that of its main star. Then the earlier tree source keeps it, in the order above, then the first member. Another member with that letter has a null `letter` and `inner`, and a null `label` when the label only repeats the letter. A name that a source gives stays in `label`. A letter of a pair (A or B of a held star that no source gives a letter) is no source's letter, so it does not count.

#### Held stars

A held star has a Metadata row with its name, the class `star` and the `system` of its root, and a System row, its home: no Point source row. Its page places it at its System row's `ra`, `dec` and `distance`, those of its node.

A held star keeps its ID from ingest to ingest by its claim: its node, and what of its own names it in the node. That is the letter or label that its source gives it, also when another member of the system keeps the letter, else its side of its Gaia DR3 orbit, else the letter of a paper or of OEC. A star that nothing of its own names, or whose claim another held star makes too, gets no ID and stays an entry.

A held star is a star like any other in the family masks and lists: its `star.spectral_type` gives its families and its Metadata `spectral_type` (Families, above), and its `star.g_mag`, else `star.v_mag`, gives its place in `families.json`.

Its names, in this order:

- the name that SIMBAD or a planet catalogue gives it, unless that is the name of its pair or of its root;
- its root's name and its letter, when it keeps a letter that a source gives: the letters of the WDS and the MSC name the components of the whole system ("Castor Ba"). A root that takes its primary's name drops the primary's component letter first ("HQ Tau Aa", not "HQ Tau A Aa");
- else its pair's name and A or B ("Kepler-16 A", "HIP 14164 B"): A is the heavier star of the pair, B the other. With no masses, or equal ones, A is the first member. When the other member has the letter A or B, it takes the letter that is left. A star with no letter in a node of three or more members has no name.

`star` holds its values. Each comes from the first source that has it: a paper (`literature`), OEC (`open-exoplanet-catalogue`), the tree source of the member, then the masses of its Gaia DR3 orbit (`gaia-dr3-orbits`). The two stars of a paper or of OEC go to the members by their letters; with no letters that agree, the paper's primary goes to the first member.

| Field | Type | |
|---|---|---|
| `mass` | float32 | solar masses |
| `radius` | float32 | nominal solar radii |
| `teff` | float32 | K |
| `spectral_type` | string | a paper's type is what it prints for that star, in the form that the family rules read: `dM` for "M dwarf", `GV` for "main sequence G-type star"; a letter alone (`K`) gives no family |
| `mass_source`, `radius_source`, `teff_source`, `spectral_type_source` | dict | the source of each value |
| `references` | list | the works of the values from a paper, also a work that gives only the type: item columns `star.references.<field>` (a citation, below) |
| `v_mag`, `g_mag` | float32 | V and G of its member (mag), which rank it in the star families |

#### Pair orbits

`orbit` is the orbit of a pair's second member about its first, ready to draw. `first` and `second` give the two members. A point of three stars of two sides (the `inner` of one is null, the other two share theirs) holds the pair of the first star of each side, as Gaia DR3 sees the outer pair of a close triple. Its second star stands for both stars of its side, so neither star takes the pair's values of a star. An orbit at the period of the inner pair stays off, as that pair has no node, unless a paper gives it: then the point holds the pair of its two stars with one `inner`. Each element comes from the first orbit that has it: a paper, the MSC, ORB6, SBX, OEC, then Gaia DR3; within one source, the orbit with the most elements first. A measured `e` or `ω` comes before an assumed one. An orbit names a pair by a component id or by a point that holds the pair. An MSC and a WDS id that are equal name one star unless their separations disagree. Then each source reads its own catalogue: the MSC's for the MSC, the WDS's for ORB6 and SBX. A star that stands in both trees takes the MSC's member, unless only the WDS's is in a pair. An orbit that names a host reaches the pair of the host and its brown dwarf only at the period of the record, within 5%: the host can have a companion that no tree lists. An orbit is drawn when it has `period`, a semi-major axis, `inclination` and, unless it is circular, `arg_periastron`. An angular semi-major axis takes `distance`; with none, Kepler's third law gives it from the total mass of a paper, of Gaia DR3 or of OEC (`computed`). The scene's elements (`a` to `phase`) are on the ecliptic and the mean equinox of J2000, as the planets' elements (Planets, "Elements"); the sky's elements are on the plane of the sky.

| Field | Type | |
|---|---|---|
| `first`, `second` | int8 | the places of the first and the second member in the node's `members`, from 0: 0 and 1 on a node of two members, and on a point of three stars the two stars of its pair |
| `a` | float64 | semi-major axis of the relative orbit (AU) |
| `e` | float64 | eccentricity |
| `i`, `om`, `w` | float64 | inclination, longitude of the ascending node, and argument of periastron of the second member, on the ecliptic of J2000 (deg) |
| `ma` | float64 | mean anomaly at `epoch` (deg) |
| `n` | float64 | mean motion (deg/day) |
| `epoch` | float64 | JD of `ma`, in the time scale of its source |
| `phase` | dict | what fixes `ma`: `periastron`, `eclipse` (the second member in front of the first at the primary eclipse), `osculating` (the epoch of a photometric-dynamical fit), or `assumed` (no epoch: periastron at J2000) |
| `period` | float64 | days |
| `semi_major_axis` | float64 | AU, as `a` |
| `semi_major_axis_arcsec` | float64 | the angular semi-major axis that gave `semi_major_axis` with `distance` (arcsec); null when a source gives AU or Kepler's third law gives it |
| `eccentricity` | float64 | as `e` |
| `inclination` | float64 | to the plane of the sky (deg); under 90 the second member turns from north to east |
| `node` | float64 | the position angle of the node, from north through east (deg) |
| `node_ascending` | bool | true when `node` is the ascending node, where the second member moves away from us; false when it can be either node |
| `arg_periastron` | float64 | of the second member, from `node` (deg) |
| `periastron_time` | float64 | JD of a periastron |
| `barycentre` | float64 | the place of the barycentre on the line from the first member to the second, as a share of their separation: m2 / (m1 + m2). 0 with no mass ratio |
| `centre` | dict | `barycentre`; `primary` when no source gives a mass ratio: the first member stays at the centre, and the second moves on the relative orbit |
| `mass_ratio_source` | dict | the source of `barycentre` |
| `period_source`, `semi_major_axis_source`, `eccentricity_source`, `inclination_source`, `node_source`, `arg_periastron_source`, `epoch_source` | dict | the source of each element: `literature`, `msc`, `orb6`, `sbx`, `open-exoplanet-catalogue` or `gaia-dr3-orbits`. When Kepler's third law gives the semi-major axis, the source of the masses |
| `assumed` | list | the elements that a rule fills (item column `orbit.assumed.item`, dict): `eccentricity` (0), `arg_periastron` (90° on a circular orbit), `epoch` (J2000, `phase` `assumed`), `node` (below) |
| `computed` | list | the elements that other values give: `semi_major_axis` by Kepler's third law (item column `orbit.computed.item`, dict) |
| `references` | list | the works of the elements, one per source, in source order: item columns `orbit.references.<field>` (a citation, below) |

The mass ratio of the barycentre comes from the first of: the two masses of a paper, the K1 and K2 of an MSC or an SBX orbit, the two masses of Gaia DR3 (`binary_masses`), the two masses of OEC, then the two masses of the pair in the MSC (`sys.tsv`, `msc`). An MSC mass with the code `m` is the minimum mass of the secondary of a single-lined orbit, so it gives no ratio.

A pair with no node on the sky has the node of its planets: one angle per system, from a hash of the ID of its root (Planets, the `assumed` field), named `node` in `assumed`. A circumbinary planet with no node of its own takes its pair's node. So the pair and its planet are in one plane.

ORB6 and the MSC can give either node (`node_ascending` false). ORB6 flags an ascending node: `*` where it is identified, `q` where ORB6 turned the published node by 180°. An orbit of the pair whose ω is fixed by its velocities or by an eclipse settles it: when its ω and the visual orbit's are more than 90° apart, `node` and `arg_periastron` turn by 180°, and `node_ascending` is then true. An assumed ω, of either orbit, settles nothing.

A citation:

| Field | Type | |
|---|---|---|
| `source` | dict | the source of the elements or values that it cites |
| `reference` | string | the source's key of the work: a paper key of the constants (`literature`), the note of the orbit (`msc`: "SB9_2192 2002AJ....124.1144L", "NSS SB1"), a WDS reference code (`orb6`: "Msn2023"), a bibcode (`sbx`), or a solution id (`gaia-dr3-orbits`) |
| `short` | dict | the authors and the year ("Doyle et al. 2011"); null when the export does not know the work |
| `title` | dict | the title, with the journal |
| `url` | dict | a DOI or an ADS page |

A page shows `short` and `title`, else `reference`, and links them to `url`. A paper key has its work from the constants (`constants/stars/binaries.py`, `literature.py`). A Gaia DR3 orbit, and an MSC note of one (`NSS …`, `DR3 …`), cites Gaia Collaboration, Arenou et al. 2023. A bibcode, also one inside an MSC note, links to its ADS page with no `short` or `title`. An ORB6 code has no citation yet: its work is in the WDS reference file, which the export does not read.

A client reads a system from the root's row: the tree gives every node and its parent, and the row of each node gives its members. From any star or node, Metadata `system` names the root. The row of a point in Point source keeps the fits that assume one star (FLAME, GSP-Phot). Its System row (bit 3 of `mask`) says that they do not hold, and so does its class `binary star` or `multiple star`. A resolved system keeps its ID from one ingest to the next by the catalogue ids in its Metadata `cross_ids`, under the rule of every ID. A point keeps its own ID.

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

Most objects have rows only in their home table, so a lookup is one round trip after the split tables. A point of a star system also has a System row (bit 3 of its mask). A resolved system and a held star have their home in table 3 and no other row: their System row gives their place (`ra`, `dec`, `distance`), and a held star's values are in `star`.

## Milky Way render tree (`mw`)

An octree by visibility range for the objects of the Milky Way. It holds the stars of Point source with a distance. A point that holds several stars is one row, as before. A resolved star system has no Point source row, so it has no render row: its stars have theirs, and a star with no distance of its own can take its system's (step 3 below).

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
- **Precision.** A float32 position relative to the centre is off by up to half · 2^-24: about 13 AU for a star in a node of half size 1,024 pc, 0.8 AU in a node of half size 64 pc. A client that goes near one star takes its position from the star's record, with the distance rule below.

Which stars are drawn, and where (`extrasolar.placement`; the ingest report counts the planet hosts by the same rule):

1. A star whose `distance_source` is `literature` is at `distance`: that value was chosen for the star from a paper. This holds for every star, flagged or not.
2. Else a star whose `distance_source` is `star-systems` is at `distance`, with `distance_method` `system`: the shared distance of its star system. Parallax noise puts the stars of a system further apart in depth than they are on the sky, so the system outranks the star's own parallax, but not a paper. See "The shared distance of a system" below. Point source keeps the star's own `parallax`.
3. Else a star with `parallax / parallax_error > 5` that is not flagged is at `1000 / p`, unless its distance group is a more precise measured parallax: `distance_method` is `parallax`, `distance_source` is not `simbad-parallax`, and `(distance_upper − distance_lower) / (2 · distance)` is under `parallax_error / parallax`, or under half of it for Gaia astrometry. That star is at `distance` (step 4). The distance catalogues copy Gaia's parallax with its error rounded down, hence the margin. SIMBAD's parallax on a row with its own is Gaia DR2's, with errors too small. A distance from a prior (`geometric`), a cluster or a galaxy stays below the star's own parallax. A star is flagged when its `astrometry_source` is `gaia-dr3` or `gaia-dr3-named` and its `fidelity_v2` is under 0.5. A Hipparcos, SIMBAD or exoplanet catalogue parallax is never flagged, even when the row has the `fidelity_v2` of a Gaia source.
4. Else a star with `distance` is at `distance`.
5. Else a planet host with a `host_distance` is at `host_distance`, along its RA and Dec, or at `1000 / parallax_nss` when it has a 5σ astrometric orbit solution.
6. A flagged star is drawn only when Hipparcos, SIMBAD or an exoplanet catalogue saw it (`hipparcos_photometry_source`, `simbad_photometry_source` or `host_star_source` not null), or by step 1. Its parallax is suspect, so steps 4 and 5 come first, also for a star that Hipparcos or SIMBAD saw. Else it is at `1000 / p` when `parallax` is 5σ.
7. A star with no distance from these steps has an ID and a record, but no render row. So has a star with no magnitude, unless it is a planet host.

In steps 3 and 6, `p` is `parallax_nss` of table 2 for a star with an astrometric orbit solution whose `parallax_nss` is over 5 times its error (see Binary orbit), else `parallax`. The single-star `parallax` and `parallax_error` still decide whether step 3 or 6 holds. The planet files say how each host is placed (`placement`).

Positions are at J2016.0: a row at another `epoch` (J1991.25 for Hipparcos, J2000.0 for SIMBAD) moves by its proper motion. A row without proper motion stays at its epoch. The absolute magnitude takes the distance `d` used: `mag = G − 5 log10(d / 10 pc)`, with no correction for extinction. G is the first of: `phot_g_mean_mag`; `simbad_g_mag`; the estimate of G from the Hipparcos V and B − V, else from Hp, that the ingest uses for matching (`g_estimate` of the Hipparcos source); the same estimate from `simbad_v_mag` and `simbad_b_mag − simbad_v_mag`; for a planet host, `host_g_mag`, else `host_v_mag` taken as G. A planet host with no magnitude at all (most microlensing and pulsar hosts) takes absolute G 15.0, a placeholder that keeps it in the tree and draws it only near its system. The colour is `phot_bp_mean_mag − phot_rp_mean_mag`; for a star without Gaia colours, BP − RP from the Hipparcos V − I (Riello et al. 2021, Table C.2: −0.01612 + 1.274 x − 0.08143 x², x = V − I from −0.5 to 3.5); else BP − RP of a dwarf of the star's Teff (`host_teff`, else `teff_gspphot`) by the dwarf sequence of Pecaut & Mamajek (2013, table version 2022.04.16, B9V to M8.5V, linear between rows, the nearest end outside them); else NaN. SIMBAD's B − V gives no colour: Riello et al. 2021 give no BP − RP from B − V.

### The shared distance of a system

A system of two or more points takes a distance, from the root of its tree down. A point alone in its system keeps its own place.

- The members of the tree share. The tests of membership have already refuted a star that lies far from its primary, so a vote that still disagrees is a poor parallax of a real pair, and the mean outweighs it.
- A point votes with what steps 1 and 3 to 6 give it. A paper comes first: the most precise, where a node has two. Then a measured parallax: a star's own, with a 5σ `parallax_nss` in its place, or a distance group of `distance_method` `parallax` that step 3 prefers. Then a 5σ parallax that fidelity flags, which counts only when the node has no measured parallax. Then any other distance, which counts only when the node has neither: a distance from a prior or a group of stars, a `host_distance`.
- A node's own distance is the inverse-variance mean of the best votes below it, in parallax. A point counts once, however many stars it holds. A Gaia error counts as in the veto of the Star systems section. A Hipparcos parallax weighs by its own error. A distance with no error counts as ±100%.
- The root takes its own distance. Each member takes its parent's distance plus its own offset, shrunk by its error σ to `offset × cap² / (cap² + σ²)` and held within ±cap. The cap is the sky radius of the parent: the widest separation of a member from the parent's primary, at the parent's distance. So a member whose error is far above the cap stays near its parent, as most do, and a star that resolves its own depth keeps it: Proxima stays nearer than α Cen A and B. A close pair inside a wide system stays close. A node takes the same rule with the error of its own distance. A member with no distance of its own takes its parent's.
- A star with its own paper keeps that distance (step 1). The others take the system's.

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
    { "ref": "DSO:M44", "reason": "deep-sky", "designation": "M44", "position": [-111.1, 132.2, 61.6], "stand_in": "hunt-reffert-2024" },
    { "ra_hours": 19.43791, "dec": -23.807, "position": [18.5, -46.8, -22.2], "stand_in": "culture-stars" }
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
  - a star: `id` is its extrasolar ID, and `position` its position in parsecs, in the frame of the render tree (ICRS axes, origin at the barycentre, J2016.0), as float64. The position is the one that the tree build computes for the star, from the same code over the same rows, so a line ends on the rendered star: it is the float64 value that the node stores as the node's centre plus a float32 offset. A star that the tree does not draw has an `id` and no `position`: a star with no distance (no 5σ parallax and no `distance`), a flagged star that neither Hipparcos nor SIMBAD saw, or a star with no magnitude (see the render tree). A named Gaia source without a 5σ parallax (`gaia-dr3-named`) has an `id`, and the tree draws it when it has a `distance`.
  - an object with no ID: `ref` as the source writes it, `reason` (below), and `designation` for a deep-sky object or a planet. A line that passes through it keeps its index, so no line is cut; a client skips the segments to a member without a position.
  - a point of the sky that a Stellarium figure gives in place of a star: `ra_hours` and `dec` (degrees) as published.

  A deep-sky object and a point of the sky have a stand-in position until the registry holds an object for them: `position` as for a star, and `stand_in`, the source of its distance. A deep-sky object takes its direction from SIMBAD (the local export), else OpenNGC, and its distance from `baumgardt-globular-clusters`, `hunt-reffert-2024` (the median, of a row of `Type` o, g or d; a row's own `Name` goes before an alias that rows share) or `hecate`, the first that lists one of its SIMBAD identifiers. With no such distance, and for each point of the sky, `stand_in` is `culture-stars`: the distance is the median of the culture's stars, so that a figure of sky points keeps its shape from near the Sun and stays among the culture's stars from afar. A stand-in is no star: it is in no shard, in no page's stars, and has no ID. A `solar-system` member, `NAME Milky Way` (a band, no point) and `PK080-06.1` (not in the local catalogues) have no position.
- **`figures`.** `kind` is `constellation` or `asterism`. `names` lists the names of the figure, each with the fields that the source gives of `native` (in the culture's script), `english`, `pronounce`, `transliteration` and `IPA`. `lines` is a list of chains; each chain is a list of member indexes, joined in order. A Bucur figure can have `group`, member indexes of a star group with no lines, and `iau`, the IAU constellation that holds a figure whose stars are not known. In `modern`, `modern_iau`, `modern_st` and `modern_chinese`, each constellation has `iau`, its IAU abbreviation. `modern_journey_to_the_west` has the IDs of the 88, but draws figures of its own, so it has no `iau`.

  `slug` is the figure's segment in the URL of its page, `/g/culture-<key>/f/<slug>`, which a client builds from this file. It is the last word of the `id`, with no marks and with `-` for what a URL escapes, after `ast-` on an asterism: an asterism can share that word with a constellation. A source can repeat an ID, and two words can differ in their marks alone, so a later figure with the same slug takes `-2`, in the order of the source. In the export of 2026-10-31 that is `ast-BdQd-2` in `arabic_al-sufi`, `Zbn1-2` in `arabic_arabian_peninsula`, `Sara-2` in `indian`, `05A-2` in `japanese`, `H19-2` in `korean` and `019-2` in `pardhi`. A ray helper has no `slug`, and neither has a figure of a culture that the picker leaves out, unless it is the home of its `page` (`sky-quadrans-muralis` in `modern`): a figure with no `slug` has no page.

  `description` is the source's text on the figure, as the source writes it, on a culture whose licence lets the site show text (`text_allowed`, the rule of `culture_text` in [groups.md](groups.md)). Only Bucur's figures have one, and no catalogue of Stellarium's translates them. The culture's `credit` credits it.

  `page` is the key of the figure's group data ([groups.md](groups.md)), the article and the pictures of the constellation it is. It has no URL. The constellations of those four cultures have one by their Latin `native` name, and the figures of `dien` and `ruelle` by their Latin `english` name, with `(eq)` on the second chart of a constellation. A Chinese mansion, a nakshatra and a historical Western constellation have one by figure ID (`sky_figure_pages` in `constants/stars/constellations.py`). `iau` alone names no page: a Bucur figure can lie inside the constellation that it names.

  `labels` is the name of the figure by site language, in the languages that have one. A figure with an IAU page has the Wikidata name, and `en`. Another figure of a Stellarium culture has Stellarium's translation, found as Stellarium finds it: by the name's `english` and its `context` (msgid and msgctxt in the `stellarium-skycultures` catalogue, `zh_CN` for `zh`, `pt` and never `pt_BR` for `pt`). A value equal to the English or a native name is left out, and so is one in `WRONG_SENSE` (`skycultures/translations.py`). A culture flagged `no-derivatives`, `no-licence` or `tk-labels` has no translations: a translation is an adaptation of the culture's names. A figure with a page fills its gaps from the Wikidata label of the page, and keeps a value equal to a native name, as the page reads it. A client shows a native name in the reader's script first, then `labels`, then the English name.

  A Stellarium asterism with `ray_helper` is a line that helps find stars (a pointer), which Stellarium draws apart from the figures.
- **`names`.** The star names of the culture: `member` is a member index, and `names` lists its names with the same fields as a figure's.

| `reason` | |
|----------|-|
| `deep-sky` | a cluster, nebula or galaxy; the registry has no deep-sky objects yet |
| `solar-system` | the Sun, the Moon or a planet |
| `not-in-registry` | a HIP, Gaia DR3 or HD number with no live ID: not in Hipparcos 2007, or a Gaia source with no 5σ parallax that SIMBAD's list of stars does not hold, or with `fidelity_v2` under 0.5 that no other catalogue matches |
| `component` | a component letter other than A after a HIP number |
| `not-in-simbad` | SIMBAD has no object with this identifier |
| `no-star-number` | a SIMBAD star with no HIP, Gaia DR3 or HD number |
| `unknown-designation` | a designation of no known form |

The matching runs at ingest: the `extrasolar` target of `space-map-ingest` ends with it, and `--targets skycultures` runs it alone. A HIP number goes through the registry's `hip/2007` catalogue ids and a Gaia DR3 source_id through `gaia/dr3`. Bucur names stars by SIMBAD identifier; SIMBAD gives the star's HIP number, else its Gaia DR3 or HD number, else the HIP number of the star system that holds it.

A star's page reads the figures of the star from one small file, and no culture file. There are `star_shards` of them, at the pattern `star_figures` with `shard` = the star's ID modulo `star_shards`:

```json
{
  "token": "495f0eea0c17aae7",
  "stars": {
    "22821649": {
      "modern_iau": [{ "names": [{ "native": "Orion", "english": "Hunter" }], "labels": { "fr": "Orion" }, "slug": "Ori" }],
      "aztec": [{ "names": [{ "english": "The New fire" }] }]
    }
  }
}
```

Each star that a figure's lines or `group` use has its figures by culture key, in the culture's order, with `names` (`native`, `english` and `pronounce` only), and `labels` and `slug` as in a culture file. No ray helper is here. The shards hold all cultures: a client leaves out what it does not show, by `group` and `distribution` of the table. A star that is in no figure is in no shard. In the export of 2026-10-31, 3,824 stars are in 33,927 figure memberships, and a shard is 10 to 32 KB, 1.4 MB in all.

The token of `skycultures` covers all its files: SHA-256 over each file's path, a zero byte and the SHA-256 of its JSON with `token` set to 16 zeros (`"0000000000000000"`), as for the containers. Each file's `token` field holds the token; a client checks it as it checks a container header.

## Planets (`planets`)

The planets and the substellar companions up to 60 Jupiter masses that the NASA Exoplanet Archive, exoplanet.eu and the Open Exoplanet Catalogue (OEC) list as confirmed or controversial around a star. Candidates, retracted objects and free-floating objects are not in it. A planet's page is `/x/{host}/b/{n}`: `host` is the extrasolar ID of the star it orbits, and `n` its number within that host, from 1. A number is never given twice: a planet that every catalogue drops retires, and its number then is a 404. A number can become an alias of another planet: when two numbers turn out to be one planet, or when the planet's host changes, which gives the planet a number on its live host. A host changes when its ID merges into another ID, when a catalogue moves the planet, or when a paper in the cited table below moves it. The old page then redirects.

Where a catalogue puts a row on the wrong star, or lists one planet twice, a cited table corrects it (`constants/stars/planet_hosts.py`): the row takes the star of its paper and that star's ID, or joins the planet that the paper names. A row that takes a star loses the star columns of its catalogue row, also when they are right. An orbit value that the ingest computes then uses the mass of the new star, and is missing when that star has none. A star row with a wrong position, or with a name that resolves to no object, takes the key and position of its star.

The planets of one planetary system share one file, keyed by an ID (`system`). For a host in a star system (System, above), that is the root of its system, which can be a resolved system with an ID of table 3: α Cen's file holds the planets of Proxima and of α Cen B. For a single star, it is the host. For other hosts that a planet catalogue puts in one system, it is the first star in OEC's hierarchy that has planets, else the star without a component letter or with `A`, and the root of that star's system when the star is in a star system. So a planet around each star of a binary is in one file, and each orbits its own host. A planet around both stars of a binary (P-type) orbits the node that holds both: a point when Gaia sees one source for the pair (Kepler-16), else the resolved pair, whose ID is of table 3 (`/x/<pair>/b/<n>`). The resolved pair is not drawn as a star, and its planets are drawn at the place of one of its stars (System file, below). The hosts of one system can be in two regions of the sky, and their file is the same.

### Index

`planets/index.json.gz` is gzip around one JSON object:

```json
{
  "token": "3f0c…",
  "hosts": [
    { "id": 27424668, "system": 27424668, "planets": [1], "position": [-0.4732, -0.3644, -1.1576], "outer_orbit": 0.04848 },
    { "id": 564339647, "system": 27424668, "planets": [1], "position": […], "outer_orbit": null },
    { "id": 1234567890, "system": 1234567890, "planets": [1, 3], "position": null, "outer_orbit": 1.2 }
  ],
  "aliases": { "1234567890/2": [1234567890, 1], "987654321/1": [1234567890, 3] }
}
```

- `hosts`: every host with a planet, sorted by `id`. A key with no planets of its own is in its system file and not here.
- `system`: the key of the host's system file.
- `planets`: the live numbers of the host, ascending.
- `aliases`: every alias number, keyed `"{host}/{n}"`, with the live planet it leads to as `[host, n]`. The target can be on another host (the second example: host 987654321 merged into 1234567890). The target is always a planet that the index lists, so there is one redirect; an alias whose end is not served is left out (a 404). The host of an alias key can be missing from `hosts`: a merged ID has no live planets.
- `position`: in parsecs, in the frame of the render tree (ICRS axes, origin at the barycentre, J2016.0), the float64 position that the tree build computes for the host. The node stores it as its centre plus a float32 offset, so the drawn point is off by up to half · 2^-24 of the node. Null when the host has no distance (not drawn). A resolved star system has the position of one of its points (System file, below).
- `outer_orbit`: in AU, the largest semi-major axis of the host's planets; null when none has one.

To find a planet `/x/{host}/b/{n}`: load the index once; when `aliases` has `"{host}/{n}"`, redirect to `/x/{target host}/b/{target n}`; else find the host in `hosts` and check that `n` is in its `planets` (else a 404); load `planets/{system}.json.gz` and take the planet with that `host` and `number`.

### System file

`planets/{key}.json.gz`, with `key` the key ID of the system:

```json
{
  "token": "3f0c…",
  "system": 27424668,
  "hosts": [ { "id": 27424668, "name": "Proxima Centauri", "…": "…" }, { "id": 564339647, "…": "…" } ],
  "planets": [ { "host": 27424668, "number": 1, "name": "Proxima Cen b", "…": "…" }, { "host": 564339647, "number": 1, "…": "…" } ]
}
```

`hosts` has the key first, then the other hosts by ID. `planets` is sorted by host, then number. A float with no value is `null`. A host or a key that is a resolved star system has no point, so the render tree does not draw it as a star. Its record has its Metadata values, `ra` and `dec` from its System row at `epoch` 2016.0, and the `position` and `distance` of its primary point, else of the first of its member points that the render tree draws, in member order. Every other field is null, `placement` too. Its planets are drawn about that place. With no such point, `position` and `distance` are null.

A host:

| Field | | |
|-------|-|-|
| `id` | number | extrasolar ID |
| `name`, `name_source` | string | the Metadata name and its source. It is the global name of the host's page (`export/names.py`) |
| `names` | object | the name of the host's page in each language where it differs from `name`, by language code: the Wikidata labels of a star with an object entry; else empty. A client shows `names[lang]`, else `name` |
| `class` | string | the Metadata class: `star`, `brown dwarf`, `white dwarf`, `pulsar`, or `binary star` and `multiple star` for a node of a star system |
| `cross_ids` | list | the Metadata cross-ids, each `{catalogue, release, catalogue_id}` |
| `planets` | list | its live numbers; empty for a key with no planets |
| `placement` | string | how its distance is known, by the steps of the render tree: `parallax` (its own, or a 5σ orbit parallax), the `distance_source` of its distance group (as `literature`, `bailer-jones-2021` or `star-systems`), `catalogue distance`, `parallax with fidelity under 0.5`, or null when the render tree does not draw it: it has no distance, or it is a resolved star system |
| `position` | [x, y, z] | as in the index (pc) |
| `distance` | number | pc, as the render tree has it: `1000 / parallax_nss` with a 5σ astrometric orbit solution, else `1000 / parallax` for `parallax` and `host_distance` for `catalogue distance` |
| `ra`, `dec`, `epoch` | number | the Point source astrometry: degrees, ICRS at `epoch` (Julian year) |
| `teff`, `teff_source` | number, string | K: `host_teff` (the catalogue), else `teff_gspphot` (`gaia-dr3`) |
| `radius`, `radius_source` | number, string | solar radii: `host_radius`, else `radius_gspphot` (`gaia-dr3`) |
| `mass` | number | solar masses, `host_mass` |
| `metallicity` | number | dex, `host_metallicity` |
| `spectral_type` | string | `host_spectral_type` |
| `bp_rp` | number | Gaia BP − RP, when Gaia measured both |
| `catalogue`, `catalogue_name` | string | `host_star_source`, and the star's name in that catalogue (`host_name`) |

A planet:

| Field | | |
|-------|-|-|
| `host`, `number` | number | its page `/x/{host}/b/{number}` |
| `star` | id | the star that a brown dwarf record also is, a member of its star system (System, above); else null |
| `object` | bool | true when the site's object bundles hold an entry `x-{host}-b-{number}` for the planet ([objects.md](objects.md)): when it has a `wikidata/qid` id |
| `name` | string | the global name of the planet's page (`export/names.py`), with an object entry or without one: the IAU name (`iau-nameexoworlds`); else the catalogue name (`designation`) of a `controversial` planet, whose letter nobody agrees on, and of each planet whose `letter` another planet of its host has, counting every planet of the host, as a page name points to one page; else the global name of its host's page and its letter (`Proxima Centauri b` for `Proxima Cen b`). A planet with no letter keeps its catalogue name. `designation` keeps the catalogue name |
| `name_source` | string | the source of the planets table name: `iau-nameexoworlds`, else the catalogue of the designation |
| `names` | object | the name of the planet's page in each language where it differs from `name`, by language code: the host's name in that language and the letter. An IAU name or a catalogue name has none. A client shows `names[lang]`, else `name` |
| `designation` | string | the archive's name, else exoplanet.eu's, else OEC's |
| `letter` | string | `b`, `c`, … or null. A letter of a star goes to its first planet, by the source order of the catalogues. Another planet with that letter takes another letter of its catalogue rows if one is free, else null. exoplanet.eu's capitals (`GJ 1001 B`) are no letters. A row with a host from a paper has none |
| `aliases` | list | the IAU name and every catalogue name of the planet; for a `controversial` planet also its host's name and its letter |
| `cross_ids` | list | `{catalogue, release, catalogue_id}`: the archive's `objectid`, exoplanet.eu's name, OEC's first name, `iau/nameexoworlds/<name>`, and `wikidata/qid/<QID>`. Each ingest links the Wikidata items with an article in one of the site's languages again: an item names a planet by its NASA archive name (P5667), which is the planet's designation, or by its exoplanet.eu page (P5653). An item whose ids name two planets names none, and of the items that name one planet, the item with the most articles keeps it, then the lowest QID |
| `class` | string | after the IAU: `planet` (under 13 MJ, mass ratio to its star under 2/(25+√621) ≈ 0.04), `brown dwarf` (13 MJ or more), `sub-brown dwarf` (under 13 MJ with a larger mass ratio) |
| `class_basis` | string | `true mass`, `minimum mass`, `estimated mass`, `no mass` |
| `mass_ratio` | number | planet over central object, null without a star mass |
| `status` | string | `confirmed` or `controversial` |
| `elements` | object | the orbit in the scene's frame (below), or null when the planet has no semi-major axis: the client draws it as a fixed dot |
| `values` | object | every other value of the planets table that the planet has (below) |
| `sources` | object | the source of each group: `status`, `discovery`, `orbit`, `sky`, `mass`, `radius`, `physical`, `atmosphere`, `stellar`, `binary` → `nasa-exoplanet-archive`, `exoplanet-eu`, `open-exoplanet-catalogue`, or `gaia-dr3` for `sky` |
| `assumed` | list | the values that are defaults, not published: `eccentricity` (0, also an exact 0 with no error), `omega` (90°), `inclination` (a transiting planet of the same host, else 90°), `node` (one angle per system, from a hash of the ID of its key), `periastron_time` (J2000.0: the position on the orbit is unknown) |
| `estimated` | list | values that a catalogue estimates (the archive's "Calculated Value", a mass–radius relation, exoplanet.eu's "Theoretical") |
| `computed` | list | `period` or `semi_major_axis` from Kepler's third law, or `semi_major_axis` from an angular separation and the distance |
| `limits` | list | `<name><` for an upper limit, `<name>>` for a lower limit |
| `families` | list | the published families of the planet, as slugs in the order of `families` of `planets` in `metadata.json`, with their parents (Families, below); empty when none |
| `families_estimated` | list | the families that need an estimate and are not in `families` |

`values` has the columns of the planets table with a value, by these names and units: `discovery_method`, `discovery_year`, `discovery_facility`; `period` (d), `semi_major_axis` (AU), `eccentricity`, `inclination` (deg), `omega` (deg), `periastron_time` and `transit_time` (JD, as published, mostly BJD), `time_system` (the archive's system of the transit time: `BJD`, `BJD-TDB`, `HJD`, `JD`, …); `node` (deg), `node_inclination` (deg) and `node_solution` (Gaia's `nss_solution_type`); `mass` (Jupiter masses), `mass_kind` (`true`, `minimum`, `estimate`); `radius` (Jupiter radii); `equilibrium_temperature` (K), `insolation` (Earth's), `density` (g/cm³); `molecules` (a list); `star_mass` (solar), `star_radius` (solar), `star_teff` (K), `star_metallicity` (dex), the star of the fits; `binary_type` (`S-type` or `P-type`). A measured value `x` can have `x_error_upper` and `x_error_lower`, both positive. The defaults of `assumed` are in `values` too. `eccentricity` is as published, also when it is outside [0, 1).

### Families

The export tags each planet with the planet families of `constants/planets/families.py`, from the planet's `values`, its flags and its host's `class`. A family adds its parents (a hot Jupiter is also `gas-giant` and `giant-planet`). There is no root family: the families without a parent are below the Planets category page (`cat-planets`, groups.md). A family is in one list only: `families` when the values that its rule reads are measured, else `families_estimated` when the rule needs an estimate. Only the class `planet` gets families: a brown dwarf or a sub-brown dwarf has empty lists.

The rules, in Earth masses (M⊕) and radii (R⊕), with 1 MJ = 317.828 M⊕ and 1 RJ = 11.209 R⊕:

| Family | Parent | Rule |
|---|---|---|
| `terrestrial-planet` | — | R ≤ 1.5 R⊕; when the radius does not decide, M < 2 M⊕ |
| `sub-earth` | `terrestrial-planet` | M < 1 M⊕ and R < 1 R⊕ |
| `mega-earth` | `terrestrial-planet` | M ≥ 10 M⊕, 2.1 ≤ R ≤ 5 R⊕, density above Earth's (5.51 g/cm³) |
| `super-earth` | — | 1.9 ≤ M ≤ 10 M⊕ and 1.25 ≤ R < 2 R⊕ |
| `mini-neptune` | — | 2 ≤ R < 3.88 R⊕ (Neptune's radius) |
| `super-puff` | — | M < 10 M⊕ and R > 3.88 R⊕ |
| `giant-planet` | — | M ≥ 10 M⊕ and R ≥ 3.88 R⊕ |
| `ice-giant` | `giant-planet` | giant planet, more than half (to 99 %) of its mass heavier than helium; no catalogue gives this, so only the Solar System planets have it |
| `super-neptune` | `giant-planet` | 20 ≤ M ≤ 100 M⊕ and 4 ≤ R ≤ 8 R⊕ |
| `hot-neptune` | `giant-planet` | 10 M⊕ ≤ M < 0.25 MJ, 3.88 ≤ R < 8 R⊕, period under 10 days |
| `gas-giant` | `giant-planet` | M ≥ 0.25 MJ and R ≥ 8 R⊕ |
| `super-jupiter` | `gas-giant` | gas giant, M > 2 MJ |
| `hot-jupiter` | `gas-giant` | gas giant, period under 10 days |
| `warm-jupiter` | `gas-giant` | gas giant, period 10 to 200 days |
| `cold-jupiter` | `gas-giant` | gas giant, semi-major axis above 1 AU |
| `jupiter-analogue` | `cold-jupiter` | gas giant, M ≥ 0.3 MJ, semi-major axis 3 to 12 AU |
| `eccentric-jupiter` | `gas-giant` | gas giant, eccentricity 0.1 or more |
| `puffy-planet` | `gas-giant` | gas giant, density at most Saturn's (0.687 g/cm³) |
| `ultra-short-period-planet` | — | period under 1 day |
| `circumbinary-planet` | — | `binary_type` `P-type` |
| `pulsar-planet` | — | the host's `class` is `pulsar` |
| `goldilocks-planet` | — | `insolation` in the conservative habitable zone of Kopparapu et al. 2014 for the star's Teff (2,600 to 7,200 K) |

The evidence:

- A value is measured when it is not in `estimated` or `assumed`. A computed period or semi-major axis is measured. An assumed value is never used: an assumed eccentricity makes no eccentric Jupiter.
- A limit `x<` puts the value between 0 and x, and `x>` above x. A limit decides a rule only when it puts the value wholly inside or outside the range. Else the other value of the rule can still decide.
- A minimum mass (`mass_kind` `minimum`) is a lower bound. It passes "M ≥ X" as published. For "M < X" it stands in for the mass, and the family is estimated. An upper limit on a minimum mass gives no bound.
- An estimated mass or radius is used only when neither the mass nor the radius is measured, and the family is then estimated. So a measured value stops the estimate of the other, in every rule.
- A rule on mass and radius is published when each of the two that decides it is in range.
- A density is the measured `density`, else one from a measured mass and radius. It never comes from an estimate, so an estimated radius makes no puffy planet.
- A rule of several parts is published when all parts are published, and estimated when one part is estimated and no part fails.
- The Teff of `goldilocks-planet` is `star_teff`, else the host's `teff`, and the star's radius is `star_radius`, else the host's `radius`. With no catalogue insolation, the insolation comes from the star's radius, the Teff and `semi_major_axis`, and the family is estimated.

### Elements

`elements` is the orbit of the planet around its host on the ecliptic and mean equinox of J2000, the frame of the scene, with the obliquity 23.4392911° (`elements_frame` in `metadata.json`):

| Field | |
|-------|-|
| `a` | semi-major axis (AU) |
| `e` | eccentricity |
| `i` | inclination to the ecliptic (deg) |
| `om` | longitude of the ascending node on the ecliptic (deg) |
| `w` | argument of periastron (deg) |
| `ma` | mean anomaly at `epoch` (deg) |
| `n` | mean motion, 360 / period (deg/day); 0 when the period is unknown, and the planet then stays at its place at `epoch` |
| `epoch` | JD TDB |
| `phase` | what fixes `ma`: `transit`, `periastron`, or `assumed` when the position on the orbit is unknown |
| `replaced` | present only when an element is not as published: `["eccentricity"]` when the published eccentricity is outside [0, 1), and the orbit is drawn with `e` 0 |

These are the fields of the frontend's `OrbitalElements` (`orbitalElementsToPositionJD`), relative to the host. The conversion from the catalogues:

- **The plane of the sky.** The catalogues give `inclination` i to the plane of the sky, `node` Ω as a position angle from north through east, and `omega` ω. The axes are north, east, and the line of sight away from us: the ascending node is where the body moves away from us, and an orbit with i < 90° turns from north to east. The export turns this plane at the host's direction (its `position`, else its RA and Dec) into the ecliptic, once per planet.
- **ω is the star's.** Most radial-velocity and transit fits give the argument of periastron of the star; the planet's is ω + 180°, with the same Ω and i. The elements use ω + 180°, except for a planet found by imaging (`discovery_method` `Imaging`), whose ω is fitted to the planet's own positions and is taken as is. ω and Ω are reduced to [0°, 360°).
- **Inclination.** `inclination`, but when it is assumed and the sky solution has one (`node_inclination`, from Gaia or OEC), that one.
- **Node.** `node`: Gaia's photocentre orbit (in [0°, 180°), as astrometry gives it) when its period matches the planet's within 5%, else OEC's, else the assumed angle of the system.
- **Phase.** With a `transit_time`, `epoch` is that time and `ma` is the mean anomaly of the inferior conjunction, where the planet is nearest us (ω + ν = 270° for the planet's ω): for a transiting planet the planet is in front of its star at `epoch`. Else `epoch` is the `periastron_time` and `ma` is 0. A planet with neither has the assumed periastron at J2000.0, and `phase` is `assumed`. Times are as observed from the solar system, so light time is not removed; the time systems of the catalogues differ by minutes and all are taken as JD TDB.

### Token and checks

The token of `planets` covers the index and every system file, as for the sky cultures: SHA-256 over each file's path, a zero byte and the SHA-256 of its JSON with `token` set to 16 zeros. Each file's `token` field holds it, and a client fetches each file with `?v={token}`. A file whose token is not the one in `metadata.json` comes from another export: the client shows the reload prompt.

The export refuses to publish when a planet number is given twice, when a host is in two systems, when a host or a system key is not a live ID, has no Metadata row, or has neither a Point source nor a System row, when the file of a host in a star system, or a file keyed by a star in one, is not keyed by the root of that system, or when a planet or alias that the served index lists is gone and the registry's Planets part does not say it retired or became an alias, and its host is still live.

### Sitemap

The site's sitemap lists the page of every planet and of every planet host that this export serves, from the planet index and the system files: see [sitemap.md](sitemap.md). An alias number has no page in it.

## Systems index (`systems`)

`systems/index.json.gz` lists each root of a star system that holds a held star, a drawn orbit or a planet host: the systems that a page draws up close. Search makes no document from it: a root or held star is in search only when its object entry has a Wikipedia extract, as a star's is, and that document then takes the facts of the index. A client can read it to list these systems.

```json
{
  "token": "9a41…",
  "systems": [
    {
      "id": 20657986,
      "name": "Kepler-16",
      "class": "binary star",
      "stars": 2,
      "held": [{ "id": 54212418, "name": "Kepler-16 A" }, { "id": 591083330, "name": "Kepler-16 B" }]
    }
  ]
}
```

- `systems`: sorted by `id`, the root's ID. `name` and `class` are its Metadata `name` (null when it has none) and `class`; `stars` is its System `stars`.
- `held`: the held stars of the system that have a name, sorted by ID.

The token of `systems` is the SHA-256 of the file's path, a zero byte and the SHA-256 of its JSON with `token` set to 16 zeros, as for the planets.

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
  "families": [
    { "slug": "a-type-main-sequence", "wikidata": ["Q471805"], "parents": ["main-sequence"], "published": 5469, "estimated": 919817 },
    "…"
  ],
  "objects": {
    "star": { "count": 180980312, "size_bytes": 54754808312, "sources": { "gaia-dr3": 180973358, "rybizki-2022": 180970832, "…": "…" } },
    "star_system": { "count": 1288914, "size_bytes": 40118020, "sources": { "star-systems": 1288914 } },
    "planet": { "count": 7581, "size_bytes": 7136718, "sources": { "nasa-exoplanet-archive": 6444, "…": "…" } }
  },
  "skycultures": {
    "token": "495f0eea0c17aae7",
    "file": "skycultures/{key}.json.gz",
    "star_figures": "skycultures/stars/{shard}.json.gz",
    "star_shards": 64,
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
        "group": "modern",
        "labels": { "fr": "Moderne (chinoise)", "…": "…" },
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
        "stand_ins": 0,
        "unresolved": 11
      },
      "…"
    ],
    "credits": [{ "name": "Stellarium sky cultures", "…": "…" }, { "name": "Constellation line figures in sky cultures across the world", "…": "…" }, { "name": "SIMBAD astronomical database", "deep_sky": true, "…": "…" }]
  },
  "planets": {
    "token": "3f0c…",
    "index": "planets/index.json.gz",
    "system": "planets/{key}.json.gz",
    "systems": 5801,
    "hosts": 5809,
    "planets": 7595,
    "units": { "position": "pc", "distance": "pc", "a": "AU", "angles": "deg", "n": "deg/day", "epoch": "JD TDB" },
    "elements_frame": "ecliptic and mean equinox of J2000, the planet around its host; obliquity 23.4392911 deg",
    "families": [
      { "slug": "terrestrial-planet", "wikidata": ["Q128207"], "parents": [], "published": 1065, "estimated": 29 },
      { "slug": "hot-jupiter", "wikidata": ["Q382979"], "parents": ["gas-giant"], "published": 798, "estimated": 2 },
      "…"
    ],
    "frame": "ICRS equatorial axes, origin at the solar system barycentre, epoch J2016.0",
    "distribution": "non-commercial"
  },
  "systems": {
    "token": "9a41…",
    "index": "systems/index.json.gz",
    "systems": 32310,
    "held": 58262,
    "distribution": "non-commercial"
  },
  "credits": [
    { "name": "Gaia Data Release 3", "organisation": "ESA/Gaia/DPAC", "source": "https://www.cosmos.esa.int/web/gaia/dr3", "license": "CC BY-NC 3.0 IGO", "attribution": "…", "citation": "…" },
    "…"
  ]
}
```

- `tables`: keyed by slug. `number` is the table number in the IDs, null for Metadata. `max_rows` is the split threshold. `rows` counts the rows of all tiles.
- `trees`: keyed by name; `mw` is the Milky Way.
- `families`: the star families in bit order: entry `n` is bit `n` of the Metadata masks. `wikidata` holds the topic items of the family, `parents` the slugs of the families that contain it (empty on the root), `published` and `estimated` count the stars with the bit set in `families` and in `families_estimated`. The brightest stars of each family are in `families.json` (below).
- `objects`: the census of the export for `/about/data` ([about-data.md](about-data.md)), by kind. Each ID counts once. A node of a star system is no star. `star_system` is a node: a live ID of table 3 or a point that holds two or more stars, each of class `binary star` or `multiple star`. `star` is any other live ID of table 1, or a held star, which has no Point source row. `planet` is a row of the planets table. `size_bytes` holds the files of the kind: Point source, Binary orbit and the render tree for the stars, the planet files for the planets, the systems index for the star systems, and the Metadata and System tiles split between the stars and the star systems by their rows. The sky cultures, `metadata.json` and `families.json` are not counted. `sources` counts the objects that each source feeds with at least one value, most objects first. The source of a value is the source column of its group, with another pass of a catalogue as that catalogue (`gaia-dr3-named` is `gaia-dr3`; `simbad-hip` and `simbad-parallax` are `simbad`). A group of a star table that a pass carries for a catalogue of its own counts for that catalogue: `xgboost` for `andrae-2023`, `pastel` for `pastel-2020`, `apogee` for `apogee-dr17`, `lamost` for `lamost-dr10`, `gcvs` for `gcvs-5.1`, `spicy` for `spicy`, `xhip_metallicity` for `xhip`, `fidelity` for `rybizki-2022`, `orbit` and `masses` for `gaia-dr3-nss`. Wikidata is left out: every object with an item has an object entry, and the main export counts the items from the entries.
- `distribution`: who may serve the data, with the meaning that it has on a texture ([textures.md](textures.md)): the strictest tier of the sources whose values the files hold. Gaia DR3 is CC BY-NC 3.0 IGO, and every table and tree holds Gaia values. The star system catalogues reach Metadata (`system`, the classes and names), Point source (the system distance, `member`), System, the render tree and the planet files: the WDS and the MSC state no licence, so they are `non-commercial`, and El-Badry, Rix & Heintz 2021 is CC BY 4.0, though it repeats Gaia EDR3 values, which come from Gaia here. So all are `non-commercial`.
- `credits`: each source with `name`, `organisation`, `source` (URL), and `license`, `attribution` and `citation` when known: Gaia DR3, Rybizki et al. 2022, the binary orbits and masses of Arenou et al. 2023, Andrae, Rix & Chandra 2023, PASTEL, SIMBAD, APOGEE DR17, the LAMOST DR10 M dwarfs of Zhang et al. 2025, the LAMOST DR10 catalogue of M stars, GCVS 5.1, SPICY, the ATNF Pulsar Catalogue with the reference and URL that it asks for, Hipparcos I/311 and I/239, XHIP V/137D, the distance catalogues (Reylé et al. 2021, the UltracoolSheet, Hunt & Reffert 2024, the LMC and SMC distances of Pietrzyński et al. 2019 and Graczyk et al. 2020, Bailer-Jones et al. 2021), the star system catalogues (the Washington Double Star Catalog with the acknowledgement it asks for, Tokovinin's Multiple Star Catalogue, the wide binaries of El-Badry, Rix & Heintz 2021; the orbit catalogues ORB6, with the WDS acknowledgement, and SBX, CC BY 4.0), one credit for the papers of the literature table (its `source` is the table in the repo; each star's object entry cites its own papers), the IAU Catalog of Star Names, Wikidata; with planets also the NASA Exoplanet Archive (its acknowledgement, and the DOI of Planetary Systems Composite Parameters, 10.26133/NEA13), exoplanet.eu (CC BY 4.0), the Open Exoplanet Catalogue (MIT) and the IAU's NameExoWorlds. The planet catalogues also fill the host rows of Point source and Metadata, so their credits are in this list. Each catalogue has one credit, and its `source` names it.
- `planets`: absent when the registry has no planets table. `index` and `system` (a pattern with `{key}`) are paths. `systems`, `hosts` and `planets` count the system files, the hosts with planets and the planets. `frame` is the frame of the positions, `elements_frame` that of the elements. `families` lists the planet families in the order of the planet records' lists, as the star families are listed: `wikidata` holds the topic items of the family, `parents` the slugs of the families that contain it (empty on a family without a parent), `published` and `estimated` count the served planets with the family in `families` and in `families_estimated`. `distribution` is `non-commercial`: the host positions come from Gaia DR3.
- `systems`: the systems index. `index` is its path; `systems` and `held` count its systems and held stars.
- `skycultures`: absent when the export had no matched cultures. `file` is the path pattern, `star_figures` and `star_shards` lead to the figures of a star (Sky cultures, above), and `cultures` lists each culture with its file:
  - `licence`: the licence of the culture's data and illustrations as it states it (`applies_to` is `all`, `data` or `illustrations`; the files hold no illustrations yet), and the tier that this licence alone allows. A culture that states no licence has no parts and the tier `non-commercial`, with the flag `no-licence`. A statement that the ingest cannot read gives the tier `undecided`, which no client may serve.
  - `distribution`: the tier of the file, the strictest of the culture's licence and of Gaia DR3 (`non-commercial`), because the positions come from Gaia. `undecided` stays `undecided`.
  - `flags`: `no-derivatives` (a CC ND licence: only unchanged copies), `non-commercial` (a CC NC licence or a Traditional Knowledge NC label), `tk-labels` (Traditional Knowledge labels add terms to the licence), `no-licence` (the culture states no licence, so it is non-commercial), `unknown-licence`.
  - `group`: the region group of the culture picker, from `SKY_CULTURE_REGIONS` in `constants/stars/cultures.py`: `modern`, `northern-africa`, `southern-africa`, `northern-america`, `central-america`, `south-america`, `eastern-asia`, `northern-asia`, `south-eastern-asia`, `southern-asia`, `western-asia`, `eastern-europe`, `northern-europe`, `southern-europe`, `western-europe`, `australasia`, `melanesia` or `polynesia`. `region` and `subregion` keep the words of the dataset. `null` on a culture that a picker leaves out (`modern`, `modern_hlad`, `modern_rey`, `modern_st`, `modern_sternenkarten`: western near-copies of `modern_iau`).
  - `labels`: the name of the culture by site language, for the languages that have one of their own. The others, and English, read `name`. A Stellarium culture has Stellarium's translation (`stellarium-skycultures-descriptions`), fixed by hand where it does not work (`SKY_CULTURE_NAME_FIXES`). A gap, and each Bucur culture, reads the hand table `SKY_CULTURE_LABELS` or a Wikidata label, fixed by hand where one does not work as a name; an edition reads the translated name of its culture, then its edition; a culture with no matching item has none. A people's label names the culture only: it does not make that item the culture's astronomy.
  - `packaged`: false for a culture that Stellarium leaves out of its standard package.
  - `credit`: the culture's own credit: its source at the pinned commit, its licence, and for Stellarium `authors`, the plain names of the people that the culture's description names as its makers, with no Markdown, addresses or links.
  - `figures`, `members`, `positioned` (members with a position), `stand_ins` (those that are stand-ins) and `unresolved` (members with no ID, sky points left out).
  - `credits` of the section: Stellarium, Bucur's dataset, SIMBAD, which matched Bucur's identifiers, and the catalogues of the deep-sky stand-ins (Hunt & Reffert 2024, Baumgardt et al., HECATE, OpenNGC). `deep_sky: true` marks a credit that places these stand-ins (SIMBAD and those four); a culture with a figure that draws a stand-in credits these too.

## `families.json`

```json
{
  "brightest": {
    "a-type-main-sequence": [{ "id": 20593262, "name": "Vega" }, "…"],
    "…": "…"
  }
}
```

The main export reads this file for the family pages ([groups.md](groups.md)). Clients do not read it, so it is apart from `metadata.json`, which a client fetches at each load. The export writes both files into the same staging directory, so they come from the same run. A full export stops when the served export has no `families.json`: run the extrasolar export first. Its IDs and names come from the Metadata tiles, so it is `non-commercial`, as they are.

`brightest` has a key for each family with a listed star, in bit order, except the root. Every star with a published family is in the root, so the root lists no stars. Each list holds the 20 brightest stars with the bit set in `families`, brightest first, each with its `id` and the `name` of its Metadata row (null when the row has none). The brightness is the G of the render tree (`MAG_SOURCES` in `export/extrasolar/render.py`): Gaia G, else SIMBAD G, else G estimated from Hipparcos or from SIMBAD V and B − V, else the G or V of an exoplanet catalogue. A held star takes the `g_mag`, else the `v_mag`, of its member in its node's `members`, with no estimate. A held star with neither stays in its families and their counts, but no list holds it, and the export logs how many there are. Any other star without a brightness comes last, and a tie goes by ID.

## Sizes

The export of 2026-10-23 (registry ingest 2, 180,949,689 IDs, all live):

| Part | Files | Size | Median file | p90 | Max |
|------|-------|------|-------------|-----|-----|
| Metadata tiles (`max_rows` 7,500) | 52,206 | 4.3 GB | 73 kB, 3,063 rows | 133 kB | 175 kB |
| Point source tiles (`max_rows` 900) | 437,445 | 32.7 GB | 64 kB, 349 rows | 125 kB | 162 kB |
| Split tables | 2 | 1.7 kB and 11.6 kB (69,604 and 583,256 bits) | | | |
| Render nodes | 61,487 | 2.8 GB | 24 kB, 1,372 rows | 141 kB | 160 kB |
| Render IDs | 61,487 | 0.63 GB | 5 kB | 34 kB | 42 kB |

The export of 2026-10-26 (a new registry, 180,980,643 IDs) adds both FLAME groups and the metallicity groups to Point source: 437,532 tiles, 47.0 GB, median 92 kB and 349 rows, p90 178 kB, max 237 kB, about 260 B per row.

Binary orbit tiles (`max_rows` 300), an estimate from the tile writer and the split rule over the 394,046 orbits of the positionable stars: 3,045 tiles, 118 MB, median 34 kB and 112 rows, p90 64 kB, max 111 kB.

System tiles (`max_rows` 1,500), an estimate from the tile writer and the split rule over the 1,697,320 nodes of a dry run of the tree builder on registry ingest 1 (1,678,427 systems, 3,396,784 members): 2,385 tiles, 138 MB, median 51 kB and 624 rows, p90 94 kB, max 124 kB, about 82 B per row. That estimate is from before the held stars and the `distance`, `orbit` and `star` columns.

The systems index, an estimate from a dry run of the tree builder: 32,310 roots with a held star or a drawn orbit, before the roots of planet hosts, and 58,262 named held stars.

The sky cultures of registry ingest 4 (Stellarium at `0d956aa`, Bucur at `711e069`): 101 culture files (64 from Stellarium, 37 from Bucur) and the international names, 1.76 MB together. The median culture file is 3.7 kB; the largest are `chinese` (166 kB, 312 figures, 3,079 members) and `modern_chinese` (141 kB). 4,820 of the 4,864 stars of all cultures have a position.

A test export of 2026-10-25 (about 7,600 planets on 5,800 hosts): about 5,800 system files, 6.8 MB together, median 1.2 kB, largest 3.6 kB; the index 256 kB.

A full render node of 10,000 stars is about 143 kB, of which the float32 positions take about 107 kB. 180,923,672 stars are in the tree, at depths 0 to 14. A plain octree gives 61,487 nodes against a minimum of 18,093; 7,761 nodes are full and 26,246 hold under 1,000 rows.

With a limit of 7.5 mag, a client at the barycentre loads 59 nodes and 581,094 stars by the loading rule above. At 10 pc from it, it loads 57 to 62 nodes, and at 1 kpc, 22 to 47 nodes (0.21 M to 0.45 M stars), depending on the direction.

## Checks before the files go live

The export builds into `v1/.x-staging/` and replaces `v1/x/` only when all checks pass:

- no ingest of the registry has merges that no one has reviewed (`space-map-extrasolar review`);
- every row holds an ID that the registry has, with the status that the row shows (live, or alias for an alias row), and every alias target is live;
- every ID that the previous export serves is still served with all its catalogue ids, or is an alias or retired in the registry. The `wikidata/qid` ids are not checked: each ingest links the Wikidata items again, so an item can move to another star. The previous export stands for the live site until the serving is decided;
- the matched sky cultures come from the registry ingest that the export reads. Each extrasolar ingest matches them at its end, so this fails only when that step failed; `space-map-ingest --targets skycultures` matches them again;
- the star systems hold together. A System ID has one row; a member star has no System row, a member node has one and names this node as its parent, and a node's parent lists it; an ID is a member of one node at most; the parents of a node lead to its `root` with no cycle, and `depth` counts the steps; only a root has a `tree`, and it holds every node with that root as their rows give them; a node's primary is in its system. In Metadata, every node and member star has a live row whose `system` is its root (null for the root itself), every node has bit 3 of its `mask`, and no other ID has a `system` or bit 3. These checks run before the tiles are written. The IDs of the systems are under the rule of every ID above;
- the planet checks (see Planets, "Token and checks").

A failed run leaves the served export as it was.

The export holds a shared lock on `registry/lock` for the whole run, and an ingest holds the same lock exclusively. So an export does not start while an ingest runs, an ingest does not start while an export runs, and every file comes from the registry state that `registry` in `metadata.json` names.
