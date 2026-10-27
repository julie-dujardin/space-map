# Extrasolar objects (`v1/x/`)

The objects outside the solar system: their record tiles, one tree per table, the Milky Way render tree, the constellation figures of the sky cultures, and the exoplanets with one file per planetary system. `space-map-export --only extrasolar` builds them from the extrasolar registry and its tables. They are not part of the main export: the stars alone are over half a million files, and the host of the main export has a file limit. They are written to `space-map-extrasolar/v1/x/` and are served from their own base URL, `PUBLIC_EXTRASOLAR_URL`. Without that URL a client has no stars and no `/x/` pages.

An object has one ID for all its files. The ID, its URL form and its check are in the design of the registry: `id = serial·2^29 + table·2^24 + cell`, with `cell` the HEALPix level-10 nested cell (ICRS) and `table` the home table. A client decodes it with division, never with bit operators: `cell = id % 2^24`, `table = floor(id / 2^24) % 32`, `serial = floor(id / 2^29)`.

## Directory structure

```
v1/x/
  metadata.json                          (not gzipped) entry point: format, tokens, tables, trees, credits
  metadata/split.bin.gz                  split table of the Metadata tiles
  metadata/{level}/{pixel}.bin.gz        Metadata record tiles
  point-source/split.bin.gz              split table of the Point source tiles
  point-source/{level}/{pixel}.bin.gz    Point source record tiles (table 1)
  binary-orbit/split.bin.gz              split table of the Binary orbit tiles
  binary-orbit/{level}/{pixel}.bin.gz    Binary orbit record tiles (table 2)
  mw/node/{name}.bin.gz                  Milky Way render nodes
  mw/id/{name}.bin.gz                    the ID column of each render node
  skycultures/{key}.json.gz              a sky culture: figures, members and star names
  planets/index.json.gz                  every planet host: its system, planet numbers, place and outer orbit
  planets/{key}.json.gz                  one planetary system: its hosts and planets, with orbits in the scene's frame
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
| `name` | string | IAU proper name (the WGSN list, which holds the NameExoWorlds star names; a NameExoWorlds star name outside that list comes with the host rows), else for a planet host the name in its exoplanet catalogue, else the English label of its Wikidata item when that is no bare catalogue number ("T Tauri", "Teegarden's Star", "Gliese 105"), else a Bayer or Flamsteed designation with the Greek letter spelled out ("Alpha Canis Majoris"), a WR number, a GCVS name, the designation of the star system that the star is the brightest component of (unless the system is itself a star with other HIP or HD numbers), `HD n` or `HIP n` (the star's, else its system's), a SIMBAD NAME, a designation in a cluster where SIMBAD's main identifier is from a survey, SIMBAD's main identifier, or `Gaia DR3 n`. A star with a Gaia DR3 id takes `Gaia DR3 n` over a main identifier from a survey (2MASS, Tycho, UCAC, WISE …). A name has no SIMBAD prefix: no `NAME` and no object type (`V*`, `**`, `EM*`, `Cl*`). Where the object type is the whole catalogue acronym (`C* 2905`), the identifier keeps it |
| `name_source` | dict | the source of the name: `iau-wgsn`, `nasa-exoplanet-archive`, `exoplanet-eu`, `open-exoplanet-catalogue`, `wikidata`, `simbad`, `hipparcos-2007` (designations from XHIP), `hipparcos-1997`, `gaia-dr3`, `gaia-dr3-named` |
| `class` | dict | what the object is: `star` for every row now |
| `class_source` | dict | |
| `cross_ids` | cross_ids | every catalogue id of the object: catalogues `gaia/dr3`, `hip/2007`, `hd/1949`, `simbad/oid`, `iau/wgsn`, `wikidata/qid`, `literature/star` now. An object has at most one `wikidata/qid` id: of the items that reach one star, the item with the most articles in the site's languages keeps it, then the lowest QID. A `literature/star` id is the key of the star in the literature table of the repo (`constants/stars/literature.py`): `gaia/dr3/<source_id>`, `hip/2007/<n>` or `hd/1949/<n>` |
| `mask` | uint32 | bit `n` is set when data table `n` has a row for the ID |
| `object` | bool | true when the site's object bundles hold an entry `x-<id>` for the ID ([objects.md](objects.md)): today, when it has a `wikidata/qid` or a `literature/star` id |
| `alias_target` | id | null for a live ID |
| `families` | uint64 | the published families of the star: bit `n` is entry `n` of `families` in `metadata.json` (below) |
| `families_estimated` | uint64 | the families that need a Gaia DR3 estimate and are not in `families` |

An alias is a row at the alias's own cell with only `id`, `mask` 0 and `alias_target`, which is the live ID at the end of its chain: a chain A → B → C is written A → C. A retired ID has no row, and its URL is a 404. An alias whose chain ends at an ID that is not live has no row either.

#### Families

The export computes the two family masks from the Point source row and the Metadata class; the rules are in `constants/stars/families.py`. A star is in every family that its data supports, and a family adds its parents (a G-type main-sequence star is also `main-sequence` and `dwarf`). A row without a Point source row, such as an alias, has 0 in both. A client reads a mask as a `BigUint64Array` and tests bit `n` with `(mask >> BigInt(n)) & 1n`.

A published family comes from catalogued classifications only:

- the MK spectral type, the first of `simbad_sp_type`, `sp_type` (Hipparcos) and `host_spectral_type`. The letter and the luminosity class give the family (`K2 III` is `giant` and `red-giant`, `M4 V` is `red-dwarf`); a composite type gives its first star. A class without a luminosity class gives only the families of its letter: D (`white-dwarf`), W (`wolf-rayet`), C, R and N (`carbon-star`), S, MS and SC (`s-type-star`), L, T and Y. A white dwarf has no luminosity class: the V of `DAV` marks a pulsating star. `Ba` after an F to M type marks a `barium-star`;
- `simbad_otype`, one listed code each (`Mi*` is `mira-variable`, `Psr` is `pulsar`); candidate types give none. A stage that the object type gives joins the MK letter as a luminosity class does (`K0` with `MS*` is `k-type-main-sequence`);
- the Metadata class `white dwarf`, `brown dwarf` or `pulsar`.

An estimated family uses at least one Gaia DR3 estimate:

- the spectral type tag `spectraltype_esphs`, where the second digit of `flags_esphs` is 1 to 5. O, B and A count only for a star of the OBA golden sample (`in_oba_golden_sample`). `CSTAR` counts only with the digit 0, which marks the carbon stars that the validation confirmed;
- the FLAME stage, from `flame_spec` before `flame`, where the fit holds as the star panel shows it: a mass, and for a giant (first flag digit 1) a mass from 1 to 2 M☉. Below 420 is `main-sequence`, below 490 `subgiant`, then `giant`;
- `classprob_dsc_combmod_whitedwarf` over 0.5 (`white-dwarf`);
- `classlabel_espels`: `TTauri`, `HerbigStar`, `RedDwarfEmStar` (`red-dwarf`), `wC` and `wN` (`wolf-rayet`).

Each family states the spectral letter of a star, its stage, both or neither. A published family or MK value stops each estimate of what it states: a star typed `K2 III` gets no estimated letter or stage, and a star typed `K0` can get an estimated stage. An estimate joins the published value of the other: `MS*` with the Gaia tag K is an estimated `k-type-main-sequence`. A variable star states neither, so it stops nothing.

### Point source (table 1)

Gaia DR3, Hipparcos, SIMBAD, the literature table, the distance catalogues, the metallicity catalogues and the host stars of the exoplanet catalogues, with every field and its uncertainty. The columns come in groups. Each group comes from one source, named in its `*_source` column; all columns of a group are null when no source has a value. Units: positions in degrees (ICRS at `epoch`, a Julian year: 2016.0 for Gaia, 1991.25 for Hipparcos, 2000.0 for SIMBAD), position errors in mas (`ra_error` on ra·cos dec), parallax in mas, proper motion in mas/yr (`pmra` on ra·cos dec), magnitudes in mag, radial velocity and broadening in km/s, temperature in K, `logg` in log(cm/s²), metallicity in dex, GSP-Phot distance in pc, radii in nominal solar radii (695,700 km), FLAME luminosity in nominal solar luminosities (3.828 × 10²⁶ W), mass in solar masses, age in Gyr, gravitational redshift in km/s and bolometric correction in mag, `nu_eff_used_in_astrometry` and `pseudocolour` in 1/µm. Except for distance, whose percentiles are explicit columns, `*_lower` and `*_upper` are the 16th and 84th percentiles. `fidelity_v2` under 0.5 marks a likely spurious astrometric solution (Rybizki et al. 2022). `metadata.json` lists the columns in order.

A planet host also has the group `host_star`, the star as its exoplanet catalogue gives it (`host_star_source`: `nasa-exoplanet-archive`, else `exoplanet-eu`, else `open-exoplanet-catalogue`): `host_name`, `host_distance` and `host_distance_error` (pc, the larger of the two errors), `host_teff` (K), `host_radius` and `host_mass` (solar), `host_metallicity` (dex), `host_logg` (cgs), `host_age` (Gyr), `host_v_mag`, `host_g_mag`, `host_k_mag` (mag) and `host_spectral_type`. Every other star has nulls there. A host that no other catalogue gives is a literature star. A host without a Gaia or Hipparcos row takes its astrometry group from the exoplanet catalogue (`astrometry_source`), before SIMBAD, with RA, Dec, parallax and proper motion as the catalogue gives them and epoch 2015.5 for the archive (its positions are Gaia DR2's) or 2000.0 for exoplanet.eu and OEC. A planet host can also take its Metadata name and class from these catalogues (`name_source`, `class_source`); a literature star's class is `star`, `brown dwarf`, `white dwarf` or `pulsar`.

`radius_gspphot` and its bounds, and the `flame` group, come from Gaia DR3's `astrophysical_parameters`, joined to `gaia_source` by `source_id`. They are model estimates, not resolved measurements, and stay null where Gaia has none. FLAME (Creevey et al. 2023, A&A 674, A26) derives the luminosity from G, `ag_gspphot`, the bolometric correction `bc_flame` and the parallax or the GSP-Phot distance, and the radius from the luminosity and `teff_gspphot`. The mass, the age and `evolstage_flame` come from BaSTI tracks with a solar metallicity, so the age is biased for stars outside −0.5 < [M/H] < +0.5. `evolstage_flame` counts the phases of the BaSTI tracks from 100 at the zero-age main sequence: main sequence below 390, turn-off from 390, subgiant from 420 and giant from 490, where Gaia flags nearly every star as a giant. The tracks end near 1300 at the tip of the red giant branch, but a few values run up to about 1770, and stars without a mass have a stage as well. `flags_flame` is as published. Its first digit is 0, 1 for a giant, whose mass Gaia trusts only from 1 to 2 M☉, or 2 where FLAME gives no mass or age. Its second digit is 0 or 2 where the luminosity rests on the parallax, 1 where it rests on `distance_gspphot`.

The `flame_spec` group is FLAME's second run, on the temperature, gravity and metallicity that GSP-Spec measured on the RVS spectra. It comes from `astrophysical_parameters_supp`, holds about 5 million stars, and has the columns of `flame` with `_spec` added (`radius_flame_spec`, `radius_flame_spec_lower`, …), in the same units. `flags_flame_spec` has one digit, with the meaning of the first digit of `flags_flame`, and `evolstage_flame_spec` is 0 for some stars without a mass.

Close rendering takes `radius_flame`, else `radius_gspphot`, and `teff_gspphot` for a smooth, limb-darkened photosphere, with photometric colour as a fallback. Stars without a radius remain points.

The `xgboost` group is Table 1 of Andrae, Rix & Chandra (2023, ApJS 267, 8; [Zenodo 7945154](https://doi.org/10.5281/zenodo.7945154), CC BY 4.0), joined to `gaia_source` by `source_id`; its provenance is `xgboost_source`. `mh_xgboost`, `teff_xgboost` and `logg_xgboost` come from XGBoost on the XP spectra, the CatWISE photometry and the parallax, trained on APOGEE DR17. `catwise_w1` and `catwise_w2` are the CatWISE2020 magnitudes (Vega) that it used, and `in_training_sample` marks the stars of its training sample. `in_vetted_rgb_sample` is true for the stars of their Table 2, a vetted sample of red giants with the same values. `in_oba_golden_sample` is true for the stars of the Gaia DR3 golden sample of OBA stars (Gaia Collaboration, Creevey et al. 2023, A&A 674, A39; all 3,023,388 rows), the list that the authors use to remove OBA stars. The table has no quality cut and no uncertainty for each star. The authors give about 0.1 dex for [M/H] in the training range, 0.2 dex at G ≈ 16 and 0.4 dex at G ≈ 17.65. [M/H] is not valid for OBA stars. On the main sequence it is unbiased for 0.5 < BP − RP < 1.5, about 0.15 dex too low for 1.5 < BP − RP < 2.5, and not valid outside 0.5–2.5. `teff_xgboost` stays near the training range of 3,107 K to 6,867 K (the table spans 2,975 K to 7,076 K), so it cannot mark a hot star (their Sect. 3.5, 3.7 and 4.3). The ingest applies none of these cuts. Of the 180,949,689 stars of ingest 4, 62.8% have a row: 24.8% of those with G < 6.5 and 72.6% of those within 100 pc.

The `gaia_classification` group also holds the class tags of Gaia DR3 from `astrophysical_parameters`, as published: `classprob_dsc_combmod_whitedwarf`, the spectral type tag `spectraltype_esphs` (O to M, `CSTAR` or `unknown`; ESP-ELS gives it, despite its name) with `flags_esphs`, whose second digit is the quality of the tag (1 best to 5, 0 for a confirmed carbon star, 9 for none), and the emission-line class `classlabel_espels` with `classlabel_espels_flag` (Creevey et al. 2023, A&A 674, A26, Sect. 6.1.3).

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

The distance group and the SIMBAD photometry:

| Column | Type | |
|---|---|---|
| `distance` | float32 | distance (pc) from a paper, a SIMBAD parallax or a distance catalogue |
| `distance_lower`, `distance_upper` | float32 | bounds of the uncertainty (pc); either can be null. For `galaxy`, the error of the galaxy's distance, not its depth |
| `distance_lower_percentile`, `distance_upper_percentile` | float32 | percentile (0–100) of each bound where published; null when a bound is an error or its percentile is unspecified |
| `distance_method` | dict | `parallax`, `photometric`, `cluster` (the distance of the host cluster), `association` (the distance of the star's OB association), `galaxy` (the distance of the host galaxy), `geometric` (parallax with a Galaxy prior) or `expansion` (expansion parallax of a nebula) |
| `distance_source` | dict | the first of `literature` (a paper chosen for the star, cited in its object entry), `simbad-parallax` (a 5σ parallax that SIMBAD gives a `gaia-dr3-named` star, which has no 5σ Gaia parallax), `reyle-2021` (the 10 pc sample, Reylé et al. 2021), `ultracoolsheet` (Best et al.), `hunt-reffert-2024` (cluster members), `magellanic-clouds` (LMC and SMC members after Luri et al. 2021, at the distances of Pietrzyński et al. 2019 and Graczyk et al. 2020), `bailer-jones-2021` (Bailer-Jones et al. 2021) that has the star |
| `simbad_b_mag`, `simbad_v_mag`, `simbad_g_mag` | float32 | B, V and Gaia G that SIMBAD compiles from the literature (mag) |
| `simbad_sp_type` | string | the spectral type as SIMBAD gives it |
| `simbad_otype` | dict | SIMBAD's object type code (`*`, `**`, `V*`, `Em*` …), set for every star that SIMBAD lists |
| `simbad_photometry_source` | dict | `simbad` for every star that SIMBAD lists |

The distance group is also filled for some stars with a good parallax. The render tree places a star by its parallax first, unless the distance comes from the literature or is a more precise measured parallax; see below.

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
- **Precision.** A float32 position relative to the centre is off by up to half · 2^-24: about 13 AU for a star in a node of half size 1,024 pc, 0.8 AU in a node of half size 64 pc. A client that goes near one star takes its position from the star's record, with the distance rule below.

Which stars are drawn, and where (`extrasolar.placement`; the ingest report counts the planet hosts by the same rule):

1. A star whose `distance_source` is `literature` is at `distance`: that value was chosen for the star from a paper. This holds for every star, flagged or not.
2. Else a star with `parallax / parallax_error > 5` that is not flagged is at `1000 / p`, unless its distance group is a more precise measured parallax: `distance_method` is `parallax`, `distance_source` is not `simbad-parallax`, and `(distance_upper − distance_lower) / (2 · distance)` is under `parallax_error / parallax`, or under half of it for Gaia astrometry. That star is at `distance` (step 3). The distance catalogues copy Gaia's parallax with its error rounded down, hence the margin. SIMBAD's parallax on a row with its own is Gaia DR2's, with errors too small. A distance from a prior (`geometric`), a cluster or a galaxy stays below the star's own parallax. A star is flagged when its `astrometry_source` is `gaia-dr3` or `gaia-dr3-named` and its `fidelity_v2` is under 0.5. A Hipparcos, SIMBAD or exoplanet catalogue parallax is never flagged, even when the row has the `fidelity_v2` of a Gaia source.
3. Else a star with `distance` is at `distance`.
4. Else a planet host with a `host_distance` is at `host_distance`, along its RA and Dec, or at `1000 / parallax_nss` when it has a 5σ astrometric orbit solution.
5. A flagged star is drawn only when Hipparcos, SIMBAD or an exoplanet catalogue saw it (`hipparcos_photometry_source`, `simbad_photometry_source` or `host_star_source` not null), or by step 1. Its parallax is suspect, so steps 3 and 4 come first, also for a star that Hipparcos or SIMBAD saw. Else it is at `1000 / p` when `parallax` is 5σ.
6. A star with no distance from these steps has an ID and a record, but no render row. So has a star with no magnitude, unless it is a planet host.

In steps 2 and 5, `p` is `parallax_nss` of table 2 for a star with an astrometric orbit solution whose `parallax_nss` is over 5 times its error (see Binary orbit), else `parallax`. The single-star `parallax` and `parallax_error` still decide whether step 2 or 5 holds. The planet files say how each host is placed (`placement`).

Positions are at J2016.0: a row at another `epoch` (J1991.25 for Hipparcos, J2000.0 for SIMBAD) moves by its proper motion. A row without proper motion stays at its epoch. The absolute magnitude takes the distance `d` used: `mag = G − 5 log10(d / 10 pc)`, with no correction for extinction. G is the first of: `phot_g_mean_mag`; `simbad_g_mag`; the estimate of G from the Hipparcos V and B − V, else from Hp, that the ingest uses for matching (`g_estimate` of the Hipparcos source); the same estimate from `simbad_v_mag` and `simbad_b_mag − simbad_v_mag`; for a planet host, `host_g_mag`, else `host_v_mag` taken as G. A planet host with no magnitude at all (most microlensing and pulsar hosts) takes absolute G 15.0, a placeholder that keeps it in the tree and draws it only near its system. The colour is `phot_bp_mean_mag − phot_rp_mean_mag`; for a star without Gaia colours, BP − RP from the Hipparcos V − I (Riello et al. 2021, Table C.2: −0.01612 + 1.274 x − 0.08143 x², x = V − I from −0.5 to 3.5); else BP − RP of a dwarf of the star's Teff (`host_teff`, else `teff_gspphot`) by the dwarf sequence of Pecaut & Mamajek (2013, table version 2022.04.16, B9V to M8.5V, linear between rows, the nearest end outside them); else NaN. SIMBAD's B − V gives no colour: Riello et al. 2021 give no BP − RP from B − V.

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
  - a star: `id` is its extrasolar ID, and `position` its position in parsecs, in the frame of the render tree (ICRS axes, origin at the barycentre, J2016.0), as float64. The position is the one that the tree build computes for the star, from the same code over the same rows, so a line ends on the rendered star: it is the float64 value that the node stores as the node's centre plus a float32 offset. A star that the tree does not draw has an `id` and no `position`: a star with no distance (no 5σ parallax and no `distance`), a flagged star that neither Hipparcos nor SIMBAD saw, or a star with no magnitude (see the render tree). A named Gaia source without a 5σ parallax (`gaia-dr3-named`) has an `id`, and the tree draws it when it has a `distance`.
  - an object with no ID: `ref` as the source writes it, `reason` (below), and `designation` for a deep-sky object or a planet. A line that passes through it keeps its index, so no line is cut; a client skips the segments to a member without a position.
  - a point of the sky that a Stellarium figure gives in place of a star: `ra_hours` and `dec` (degrees) as published. It has no distance.
- **`figures`.** `kind` is `constellation` or `asterism`. `names` lists the names of the figure, each with the fields that the source gives of `native` (in the culture's script), `english`, `pronounce`, `transliteration` and `IPA`. `lines` is a list of chains; each chain is a list of member indexes, joined in order. A Bucur figure can have `group`, member indexes of a star group with no lines, and `iau`, the IAU constellation that holds a figure whose stars are not known. A Stellarium asterism with `ray_helper` is a line that helps find stars (a pointer), which Stellarium draws apart from the figures.
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

The token of `skycultures` covers all its files: SHA-256 over each file's path, a zero byte and the SHA-256 of its JSON with `token` set to 16 zeros (`"0000000000000000"`), as for the containers. Each file's `token` field holds the token; a client checks it as it checks a container header.

## Planets (`planets`)

The planets and the substellar companions up to 60 Jupiter masses that the NASA Exoplanet Archive, exoplanet.eu and the Open Exoplanet Catalogue (OEC) list as confirmed or controversial around a star. Candidates, retracted objects and free-floating objects are not in it. A planet's page is `/x/{host}/b/{n}`: `host` is the extrasolar ID of the star it orbits, and `n` its number within that host, from 1. A number is never given twice: a planet that every catalogue drops retires, and its number then is a 404. A number can become an alias of another planet: when two numbers turn out to be one planet, or when the planet's host merges into another ID, which gives the planet a number on its live host. The old page then redirects.

The planets of one planetary system share one file, keyed by the ID of the system's key star (`system`). For a single star, that is the host. For a binary or a wider system it is the first star in OEC's hierarchy that has planets, else the star without a component letter or with `A`. So a planet around each star of a binary is in one file, and each orbits its own host. A planet around both stars of a binary (P-type) orbits the pair's star: the Gaia source of the pair when Gaia sees one. The hosts of one system can be in two regions of the sky, and their file is the same.

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

- `hosts`: every star with a planet, sorted by `id`. A key star with no planets of its own is in its system file and not here.
- `system`: the key of the host's system file.
- `planets`: the live numbers of the host, ascending.
- `aliases`: every alias number, keyed `"{host}/{n}"`, with the live planet it leads to as `[host, n]`. The target can be on another host (the second example: host 987654321 merged into 1234567890). The target is always a planet that the index lists, so there is one redirect; an alias whose end is not served is left out (a 404). The host of an alias key can be missing from `hosts`: a merged ID has no live planets.
- `position`: in parsecs, in the frame of the render tree (ICRS axes, origin at the barycentre, J2016.0), the float64 position that the tree build computes for the host. The node stores it as its centre plus a float32 offset, so the drawn point is off by up to half · 2^-24 of the node. Null when the host has no distance (not drawn).
- `outer_orbit`: in AU, the largest semi-major axis of the host's planets; null when none has one.

To find a planet `/x/{host}/b/{n}`: load the index once; when `aliases` has `"{host}/{n}"`, redirect to `/x/{target host}/b/{target n}`; else find the host in `hosts` and check that `n` is in its `planets` (else a 404); load `planets/{system}.json.gz` and take the planet with that `host` and `number`.

### System file

`planets/{key}.json.gz`, with `key` the ID of the system's key star:

```json
{
  "token": "3f0c…",
  "system": 27424668,
  "hosts": [ { "id": 27424668, "name": "Proxima Centauri", "…": "…" }, { "id": 564339647, "…": "…" } ],
  "planets": [ { "host": 27424668, "number": 1, "name": "Proxima Cen b", "…": "…" }, { "host": 564339647, "number": 1, "…": "…" } ]
}
```

`hosts` has the key star first, then the other hosts by ID. `planets` is sorted by host, then number. A float with no value is `null`.

A host:

| Field | | |
|-------|-|-|
| `id` | number | extrasolar ID |
| `name`, `name_source` | string | the Metadata name and its source |
| `class` | string | the Metadata class: `star`, `brown dwarf`, `white dwarf` or `pulsar` |
| `cross_ids` | list | the Metadata cross-ids, each `{catalogue, release, catalogue_id}` |
| `planets` | list | its live numbers; empty for a key star with no planets |
| `placement` | string | how its distance is known, by the steps of the render tree: `parallax` (its own, or a 5σ orbit parallax), the `distance_source` of its distance group (as `literature` or `bailer-jones-2021`), `catalogue distance`, `parallax with fidelity under 0.5`, or null when it has no distance and is not drawn |
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
| `name`, `name_source` | string | the IAU name (`iau-nameexoworlds`), else the designation and its catalogue |
| `designation` | string | the archive's name, else exoplanet.eu's, else OEC's |
| `letter` | string | `b`, `c`, … or null |
| `aliases` | list | the IAU name and every catalogue name of the planet |
| `cross_ids` | list | `{catalogue, release, catalogue_id}`: the archive's `objectid`, exoplanet.eu's name, OEC's first name, `iau/nameexoworlds/<name>`, and `wikidata/qid/<QID>`. Each ingest links the Wikidata items with an article in one of the site's languages again: an item names a planet by its NASA archive name (P5667), which is the planet's designation, or by its exoplanet.eu page (P5653). An item whose ids name two planets names none, and of the items that name one planet, the item with the most articles keeps it, then the lowest QID |
| `class` | string | after the IAU: `planet` (under 13 MJ, mass ratio to its star under 2/(25+√621) ≈ 0.04), `brown dwarf` (13 MJ or more), `sub-brown dwarf` (under 13 MJ with a larger mass ratio) |
| `class_basis` | string | `true mass`, `minimum mass`, `estimated mass`, `no mass` |
| `mass_ratio` | number | planet over central object, null without a star mass |
| `status` | string | `confirmed` or `controversial` |
| `elements` | object | the orbit in the scene's frame (below), or null when the planet has no semi-major axis: the client draws it as a fixed dot |
| `values` | object | every other value of the planets table that the planet has (below) |
| `sources` | object | the source of each group: `status`, `discovery`, `orbit`, `sky`, `mass`, `radius`, `physical`, `atmosphere`, `stellar`, `binary` → `nasa-exoplanet-archive`, `exoplanet-eu`, `open-exoplanet-catalogue`, or `gaia-dr3` for `sky` |
| `assumed` | list | the values that are defaults, not published: `eccentricity` (0, also an exact 0 with no error), `omega` (90°), `inclination` (a transiting planet of the same host, else 90°), `node` (one angle per system, from a hash of the ID of its key star), `periastron_time` (J2000.0: the position on the orbit is unknown) |
| `estimated` | list | values that a catalogue estimates (the archive's "Calculated Value", a mass–radius relation, exoplanet.eu's "Theoretical") |
| `computed` | list | `period` or `semi_major_axis` from Kepler's third law, or `semi_major_axis` from an angular separation and the distance |
| `limits` | list | `<name><` for an upper limit, `<name>>` for a lower limit |

`values` has the columns of the planets table with a value, by these names and units: `discovery_method`, `discovery_year`, `discovery_facility`; `period` (d), `semi_major_axis` (AU), `eccentricity`, `inclination` (deg), `omega` (deg), `periastron_time` and `transit_time` (JD, as published, mostly BJD), `time_system` (the archive's system of the transit time: `BJD`, `BJD-TDB`, `HJD`, `JD`, …); `node` (deg), `node_inclination` (deg) and `node_solution` (Gaia's `nss_solution_type`); `mass` (Jupiter masses), `mass_kind` (`true`, `minimum`, `estimate`); `radius` (Jupiter radii); `equilibrium_temperature` (K), `insolation` (Earth's), `density` (g/cm³); `molecules` (a list); `star_mass` (solar), `star_radius` (solar), `star_teff` (K), `star_metallicity` (dex), the star of the fits; `binary_type` (`S-type` or `P-type`). A measured value `x` can have `x_error_upper` and `x_error_lower`, both positive. The defaults of `assumed` are in `values` too. `eccentricity` is as published, also when it is outside [0, 1).

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

The export refuses to publish when a planet number is given twice, when a host is in two systems, when a host or a system key is not a live ID or has no Metadata or Point source row, or when a planet or alias that the served index lists is gone and the registry's Planets part does not say it retired or became an alias, and its host is still live.

### Sitemap

The site's sitemap lists the page of every planet and of every planet host that this export serves, from the planet index and the system files: see [sitemap.md](sitemap.md). An alias number has no page in it.

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
    { "slug": "a-type-main-sequence", "wikidata": ["Q471805"], "published": 5477, "estimated": 8264 },
    "…"
  ],
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
  "planets": {
    "token": "3f0c…",
    "index": "planets/index.json.gz",
    "system": "planets/{key}.json.gz",
    "systems": 5801,
    "hosts": 5809,
    "planets": 7595,
    "units": { "position": "pc", "distance": "pc", "a": "AU", "angles": "deg", "n": "deg/day", "epoch": "JD TDB" },
    "elements_frame": "ecliptic and mean equinox of J2000, the planet around its host; obliquity 23.4392911 deg",
    "frame": "ICRS equatorial axes, origin at the solar system barycentre, epoch J2016.0",
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
- `families`: the star families in bit order: entry `n` is bit `n` of the Metadata masks. `wikidata` holds the topic items of the family, `published` and `estimated` count the stars with the bit set in `families` and in `families_estimated`.
- `distribution`: who may serve the data, with the meaning that it has on a texture ([textures.md](textures.md)). Gaia DR3 is CC BY-NC 3.0 IGO, and every table and tree holds Gaia values, so all are `non-commercial`.
- `credits`: each source with `name`, `organisation`, `source` (URL), and `license`, `attribution` and `citation` when known: Gaia DR3, Rybizki et al. 2022, the binary orbits and masses of Arenou et al. 2023, Andrae, Rix & Chandra 2023, PASTEL, SIMBAD, APOGEE DR17, the LAMOST DR10 M dwarfs of Zhang et al. 2025, the LAMOST DR10 catalogue of M stars, Hipparcos I/311 and I/239, XHIP V/137D, the distance catalogues (Reylé et al. 2021, the UltracoolSheet, Hunt & Reffert 2024, the LMC and SMC distances of Pietrzyński et al. 2019 and Graczyk et al. 2020, Bailer-Jones et al. 2021), one credit for the papers of the literature table (its `source` is the table in the repo; each star's object entry cites its own papers), the IAU Catalog of Star Names, Wikidata; with planets also the NASA Exoplanet Archive (its acknowledgement, and the DOI of Planetary Systems Composite Parameters, 10.26133/NEA13), exoplanet.eu (CC BY 4.0), the Open Exoplanet Catalogue (MIT) and the IAU's NameExoWorlds. The planet catalogues also fill the host rows of Point source and Metadata, so their credits are in this list. Each catalogue has one credit, and its `source` names it.
- `planets`: absent when the registry has no planets table. `index` and `system` (a pattern with `{key}`) are paths. `systems`, `hosts` and `planets` count the system files, the hosts with planets and the planets. `frame` is the frame of the positions, `elements_frame` that of the elements. `distribution` is `non-commercial`: the host positions come from Gaia DR3.
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

The export of 2026-10-26 (a new registry, 180,980,643 IDs) adds both FLAME groups and the metallicity groups to Point source: 437,532 tiles, 47.0 GB, median 92 kB and 349 rows, p90 178 kB, max 237 kB, about 260 B per row.

Binary orbit tiles (`max_rows` 300), an estimate from the tile writer and the split rule over the 394,046 orbits of the positionable stars: 3,045 tiles, 118 MB, median 34 kB and 112 rows, p90 64 kB, max 111 kB.

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
- the planet checks (see Planets, "Token and checks").

A failed run leaves the served export as it was.

The export holds a shared lock on `registry/lock` for the whole run, and an ingest holds the same lock exclusively. So an export does not start while an ingest runs, an ingest does not start while an export runs, and every file comes from the registry state that `registry` in `metadata.json` names.
