# Object detail files

Object details are grouped into **hash-bucketed bundles** to keep the file
count manageable. The bundle count per tier (`N_global`, one `N_{lang}` per
language) is chosen at export time so average members-per-bundle stays near
target K (`K_global = 100`, `K_localized = 200`) regardless of DB size. The
resulting Ns are published in `metadata.json → object_bundles` so the
frontend can reconstruct URLs from an id alone — needed for deep links where
no element file has been loaded yet.

The bucket id for an object in tier T (global or a specific language) is:

```
bucket = sha256(id)[:4] as big-endian uint32, mod N_tier
```

Each bundle is a gzipped JSON object keyed by object id:
`{ "<id>": ObjectData, ... }`. Bundles split by hash — no zone structure in
the path, no co-location guarantee, but tight uniformity (max bundle ≈ 1.3×
average at K=100).

## Global (`objects/__global__/{bucket}.json.gz`)

Written for every exported object. `bucket = sha256(id)[:4] % N_global`. Each
bundle is a JSON object `{ "<id>": GlobalObjectData, ... }`.

`GlobalObjectData` contains cross-references, orbit source data, SBDB physical
parameters, and Wikidata quantities:

```typescript
interface GlobalObjectData {
  id: string;
  type: string;                       // ObjectType name
  name?: string;
  parent_name?: string;               // host display name; moons only — lets the breadcrumb label the parent when its body isn't resident in the scene
  color?: string;                     // moons only — #rrggbb physically-derived surface colour. Top-level (moons carry no `sbdb` block); small bodies carry theirs under `sbdb.color`. Absent → frontend generic tint
  color_method?: "spectrum" | "albedo"; // moons only — how `color` was derived (present iff color is): TCT measured reflectance, else neutral grey × JPL Horizons geometric albedo
  map_texture_available?: boolean;    // only present if true
  texture?: {                         // only when map_texture_available; mirrors systems/{bary}.json
    source: string;                   // source page URL
    organisation: string;             // short canonical label, deduplicable (e.g. "NASA", "USGS", "Björn Jónsson")
    type: string;                     // texture kind (cylindrical, cylindrical_monthly, cylindrical_tile, …)
    frames?: number;                  // only on cylindrical_monthly; frame count (1-based, files end in _01..frames)
    attribution?: string;             // long-form credit line; omitted when unavailable
    description?: string;
  };
  has_rings?: boolean;                // only present if true; full ring metadata (channels, geometry, attribution) lives in systems/{bary}.json
  clouds?: {                          // only when a cloud overlay was ingested for this body; mirrors systems/{bary}.json
    id: string;                       // export bundle id, e.g. "naif-399_clouds" — used to compose /v1/textures/{id}/{tier}_{frame}.webp
    tiers: string[];                  // sorted tier names (low | medium | high)
    frames: string[];                 // available snapshot ids (YYYYMMDDHH, sorted ascending); frontend picks the closest to simulation time
    source: string;
    organisation: string;
    type: string;                     // always "clouds_overlay" today
    attribution?: string;
    description?: string;
  };
  provisional_designation?: string;
  sbdb_primary_designation?: string;  // SBDB MPC designation (e.g. "2000 RU65")
  sitelinks_count?: number;           // Wikidata sitelink count; notability rank (omitted when 0)
  cross_refs?: {
    wikidata_qid?: string;
    naif_id?: number;
    spkid?: number;
    mpc_designation?: string;
    norad_cat_id?: number;
    cospar_id?: string;
  };
  nasa_science_url?: string;          // URL to science.nasa.gov page
  images?: ObjectImage[];             // from Wikidata P18/P154 + all Wikipedia languages
  orientation?: {                     // SPICE PCK IAU rotation polynomial
    // α(T) = pole_ra_0 + pole_ra_1·T   (T = Julian centuries since J2000)
    // δ(T) = pole_dec_0 + pole_dec_1·T
    // W(d) = w0 + w1·d + w2·d²         (d = days since J2000)
    pole_ra_0: number; pole_ra_1: number;
    pole_dec_0: number; pole_dec_1: number;
    w0: number; w1: number; w2: number;
  };
  nut_prec?: {                        // SPICE PCK nutation/precession sums (paired with `nut_prec_angles` in /v1/systems/global.json)
    // α += Σ ra[i]  · sin(θ_i(T)),  δ += Σ dec[i] · cos(θ_i(T)),  W += Σ pm[i] · sin(θ_i(T))
    ra: number[]; dec: number[]; pm: number[];
  };
  radii?: {                           // SPICE PCK triaxial radii (km, body-fixed X/Y/Z)
    a: number; b: number; c: number;
  };
  pointing?: {                        // hand-edited per-spacecraft attitude (spacecraft-orientation.yaml)
    // The frontend aims the focused model's `primary.axis` exactly at the
    // `primary.target` direction, then rolls so `secondary.axis` points as
    // close as possible at `secondary.target`. Absent → south-toward-parent.
    primary:    { axis: "+x"|"-x"|"+y"|"-y"|"+z"|"-z"; target: "parent"|"sun"|"velocity" };
    secondary?: { axis: "+x"|"-x"|"+y"|"-y"|"+z"|"-z"; target: "parent"|"sun"|"velocity" };
  };
  gm?: number;                        // SPICE PCK gravitational parameter (km^3/s^2)
  orbit?: {
    epoch_jd: number; e: number; i: number;
    om: number; w: number;
    scale: "planet" | "system";
    /** Full parent `Object.id` (e.g. `"naif-399"`, `"spkid-2000004"`). */
    parent_id: string;
    source: "horizons" | "sbdb" | "celestrak" | "spice" | "sbdb_moons";
    // Keplerian (standard orbits):
    a?: number; ma?: number; n?: number;
    // Parabolic (e=1 comets):
    q?: number; tp?: number;
    // SGP4 init fields (CelesTrak-sourced earth sats only) — feed into
    // satellite.js `json2satrec` so URL-navigated sats can build a satrec
    // before their element file arrives.
    bstar?: number;           // 1 / Earth radius
    mean_motion_dot?: number; // rev/day²
    mean_motion_ddot?: number; // rev/day³
    element_set_no?: number;
    rev_at_epoch?: number;
  };
  sbdb?: {
    neo?: boolean;   pha?: boolean;
    class?: string;  // OrbitClass enum *name* (e.g. "MBA", "APO") — same id used to name the export zone
    sats?: number;   diameter?: number;  // km
    extent?: string; albedo?: number; rot_per?: number;  // hours
    GM?: number;     // km^3/s^2
    mass?: { value: number; unit: string };
    H?: number; G?: number;
    spec_B?: string; spec_T?: string;
    color?: string;  // #rrggbb physically-derived surface colour (TrueColorTools): per-body measured colour, else taxonomy chroma × albedo, else albedo grey. Absent → frontend generic tint
    color_method?: "spectrum" | "photometry" | "taxonomy" | "albedo";  // how `color` was derived (present iff color is)
    BV?: number; UB?: number; IR?: number;
    moid?: number;   // AU, Earth MOID
    moid_jup?: number; t_jup?: number;
    per_y?: number;  // orbital period, years
    ad?: number;  // AU, aphelion distance
    prefix?: string; // comet prefix
    M1?: number; M2?: number; K1?: number; K2?: number; PC?: number;
    first_obs?: string;
    last_obs?: string;
    data_arc?: number;   // observation arc span, days
    n_obs_used?: number; // number of observations used
  };
  celestrak?: {                       // SATCAT metadata for CelesTrak-sourced satellites
    object_type?: string;             // payload / rocket_body / debris / unknown
    ops_status?: string;              // operational / nonoperational / partial / backup / spare / extended_mission / decayed / unknown
    data_status?: string;             // no_current_elements / no_initial_elements / no_elements_available
    launch_date?: string;             // ISO date
    decay_date?: string;              // ISO date
    period?: number;                  // minutes
    apogee?: number;                  // km
    perigee?: number;                 // km
    rcs?: number;                     // m²
    orbit_center?: string;            // earth / jupiter / moon / … / docked
    orbit_center_docked_to?: number;  // NORAD of host (only when orbit_center == "docked")
    launch_site_code?: string;        // SATCAT short code, see constants/earth_sats/launch_sites.py
    owner?: string;                   // SATCAT OWNER short code, see constants/earth_sats/sources.py
    constellation_slug?: string;      // see constants/earth_sats/constellations.py
    bus_slug?: string;                // satellite bus / platform, see constants/earth_sats/satellite_models.py
    categories?: string[];            // SatelliteCategory values
    country_codes?: string[];         // ISO 3166-1 alpha-2 (feed into Intl.DisplayNames)
  };
  wikidata?: {
    discovery_date?: string;  // ISO 8601
    launch_date?: string;
    mass?: QuantityWithUnit;
    radius?: QuantityWithUnit;
    density?: QuantityWithUnit;
    surface_gravity?: QuantityWithUnit;
    absolute_magnitude?: number;
    apparent_magnitude?: number;
    temperature?: QuantityWithUnit;
    min_temperature?: QuantityWithUnit;
    max_temperature?: QuantityWithUnit;
    website?: string;
    blog?: string;
    capital_cost?: CurrencyQuantity;
    length?: QuantityWithUnit;
    width?: QuantityWithUnit;
  };

  // Notable moons of this body, picked at export time, ordered by
  // (image_available, sitelinks_count, diameter desc, id). Present on the
  // planet/dwarf-planet (a planet's moons are gathered from its barycenter)
  // and on asteroids with satellites. Denormalized so the strip + moons list
  // render without per-moon fetches; per-language label overrides live in
  // LocalizedObjectData.notable_moon_names. Shares the NotableEntry shape
  // with GlobalGroupData.notable_members.
  notable_moons?: NotableEntry[];
  moon_count?: number;                // total moons of this body (drives the "+N more" tile); present iff notable_moons is
  named_moon_count?: number;          // moons with an IAU name; present when > 0 (asteroid moonlets and provisional
                                      // outer-planet moons are unnamed, so this is < moon_count for those hosts)

  // Curated featured satellites (Earth only). The Moons section is relabelled
  // "Satellites" and renders these after the Moon; the "+N more" tile links to
  // the Satellites browse page (`satellites_group`) instead of an in-drawer
  // tab. NotableEntry shape, but a constellation entry carries `group` (a slug)
  // instead of `id`. Per-language overrides live in notable_satellite_names.
  notable_satellites?: NotableEntry[];
  satellite_count?: number;           // total tracked artificial satellites (spacecraft + debris), folded into "+N more"
  satellites_group?: string;          // group slug the "+N more" tile opens (cat-satellites)

  // Split-comet fragments. On an intact parent comet (e.g. 73P/Schwassmann-
  // Wachmann 3) `fragments` lists its pieces — same NotableEntry shape + strip
  // UI as notable_moons, ranked by (image_available, sitelinks_count, id) and
  // capped at 20; `fragment_count` is the full total. Per-language label
  // overrides live in LocalizedObjectData.fragment_names.
  fragments?: NotableEntry[];
  fragment_count?: number;
  // Present on each fragment object (a `<pdes>-<letters>` body): the comet it
  // broke off, for the "Fragment of <parent>" stat card + breadcrumb. Points
  // at the parent's object page when the intact body is catalogued, else at
  // the synthetic split-comet group page (primary_type "group").
  fragment_of?: {
    name: string;
    primary_type: "object" | "group";
    primary_id: string;            // parent Object.id ("object") or family group slug ("group")
    thumbnail?: PickedThumbnail;   // parent thumbnail (object parents only)
  };

  // Probe missions (probe objects only). The primary probe carries `mission`
  // + a `mission_members` strip (siblings, primary excluded) + count; each
  // member carries `part_of_mission`. Both link to the /g/mission-<slug> page,
  // whose `primary` redirect (see GlobalGroupData) focuses the primary probe.
  // Per-language label overrides: LocalizedObjectData.mission_member_names.
  mission?: { name: string; primary_type: "group"; primary_id: string };
  mission_members?: NotableEntry[];
  mission_member_count?: number;
  part_of_mission?: { name: string; primary_type: "group"; primary_id: string };
}

// Images collected from Wikidata P18/P154 + Wikipedia pageimages (all languages)
interface ObjectImage {
  file: string;           // Commons filename, used as the bundle directory name
  source_url: string;     // Wikimedia Commons file page URL (for license/attribution)
  kind: "photo" | "logo" | "locator" | "radar";  // "locator" feature-only; "radar" = small-body shape-model render
  variants: { [label in "s" | "m" | "xl"]?: string };  // label → extension
  width?: number;         // source pixel dimensions (omitted for SVG/WebM passthrough)
  height?: number;
}
// Quantities use best-fit units from Wikidata (e.g. "solar_mass", "kilometre")
interface QuantityWithUnit { value: number; unit: string; }
// Currencies use ISO 4217 codes (e.g. "EUR", "USD")
interface CurrencyQuantity { value: number; currency: string; }
```

