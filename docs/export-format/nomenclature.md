# IAU planetary nomenclature

Surface features (craters, maria, valles, …) live in two tiers so the marker
render path stays cheap.

## Marker tier (eager, per body)

Loaded when a body's surface comes into view. Two files per body that has any
feature:

- `nomenclature/positions/{body_id}.bin.gz` — **SMNF** binary
  (`feature_id` + center lat/lon + diameter + 2-letter IAU type code per
  record; see `data/src/space_map_data/export/nomenclature/format.py`).
- `nomenclature/__global__/{body_id}.json.gz` — gzipped JSON, keyed by
  string `feature_id`:

  ```typescript
  interface NomenclatureGlobalEntry {
    name: string;
    approval_date?: string;       // ISO date
    origin?: string;              // IAU "Named for ..." prose
    parent_feature_id?: number;   // IAU satellite-feature parent
  }
  ```

Features missing `object_id`, `center_lat`/`center_lon`, or `feature_type_code`
are dropped at build time (with a single aggregate log line per cause).

## Detail tier (lazy, hash-bucketed)

Fetched on drawer open. Bucket key is `{body_id}:{feature_id}` so features on
the same body cluster — opening one warms the bundle for its neighbours. Bucket
counts ship in `metadata.json → feature_bundles` so a frontend can recompute
the bucket from a URL.

- `nomenclature/details/__global__/{bucket}.json.gz` — global per-feature
  enrichment (image manifest with `kind: 'photo' | 'locator'`, Wikidata
  cross-link, physical-quantity claims):

  ```typescript
  interface FeatureGlobalData {
    wikidata_qid?: string;
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
    name?: string;                 // only when Wikidata's label differs
                                   // from the IAU canonical (`unicode_name`)
    description?: string;
    aliases?: string[];
    instance_of?: EntityRef[];     // resolved P31 refs
    named_after?: EntityRef[];     // resolved P138 refs
    location?: EntityRef[];        // resolved P276 refs
    located_on_physical_feature?: EntityRef;
    wikipedia?: { extract?: string; description?: string; url?: string };
  }
  ```

The IAU `parent_feature_id` graph (from the satellite-feature matching pass)
takes priority over Wikidata `P706` as the canonical "this feature sits on
that one" link — `P706` is much sparser (~1%) and is included as supplemental
metadata via `located_on_physical_feature` rather than as the authoritative
parent.
