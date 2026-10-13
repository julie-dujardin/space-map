# About data (`about-data.json`)

The report that the `/about/data` page shows: each map, each ring bundle and each 3D model, how fine it is, and how many files and bytes it takes. It is one JSON file that is not gzipped. `export/about_data.py` writes it on each full export, and `space-map-export --only about-data` writes it alone.

The export makes the file from the metadata that ingest writes: `textures/{id}/metadata.json` for a [texture](textures.md) bundle, `tiles/{id}/metadata.json` for its [tile pyramid](tiles.md), `rings/{id}/{bundle}/metadata.json` for a [ring](rings.md) bundle and `models/{slug}/metadata.json` for a [model](models.md). It does not read the tiles or the meshes. A cloud overlay is the exception: its metadata does not state the size of its images, so the export reads them from the bundle.

```typescript
interface AboutData {
  generated_at: string;            // ISO 8601 UTC
  worlds: number;                  // bodies with a map, a ring or a shape model
  rings: Array<{ id: string; name: string; rings: Ring[] }>;   // worlds in the order of the page, bundles innermost first
  models: {
    worlds: Array<{ id: string; name: string; models: ShapeModel[] }>;  // worlds in the order of the page
    craft: Array<{ kind: string; models: CraftModel[] }>;                // models by slug
    lightcurve?: {                 // the shapes from light curves, as one row
      models: number;
      worlds: number;              // one asteroid can have more than one model
      triangles: number;           // high file of each model
      size_bytes: number;
      sources: Credit[];           // the catalogues of the models
    };
  };
  systems: Array<{                 // the maps
    id: string | null;             // system barycentre, "naif-4"; null for the bodies in no planetary system
    name: string | null;           // English name of the planet of the system
    primary_id?: string;           // that planet, "naif-499"; the page takes its name in the reader's language from the labels
    worlds: Array<{
      id: string;                  // object id
      name: string;                // English name
      radius_km?: number;          // mean radius of the equator; absent when the size of the body is unknown
      no_surface?: true;           // a giant planet: its `surface` map shows its cloud top
      maps: Map[];
    }>;
  }>;
}

interface Credit {
  source?: string;                 // page of the source; a model can have none
  organisation: string;
  attribution?: string;            // credit line
}

interface Ring {
  id: string;                      // bundle, "inner" | "primary" | "outer"
  inner_radius_km: number;         // from the centre of the body
  outer_radius_km: number;
  samples: number;
  km_per_sample: number;           // radial distance between two samples
  size_bytes: number;              // the strip
  sources: Credit[];               // `attribution` is the title of the cited work
}

interface Model {
  slug: string;
  tiers: Array<{                   // the files, low before high
    name: string;                  // "low" | "high"
    triangles: number;
    size_bytes: number;
  }>;
  extent_m?: number;               // longest dimension; absent for a craft with no measured size
  sources: Credit[];
}

interface ShapeModel extends Model {
  provenance: "missions" | "radar";
}

interface CraftModel extends Model {
  objects: number;                 // objects whose `model_name` is the slug
  object?: { id: string; name: string };  // that object, where there is one
}

interface Map extends Credit {
  id: string;                      // bundle id, "naif-499_displacement"
  layer: "surface" | "clouds" | "night" | "specular" | "topography";
  alternate?: true;                // a map that ranks below the best map of its body
  frames?: number;                 // monthly maps and cloud overlays with more than one frame
  tiers: Array<{                   // the whole-globe images, coarsest first
    name: string;                  // "low" | "medium" | "high"
    width: number;
    height: number;
    size_bytes: number;            // all frames together
    m_per_px?: number;
  }>;
  height_step_m?: number;          // height maps: the step of the whole-globe images, which have 8 bits
  tiles?: {                        // present when the map has a tile pyramid
    max_level: number;
    width: number;                 // pixels of the finest level
    height: number;
    m_per_px?: number;
    tiles: number;                 // the map and its two polar caps, all frames, without the patches
    size_bytes: number;
    sources: Array<{
      role: "base" | "inset" | "detail";
      width: number;               // `full_width` of the source
      m_per_px?: number;
      lat_range?: [number, number];  // south and north edge of a source that covers a band
    }>;
    height_step_m?: number;        // height pyramids: the step of the 16-bit tiles
    patches?: Array<Credit & {
      id: string;
      name: string;                // proper noun, shipped as it is
      max_level: number;
      m_per_px?: number;
      lat: number;                 // centre of the mosaic, degrees, east positive
      lon: number;
      width_km?: number;           // east to west at the latitude of the centre
      height_km?: number;
      tiles: number;               // all levels of the patch
      size_bytes: number;
    }>;
  };
}
```

Notes:

- **`m_per_px` is the ground size of one pixel at the equator**: `2π · radius_km / width`. It is absent where `radius_km` is absent.
- **The coarser of the grid and the source sets the scale of a pyramid.** The finest level is the first one that is as wide as the finest source, so its pixels can be smaller than those of the source. `tiles.m_per_px` then states the source. A patch follows the same rule: a 0.25 m mosaic sits at level 16, whose pixels are 0.16 m, and its `m_per_px` is 0.25.
- **`sources` are the `layers` of the pyramid descriptor.** `base` is the first one and covers the whole body. An `inset` replaces it over a band. A `detail` source is a brightness layer: the colour stays that of the base.
- **The credit of a map is that of its pyramid** where it has one, because a pyramid can come from another source than the whole-globe images. A map with no pyramid has the credit of its bundle. A patch has its own. The fields are those of `credits.json`, without the licence.
- **Sizes do not overlap.** `tiers[].size_bytes`, `tiles.size_bytes` and each `patches[].size_bytes` count different files. The page adds the tiers and the pyramid for the row of a map, and gives each patch a row of its own.
- **Worlds are in the order of the page**: the systems from Mercury to Pluto, the planet before its moons, the moons by number, then the bodies in no system.
- A bundle whose id is not an object, such as the star map, has no row.
- **`km_per_sample` counts the two edges of a ring bundle as samples**: `(outer_radius_km - inner_radius_km) / (samples - 1)`.
- **The `high` file of a model gives the page its triangles.** The ingest picks `low` and `high` by size on disk, so `low` can have more triangles than `high`. The two files can be equal.
- **`extent_m` is `true_scale.max_extent_km` for a shape and `scale_meters` for a craft.**
- **The credit of a shape is that of its metadata**, with the citation of the data set as the credit line. A craft model has one credit for each author of its files, the author of `high` first, with the page of the highest file of that author.
- **`craft` holds each model that is not the shape of a world**, in the order of the page: `probe`, `earth_sat`, `station`, `lander`, `robot`, `rocket`, `generic_sat`, `comparable`, then other kinds by name. `objects` counts the `Object` rows that the map draws with the model. Rockets and scale references have none.
- **The shapes from light curves have no rows of their own.** They are too many to list, so `lightcurve` gives their totals. Their credit comes from `MODEL_CATALOGS`.
