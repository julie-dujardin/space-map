# Credits (`credits.json`)

Aggregated attribution manifest read by the standalone `/credits` page. A
single non-gzipped JSON file so the page can render everything in one fetch
without walking per-system or per-body files.

```typescript
interface Credits {
  systems: Array<{
    id: string | null;           // barycenter object ID ("naif-3", …) or null for the standalone bucket
    name: string | null;         // primary-planet name ("Earth", "Jupiter", …); null for standalones
    textures?: Array<{
      body_id: string;           // e.g. "naif-399"
      name: string;              // English display name; localisation is deferred
      source: string;            // attribution source URL
      organisation: string;      // short label, deduplicable (e.g. "NASA", "USGS")
      type: string;              // cylindrical / cylindrical_monthly / cylindrical_tile / …
      frames?: number;           // only on cylindrical_monthly; frame count
      attribution?: string;      // long-form credit line when available
      description?: string;      // optional one-liner about the dataset
    }>;
    rings?: Array<{
      body_id: string;           // real Object.id of the ringed host (e.g. "naif-699"); the array name is the disambiguator, not a synthetic "-rings" suffix
      name: string;              // English display name of the host body
      source: string;
      organisation: string;
      attribution?: string;
      description?: string;
    }>;
    clouds?: Array<{
      body_id: string;           // host body id (e.g. "naif-399"), NOT the "_clouds"-suffixed export id; same disambiguation as rings
      name: string;              // English display name of the host body
      source: string;
      organisation: string;
      attribution?: string;
      description?: string;
    }>;
  }>;
  models?: Array<{               // 3D-model source catalogs (one entry per catalog with ≥ 1 bundle)
    name: string;                // "NASA-3D-Resources", "ESA SciFleet"
    url: string;                 // user-facing catalog landing page
  }>;
  skybox?: {                     // whole-sky cubemap backdrop — single global asset, no host body
    source: string;
    organisation: string;
    attribution?: string;
    description?: string;
  };
}
```

Systems are ordered Mercury → Pluto by barycenter NAIF ID; a final `id: null`
bucket collects standalones (sun-orbiting dwarf planets or asteroids such as
Ceres and Bennu). Each system's `textures` and `rings` lists are alphabetised
by body name; either array is omitted entirely when no entries exist for
that bucket. Only bodies whose `metadata.json` exists on disk (under
`textures/` or `rings/`) are included. Static credits (orbital providers,
SPICE/IAU rotation kernels, Wikidata, Wikipedia, Wikimedia Commons, IAU
nomenclature) live in the frontend page itself and don't need to be emitted
here. The top-level `skybox` block is emitted whenever a cubemap-skybox bundle
exists under `textures/stars/` and mirrors the credit fields from its metadata.

The top-level `models` array credits each 3D-model source catalog (NASA-3D-Resources,
ESA SciFleet, …) with one entry per catalog whose attribution matched at least
one model bundle under `models/{slug}/`. The catalog license is what matters, not
per-body attribution, so no item list is emitted. Models whose `attribution`
doesn't match a known catalog log a warning during export so the catalog list
stays maintained.