## Localized (`objects/{lang}/{bucket}.json.gz`)

Per-language bundles. `bucket = sha256(id)[:4] % N_{lang}` where `N_{lang}`
is that language's count in `metadata.object_bundles`. An object appears in
the language's bundle only when Wikidata/Wikipedia data exists for that
language. The binary `has_localized` column/byte tells the frontend whether
*any* language has data, gating the fetch attempt; on a 404 (locale has no
bundle for this object) the frontend gives up — there is no English fallback
tier.

Each bundle is a JSON object `{ "<id>": LocalizedObjectData, ... }`. Entity
references link to Wikipedia where available.

```typescript
interface LocalizedObjectData {
  name?: string;          // Wikidata label in the target lang, falling back to English. Omitted if no Wikidata entity.
  description?: string;
  aliases?: string[];
  instance_of?: EntityRef[];
  discoverers?: EntityRef[];
  named_after?: EntityRef;
  discovery_site?: EntityRef;
  minor_planet_group?: EntityRef;
  spectral_type?: EntityRef;
  asteroid_family?: EntityRef;
  operators?: EntityRef[];        // merged from Wikidata P137 + CelesTrak, deduped; links to /g/org-<slug>
  constellation?: EntityRef;      // CelesTrak-derived; ROCKET constellations link to /g/lv-<slug> (a spent stage's vehicle), others to /g/const-<slug>
  bus?: EntityRef;                // CelesTrak-derived; links to /g/bus-<slug>
  manufacturer?: EntityRef;       // CelesTrak-derived; links to /g/org-<slug>
  launch_vehicle?: EntityRef;     // Wikidata P375; links to /g/lv-<slug> when the QID is a known launch vehicle, else a plain Wikipedia ref
  launch_site?: EntityRef;        // CelesTrak-derived takes precedence over Wikidata P1427
  developer?: EntityRef[];
  funder?: EntityRef[];
  country_of_origin?: EntityRef[];
  launch_contractor?: EntityRef[];
  part_of?: EntityRef[];          // Wikidata P361; QIDs already shown via a CelesTrak-derived field (constellation, bus, launch_site, operators, manufacturer) are dropped
  wikipedia?: {
    extract?: string;
    description?: string;
    url?: string;        // URL
  };
  notable_moon_names?: Record<string, string>; // notable-moon Object.id → localized label, only where it differs from the global name
  notable_moon_descriptions?: Record<string, string>; // notable-moon Object.id → localized Wikidata short description, for the planet-page moon lineup hover tooltip
  notable_satellite_names?: Record<string, string>; // featured-satellite id-or-slug → localized label, only where it differs
  fragment_names?: Record<string, string>;     // fragment Object.id → localized label, only where it differs from the global name
  mission_member_names?: Record<string, string>; // mission-member Object.id → localized label, only where it differs from the global name
}

interface EntityRef { name: string; short_name?: string; wikipedia?: string; }
```
