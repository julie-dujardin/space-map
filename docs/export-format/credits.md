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
      license?: string;          // Wikimedia-style short license ("Public domain", "CC BY 4.0", …) when known
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
      license?: string;          // Wikimedia-style short license when known
      attribution?: string;
      description?: string;
    }>;
    clouds?: Array<{
      body_id: string;           // host body id (e.g. "naif-399"), NOT the "_clouds"-suffixed export id; same disambiguation as rings
      name: string;              // English display name of the host body
      source: string;
      organisation: string;
      license?: string;          // Wikimedia-style short license when known
      attribution?: string;
      description?: string;
    }>;
  }>;
  atmosphere_references: Array<{ // literature behind the derived scattering params
    title: string;               // "Fulchignoni et al. 2005 (Nature 438)"
    url: string;                 // DOI or stable publisher/archive link
    contribution: string;        // one-liner: what the pipeline takes from it
  }>;
  ring_references: Array<Reference>;        // works behind the ring profiles
  temperature_references: Array<Reference>; // measured temperatures + core estimates
  interior_references: Array<Reference>;    // gravity/seismic/meteorite work behind the interior blocks
  models?: Array<{               // 3D-model source catalogs (one entry per catalog with ≥ 1 bundle)
    name: string;                // "NASA-3D-Resources", "ESA SciFleet"
    url: string;                 // user-facing catalog landing page
    license?: string;            // Wikimedia-style short license when known
  }>;
  skybox?: {                     // whole-sky cubemap backdrop — single global asset, no host body
    source: string;
    organisation: string;
    license?: string;            // Wikimedia-style short license when known
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

`license` is a short, Wikimedia-Commons-style string ("Public domain", "CC BY
4.0", "CC BY-NC-SA 3.0", "Free use with attribution", …) sourced from each
texture's `license:` manifest field. It's omitted whenever the source license is
unresolved or restrictive enough to need manual review, so absence means
"unknown/flagged", not "unrestricted".

`atmosphere_references` is the flat literature list behind `atmospheres.json`
(curated in `data/src/space_map_data/constants/atmosphere/references.py` — one
row per work numbers are actually taken from, English-only like the rest of
this payload).

`ring_references`, `temperature_references` and `interior_references` are the
same shape, one per constants package under `data/src/space_map_data/constants/`.
Each per-body panel credits only the works its own numbers come from; these
lists are the whole bibliography in one place, for the credits page.

The top-level `models` array credits each 3D-model source catalog (NASA-3D-Resources,
ESA SciFleet, …) with one entry per catalog whose attribution matched at least
one model bundle under `models/{slug}/`. The catalog license is what matters, not
per-body attribution, so no item list is emitted. Models whose `attribution`
doesn't match a known catalog log a warning during export so the catalog list
stays maintained.
