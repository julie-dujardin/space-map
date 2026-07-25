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

Feature-type collection pages (`/g/ft-<slug>`, one per 2-letter IAU descriptor
code) are documented in [groups.md](groups.md).
