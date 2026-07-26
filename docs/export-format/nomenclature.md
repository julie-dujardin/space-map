# IAU planetary nomenclature

Surface features (craters, maria, valles, …) live in two tiers so the marker
render path stays cheap.

## Marker tier (eager, per body)

Loaded when a body's surface comes into view. Two files per body that has any
feature, joined **by index**: line *i* of a labels file names record *i* of the
positions binary (both are written from one ordered feature list).

- `nomenclature/positions/{body_id}.bin.gz` — **SMNF** binary
  (`feature_id` + center lat/lon + diameter + 2-letter IAU type code per
  record; see `data/src/space_map_data/export/nomenclature/format.py`).
- `nomenclature/labels/{lang}/{body_id}.txt.gz` — one `\n`-separated display
  name per record: the feature's Wikidata label in `lang`, else its IAU name.

Features missing `object_id`, `center_lat`/`center_lon`, or `feature_type_code`
are dropped at build time (with a single aggregate log line per cause). The
same filter defines a `ft-` feature-type group's member set
(`renderable_feature_filter`), so group counts can't drift from what the map
carries.

## Detail tier (lazy, hash-bucketed)

Fetched on drawer open. Bucket key is `{body_id}:{feature_id}` so features on
the same body cluster — opening one warms the bundle for its neighbours. Bucket
counts ship in `metadata.json → feature_bundles` so a frontend can recompute
the bucket from a URL.

- `nomenclature/details/__global__/{bucket}.json.gz` — global per-feature
  enrichment (naming facts, image manifest with
  `kind: 'photo' | 'locator'`, Wikidata cross-link, physical-quantity claims):

  ```typescript
  interface FeatureGlobalData {
    approval_date?: string;        // ISO date the IAU approved the name
    origin?: string;               // IAU "Named for ..." prose (trailing period stripped)
    wikidata_qid?: string;
    sitelinks_count?: number;      // Wikidata prominence; ranks features in search + ft- member lists
    parent_feature?: EntityRef;    // IAU satellite-feature parent (same body)
    satellite_features?: EntityRef[]; // inverse of parent_feature
    contains?: EntityRef[];        // inverse of the localized `inside_of`
    images?: ObjectImage[];        // P18 → 'photo', P242 → 'locator'
    wikidata?: {
      length?: QuantityWithUnit;
      width?: QuantityWithUnit;
      height?: QuantityWithUnit;
      area?: QuantityWithUnit;
      elevation?: QuantityWithUnit;
      vertical_depth?: QuantityWithUnit;
    };
  }
  ```

- `nomenclature/details/{lang}/{bucket}.json.gz` — per-language overlay; a
  feature appears here only when it has at least one localized field in that
  language.

  ```typescript
  interface FeatureLocalizedData {
    description?: string;
    aliases?: string[];
    instance_of?: EntityRef[];     // resolved P31 refs
    named_after?: EntityRef[];     // resolved P138 refs
    part_of?: EntityRef[];         // resolved P361 refs
    inside_of?: EntityRef[];       // containing feature(s): Wikidata P706/P361, else derived from bbox/radius geometry
    quadrangle?: EntityRef;        // IAU map quadrangle; links to Wikipedia when the quad has a QID
    wikipedia?: { extract?: string; description?: string; url?: string };
  }
  ```

The IAU `parent_feature` graph (from the satellite-feature matching pass)
takes priority over Wikidata `P706` as the canonical "this feature sits on
that one" link — `P706` is much sparser (~1%) and is folded into `inside_of`
as supplemental metadata rather than as the authoritative parent.

## Quadrangle index

`nomenclature/quadrangles/__global__.json.gz` — one small file (~4 kB) covering
every body on an IAU quadrangle grid: Mercury's 15 `H-` charts, Venus' 62 `v`, Mars' 30
`mc`, the Moon's 144 `LAC`. It backs the body drawer's Surface tab hero, which
draws the cells over the body's map texture and narrows the feature list to a
selected one.

```typescript
type Quadrangles = Record<string /* body id */, {
  quads: {
    code: string;      // IAU quadrangle code, e.g. "mc09"
    name: string;      // IAU chart name, else the code when no feature names it
    n: number;         // renderable features inside it
    lat_min: number;
    lat_max: number;
    lon_min: number;   // east-positive; a cell straddling the prime meridian
    lon_span: number;  // has lon_min + lon_span > 360
  }[];
  overrides: Record<string /* feature_id */, string /* code */>;
}>
```

Cell geometry is generated from the row specs in
`constants/nomenclature/quadrangle_grid.py`, reconstructed from the gazetteer
itself — every feature carrying a `quad_code` falls inside the derived box for
that code, bar eleven classical Mars albedo features centred exactly on a cell
edge. Those ride in `overrides`, where the gazetteer's own assignment wins; the
search index applies them on top of its geometric lookup (`feature.quad`).

`nomenclature/quadrangles/{lang}.json.gz` — the charts' Wikipedia intros,
keyed `"<body id>:<code>"`, fetched only once a chart is picked:

```typescript
type QuadrangleTexts = Record<string, { extract: string; url?: string }>
```

Only Mercury, Venus and Mars charts are mapped to Wikidata (see
`constants/nomenclature/quadrangles.py`); the Moon's 144 LAC sheets have no
articles, and coverage is patchy per language — 8 languages ship a file, the
largest 16 kB. A quadrangle has no page of its own in the frontend: it's shown
as part of its parent body, on that body's Surface tab.

Written by the nomenclature tier, and on its own by
`space-map-export --only quadrangles` (additive — nothing else is touched).

Feature-type collection pages (`/g/ft-<slug>`, one per 2-letter IAU descriptor
code) are documented in [groups.md](groups.md).
