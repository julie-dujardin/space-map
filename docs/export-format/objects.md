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
  model_name?: string;                // slug under /v1/models/{model_name}/ when this body ships a 3D-model bundle (see models.md); shared by bodies that reuse one model
  model_source?: {                    // shape-model provenance (natural bodies only), denormalized from the bundle. Consumed by the scene's attribution popover, which credits the mesh it draws — not by the detail sidebar, whose sources list covers only what the sidebar itself renders
    provenance: "missions" | "radar" | "lightcurve"; // technique tier: spacecraft mission, Earth-based radar, or lightcurve inversion
    technique?: "lightcurve_convex" | "lightcurve_resolved"; // DAMIT bundles only: a convex hull from lightcurves alone, or a non-convex solution that also needed resolved data (adaptive optics, radar, occultations)
    author?: string;                  // who derived the shape ("Vernazza et al. (2021)"), when that isn't the archive under another name. DAMIT distributes other people's inversions, so its bundles name the paper's authors; a mission bundle whose credit repeats its archive omits this
    archive?: string;                 // archive the mesh came from (free text, e.g. "PDS SBN (NEAR)")
    archive_url?: string;
    mission?: { name: string; primary_type: "object"; primary_id: string }; // observing spacecraft (mission shapes only); primary_id is "probe-<id>"
  };
  render_quality?: "high" | "medium" | "low"; // best-available-asset render tier: high = faithful 3D model (spacecraft/mission/radar), map texture, or procedural star surface; medium = lightcurve-inversion convex hull only; low = size-only sphere/ellipsoid (PCK radii or SBDB diameter). Absent → no known physical extent, halo/point at best
  atmosphere?: {                      // cited atmospheric facts for the ~24 bodies with a measured envelope (see below)
    type: string;                     // "stellar_atmosphere" | "gas_giant_envelope" | "thick_atmosphere" | "thin_atmosphere" | "tenuous_collisional" | "tenuous_exosphere" | "exosphere" | "transient_exosphere" | "localized_plume" | "frozen_collapsed" | "none_detected"
    note?: string;                    // what sustains or varies it ("volcanic", "seasonal_orbit", "sputtered_ice", …); the frontend holds the sentence
    pressure?: {
      pa: number;                     // pressure at the level below
      level: string;                  // "surface" | "sea_level" | "areoid" | "cloud_top" | "one_bar" | "photosphere"
      qualifier?: "upper_limit" | "approximate" | "variable";
    };
    composition?: {                   // omitted below two species — a share needs something to be a share of
      unit: "volume_fraction" | "mass_fraction" | "column_density" | "number_density";
      species: Array<{
        formula: string;              // "CO2", "He-4" (isotopes keep the mass number)
        share: number;                // normalized over the listed species, descending
        limit?: boolean;              // non-detection upper limit, not a measured abundance
      }>;
    };
    structure?: {                     // named vertical layers, for the Structure tab's cross-section (12 bodies)
      datum: "surface" | "one_bar" | "photosphere"; // what altitude 0 means; giants hang off 1 bar and run negative below it
      datum_temperature_k?: number;   // temperature at the datum, so the lowest layer has a base as well as a top
      datum_pressure_pa?: number;     // and the pressure there — the block's own `pressure` where it is quoted at the datum, 1 bar on the giants
      layers: Array<{                 // lowest first; a layer's base is the one below's top, the lowest one's base is `datum`
        role: string;                 // "boundary_layer" | "troposphere" | "stratosphere" | "mesosphere" | "thermosphere" | "exosphere" | "photosphere" | "chromosphere" | "transition_region" | "corona"
        top_km?: number;              // height of the boundary above `datum`
        top_km_range?: [number, number]; // where it actually sits — Earth's tropopause runs 9 km polar to 17 km equatorial
        top_pressure_pa?: number;
        top_temperature_k?: number;
        top_temperature_range_k?: [number, number]; // spread over latitude and solar cycle, not an error bar
        note?: string;                // "well_mixed", "heterosphere", "exobase", "diffuse_top", …; the frontend holds the sentence
        species?: Array<{             // only where a layer's abundance differs from the body's
          formula: string;
          value: number;              // raw mixing ratio in the block's `composition.unit` — NOT a normalized share
        }>;
      }>;
      homopause_km?: number;          // above it species sort by mass and the body's single composition stops meaning anything
      homopause_pressure_pa?: number; // stated in pressure on the giants, where it is a model level rather than a measured height
      scale_height_km?: number;       // exosphere-only bodies: how fast it thins, in place of boundaries it has none of
    };
    sources: Array<{ title: string; url: string; note?: string }>; // works the values are read off, deduped, pressure source first
                                    // `note` is a few words on what this one gave, for the panel's credit line; the credits page keeps the full sentence
  };
  interior?: {                        // what the body is made of, by mass (see below)
    structure?: string;               // "differentiated" | "partially_differentiated" | "undifferentiated" | "rubble_pile" | "fluid"; absent on the estimate route
    estimated?: true;                 // present iff this came from a spectral class rather than a layer model
    analogue?: string;                // estimate route: meteorite group key, e.g. "ordinary_chondrite"
    taxonomy_class?: string;          // estimate route: class as reported, e.g. "Sq"
    taxonomy_scheme?: string;         // estimate route: which taxonomy that letter belongs to
    taxonomy_sources?: string[];      // estimate route: "ssodnet", optionally "mahlke" — ids, not citations
    note?: string;                    // "subsurface_ocean", "hydrated_rock"; only the ocean note is rendered, the rest is provenance metadata
    centre_temperature_k?: number;    // at r=0; closes the innermost layer's span. Present where a body has a published centre rather than a boundary — the Sun and the four giants, whose dilute cores have no radius to hang a boundary on
    centre_temperature_range_k?: [number, number]; // usually the whole claim, the value above being absent: Jupiter's 15000–36000 K is classical adiabat against post-Juno model, not an error bar
    composition?: Array<{             // whole-body roll-up, descending; omitted where layer masses are unknown (the Sun)
      material: string;               // "metal" | "sulfide" | "silicate" | "water" | "volatile" | "organic" | "hydrogen" | "helium" | "heavy_elements"
      share: number;                  // normalized over the materials listed
    }>;
    layers?: Array<{                  // outermost first; layer-model route only, for the Structure tab's cross-section
      role: string;                   // "crust" | "oceanic_crust" | "ice_shell" | "ocean" | "sea" | "mantle" | "ice_mantle" | "magma" | "envelope" | "metallic_hydrogen" | "radiative_zone" | "convective_zone" | "core" | "outer_core" | "inner_core" | "bulk"
                                      // a role can repeat within one body: the Moon's mantle ships twice, solid over partly molten
                                      // "ocean" is liquid water at any depth — Earth's is on the surface, everyone else's is under an ice shell. "sea" is standing liquid that is not water, i.e. Titan's maria, which sit 100 km above Titan's own "ocean"
      outer_radius_km: number;        // the source's own R, which is not the body's exported mean radius — normalize the disc to the outermost layer
      area_fraction?: number;         // share of the globe the layer covers, on the layers that are patches rather than shells. Earth's ocean 0.709, continental crust 0.412, oceanic crust 0.588; Titan's seas 0.011. Layers carrying one are still ordered by radius, but they overlap in depth — Earth's two crusts meet at a coastline, not at a boundary
      base_radius_km?: number;        // where the layer stops, on the layers whose floor is not the next one's top: under Earth's ocean is the sea floor, not the continental crust that follows it. Always present with `area_fraction`, and the two close the arithmetic — area × thickness × 4πR² comes back to the published volume
      mass_fraction?: number;         // of the whole body; absent where a source gives geometry but no mass (the Sun)
      mass_fraction_range?: [number, number]; // the published width, where there is one
      state?: string;                 // "solid" | "liquid" | "partial_melt" | "fluid" | "plasma"; absent where nobody knows
      phase?: string;                 // "ice_i" | "ice_iii" | "ice_v" | "ice_vi" | "ice_vii" — which crystal structure a solid took, where the pressure picks one and the source names it; the high-pressure ice mantles of Ganymede, Callisto and Titan today
      note?: string;                  // "core_size_disputed", "shell_thickness_modelled", …; provenance metadata, except "continental_crust_only" which renames the layer
      derived?: true;                 // the mass is our arithmetic on the source's radii and densities, not a number it quotes
      diffuse?: true;                 // no boundary to draw: `outer_radius_km` is where it fades out, not where it ends
      outer_temperature_k?: number;   // at `outer_radius_km` — geotherms are published at boundaries (Moho, 660 km, CMB, ICB), not averaged over shells. A layer's span is this against the next layer's; the innermost one's inner end is `centre_temperature_k`. Never on the outermost layer: that boundary is the surface, and `temperatures` measures it
      outer_temperature_range_k?: [number, number]; // usually the whole claim, the value above being absent — most of these are a spread across models or experiments rather than an error bar on one
      composition: Array<{            // of this layer, same materials and same sliver cut as the roll-up
        material: string;
        share: number;
        share_range?: [number, number];
      }>;
      detail?: {                      // finer chemistry where the literature gives one (7 layers today)
        unit: "oxide_weight" | "element_weight" | "mineral_volume" | "compound_weight" | "compound_volume";
                                      // whichever the layer's own source publishes; nothing is converted between them. The compound units carry whole molecules — seawater as H₂O and salt, Titan's seas as CH₄/N₂/C₂H₆ — and dissolved ions appear there under their neutral formula
        entries: Array<{ species: string; fraction: number }>; // descending, as the source tabulates them
      };
    }>;
    sources: Array<{ title: string; url: string; note?: string }>; // works the values are read off, deduped, structure source first
                                    // `note` as above; absent on a hand-authored overlay's own citations, which need not carry one
  };
  rings?: RingBlock[];                // ring render bundles, inner → outer — same blocks as `rings` in systems/{bary}.json (see rings.md)
  ring_features?: Record<string, {    // named rings, divisions, gaps, ringlets and arcs — the eight ringed bodies only (see below)
    // Keyed by slug ("cassini-division"), the same key the localized bundle
    // and panel URLs use. Keys run inner → outer, but a parent can follow its
    // children, so a consumer groups by `parent` rather than walking order.
    name: string;                     // English name from the PDS table; the localized bundle overrides it where an entity has a label
    kind: "ring" | "division" | "gap" | "ringlet" | "region" | "arc" | "dust";
    parent?: string;                  // key of the containing feature
    inner_radius_km?: number;         // absent where the source publishes only a radius (the co-orbital rings)
    outer_radius_km?: number;
    mid_radius_km: number;            // always present, derived where the source tabulates boundaries
    width_km?: number;
    radius_approximate?: true;        // the radius is the source moon's orbit, not a measured edge
    optical_depth?: {                 // normal optical depth, as the source qualifies it
      low: number;
      high?: number;                  // absent for a single stated value
      approximate?: true;             // source wrote "~"
      upper_limit?: true;             // source wrote "<"; `low` bounds it from above
    };
    thickness_km?: number;            // full vertical extent, where tabulated
    eccentricity?: number;            // fitted shapes of the Uranian narrow rings
    inclination_deg?: number;
    designation?: string;             // provisional designation still in use ("1986 U2R")
    particles?: "dense" | "dusty";    // macroscopic (back-scatter bright) vs µm dust (forward-scatter bright)
    moons?: Array<{ name: string; id?: string }>; // shepherds, embedded and source moons; `id` absent when the moon isn't in the export
    wikidata_qid?: string;
    note?: string;                    // the PDS table's own description, English, language-independent
  }>;
  ring_sources?: Array<{              // present with `ring_features`: the tables the catalogue was transcribed from, for the panel's credit line
    title: string;                    // the work, e.g. "PDS Ring-Moon Systems Node vital statistics for Saturn's rings"
    url: string;
    organisation: string;
  }>;
  ring_images?: ObjectImage[];        // pictures of the ring system, same shape as an `images` entry (see below)
  temperatures?: {                    // absent only when even the estimate can't be computed (no heliocentric distance)
    // Flat rather than grouped by part: a body's readings all plot on one bar,
    // and a reading needs its part, its kind and what produced it together.
    // Ordered headline-part first (surface, cloud_top, photosphere, corona,
    // core), then min/mean/max. Always kelvin, whatever unit the source used —
    // the scale's stellar segment is logarithmic and only a ratio scale
    // survives that.
    readings: Array<{
      part: "surface" | "cloud_top" | "photosphere" | "corona" | "core";
      kind: "min" | "mean" | "max";
      k: number;                      // kelvin
      // What produces the extreme, where bare min/max would misread: Mercury's
      // are its night and day sides, Earth's are one-off weather records.
      condition?: "night" | "day" | "record" | "modelled"; // "modelled" marks the core bracket — model spread, not a measurement
    }>;
    // `core` readings always come as a min/max pair, read off the interior
    // model's deepest core boundary — `interior.centre_temperature_*` where a
    // body has one, otherwise the innermost core layer's
    // `outer_temperature_*`. The pair is model spread rather than measurement
    // error: nobody has measured a planetary core. They ride
    // in this list so the export shape stays one array, but the panel draws
    // them under Interior rather than on the temperature scale: the Sun's core
    // is 15.5 million K against a 5772 K photosphere, and one bar holding both
    // flattens everything else to a point.
    // Whole-block, not per reading. "estimated" is a radiative equilibrium
    // calculation from heliocentric distance and albedo, which is what most of
    // the catalogue gets; mixing one into measured readings would leave the bar
    // readable as neither. Estimated blocks carry no sources — nothing to cite.
    origin: "measured" | "estimated";
    sources?: Array<{ title: string; url: string; note?: string }>;
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
  discovery_year?: number;            // natural moons only, from the JPL satellite-discovery table
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
  galleries?: ImageGallery[];         // pooled shelves beside `images` (see below)
  orientation?: {                     // IAU rotation polynomial: SPICE PCK, else DAMIT lightcurve spin, else an occultation-fitted ring pole
    // α(T) = pole_ra_0 + pole_ra_1·T   (T = Julian centuries since J2000)
    // δ(T) = pole_dec_0 + pole_dec_1·T
    // W(d) = w0 + w1·d + w2·d²         (d = days since J2000)
    pole_ra_0: number; pole_ra_1: number;
    pole_dec_0: number; pole_dec_1: number;
    w0: number; w1: number; w2: number;
    source?: "pck" | "lightcurve" | "occultation"; // who published these elements; absent on pre-`source` bundles (treat as "pck"). The three sets are disjoint and indistinguishable once merged, so the sidebar credits the pole from this and not from the fact that an orientation exists
    reference?: { title: string; url: string };    // `occultation` only: the paper the pole is fitted in (no kernel covers these four bodies)
  };
  nut_prec?: {                        // SPICE PCK nutation/precession sums (paired with `nut_prec_angles` in /v1/systems/global.json)
    // α += Σ ra[i]  · sin(θ_i(T)),  δ += Σ dec[i] · cos(θ_i(T)),  W += Σ pm[i] · sin(θ_i(T))
    ra: number[]; dec: number[]; pm: number[];
  };
  radii?: {                           // triaxial radii (km, body-fixed X/Y/Z): SPICE PCK, else an occultation-fitted ellipsoid
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

  // IAU surface features of this body (see nomenclature.md). `has_nomenclature`
  // gates the map's label layer; the two below drive the Features tab —
  // notable_features is the same NotableEntry shape as a ft- page's members
  // (host `id` + `feature_id`), ranked by (sitelinks, diameter) and capped at
  // 20, with per-language overrides in LocalizedObjectData.notable_feature_names.
  has_nomenclature?: true;
  notable_features?: NotableEntry[];
  feature_count?: number;             // renderable features on this body; drives the tab badge

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

  // Probe objects only. SPK coverage envelope (union across zones); the
  // focused-probe pause arms a SimClock boundary stop at the data wall. Read
  // only for the focused probe, so it rides here, not in metadata.json.
  coverage?: { start_jd: number; end_jd: number };
}

// Images collected from Wikidata P18/P154 + Wikipedia pageimages (all languages)
interface ObjectImage {
  file: string;           // Commons filename, used as the bundle directory name
  source_url: string;     // Wikimedia Commons file page URL (for license/attribution)
  kind: "photo" | "logo" | "locator" | "radar";  // "locator" feature-only; "radar" = small-body shape-model render
  variants: { [label in "s" | "m" | "xl"]?: string };  // label → extension
  attr: "free" | "credit" | "other";  // attribution tier for social-card use (see images.md)
  width?: number;         // source pixel dimensions (omitted for SVG/WebM passthrough)
  height?: number;
  subject?: string | number;  // what it's a picture of, in a pooled gallery: an Object.id or a feature_id
}

// One pooled shelf in the Images tab, beside the object's own `images`
interface ImageGallery {
  key: "features" | "moons";  // URL token (`&gal=`); collections also key by member Object.id
  subject?: string;           // set when the whole shelf is about one object (collections) — pooled shelves put it per-image instead
  images: ObjectImage[];
}
// Quantities use best-fit units from Wikidata (e.g. "solar_mass", "kilometre")
interface QuantityWithUnit { value: number; unit: string; }
// Currencies use ISO 4217 codes (e.g. "EUR", "USD")
interface CurrencyQuantity { value: number; currency: string; }
```

### `atmosphere`

Hand-curated in `data/src/space_map_data/constants/atmosphere/facts.py`, one
entry per body with a measured gaseous envelope (24 today), each value citing a
key in `ATMOSPHERE_FACT_SOURCES`. Distinct from `v1/atmospheres.json`, which
states the same atmospheres at whichever level their shell is *rendered* from —
Venus at its cloud top, the giants at a ~0.3 bar deck. This block quotes the
level a reader expects: the surface where there is one, the 0.1 bar cloud deck
for the giants, the photosphere for the Sun. Where the two disagree at the same
level, `tests/export/test_atmosphere_facts.py` fails.

`note` names *why* an atmosphere behaves as it does where the classification
leaves that unsaid — Io's snowing out each eclipse, Pluto's following its orbit.
Only the key ships, so the sentence stays translatable.

`share` is normalized over the species listed, so what it is a share *of*
depends on `unit`: a real mixing ratio for volume/mass fractions, but for the
thin envelopes a ratio of column or number densities measured separately, at
different times and geometries. The frontend says so in a tooltip and hatches
`limit` species.

`structure` is the vertical axis that pressure sits on, from
`constants/atmosphere/structure.py` — twelve bodies, the ones whose layers
anyone has named. Each layer is described by its *top*, because a boundary is
almost always a turning point in temperature rather than a surface, and what a
source pins is sometimes a height, sometimes a pressure, rarely both. Every
field is optional for that reason; every internal boundary does have a height.

A layer's `species` are raw mixing ratios in the block's own `composition.unit`,
**not** normalized shares — a layer lists a species only where its abundance
differs from the body's, and Titan's stratospheric methane normalized against
itself would draw a pure-methane layer. Composition otherwise stays on the
block: below the homopause an atmosphere is well mixed, and repeating the
body's numbers per layer would be one measurement written five times.

Every reading on a layer is its **top**, so a layer is only readable as a layer
once the base is chained in: it is the layer below's `top_temperature_k` or
`top_pressure_pa`, and for the lowest one it is `datum_temperature_k` or
`datum_pressure_pa`. Skip that and Venus's troposphere reads 245 K, its
tropopause, on a planet whose surface is 737 K. `datum_temperature_k` is the
body's measured surface temperature — the same value the `temperatures` block
carries — except on the four giants, whose datum is the 1 bar level and who
state one of their own. `datum_pressure_pa` is the block's own `pressure`,
shipped only where that is quoted at the datum (never a `cloud_top`, never an
`upper_limit`); on the giants it is 1 bar by definition of the datum. Either
end can still be missing where nobody measured it: nothing pins Neptune's
profile between its tropopause and its thermosphere, and no exosphere has a
top.

The cross-section draws to scale up to the highest layer that is *not*
`thermosphere`, `exosphere` or `corona`; those three are capped to a fixed band
with their real height in the label, because they hold no mass and Earth's
exosphere alone is 100× its mesosphere. That boundary always has a `top_km`.
The one body with nothing below the cap is Callisto, an exosphere by itself,
which carries `scale_height_km` instead.

### `interior`

Three routes, one shape. Bodies a mission or a seismometer actually constrained
have a hand-curated layer model in
`data/src/space_map_data/constants/interior/bodies.py` (31 today); asteroids
that only have a spectrum get their meteorite analogue's bulk chemistry from
`taxonomy.py`, keyed on the SsODNet class we ingest, and carry `estimated`
so the panel can say "estimated from its S-type spectrum" rather than "is". A
layer model always wins where a body has both — Dawn's gravity beats the fact
that V-types look like HEDs.

The third is for objects that have no database row to hang a constant off: the
hand-authored overlay carries the layer model in the entry itself, along with
its own citations, and it reaches this same shape through the same roll-up and
the same checks. Nothing in the exported block says which route it took.

Two shapes ship with it. The roll-up, one share per material summed over the
layers, is what the Overview's composition chart draws and all the estimate
route can offer. `layers` underneath it is what the Structure tab's
cross-section draws, and only the layer-model route carries it — the ~150,000
asteroids on the estimate route have no layers to spend bytes on.

`outer_radius_km` is the source's own R rather than the body's exported mean
radius; the two disagree by a few km on Europa depending on the paper. Normalize
the disc to the outermost layer's radius, not to the body's, or the stack shows
a gap or an overshoot at the surface. `derived` marks a mass that is our own
arithmetic on the source's radii and densities, and `diffuse` a layer with no
boundary at all — Jupiter's core is heavy elements smeared through the envelope,
so its radius is where it fades out.

`state` is the state of matter; `phase` is which crystal structure a solid took,
and only appears where the pressure picks one and the source names it. "Solid
water" is true of an icy moon's shell and of the ice mantle 800 km below it, and
that difference is the whole reason the second layer exists — so a consumer with
a `phase` should say "ice VI" and drop the state, rather than print both.

Temperature runs on the boundaries rather than on the shells, because that is
the form the literature publishes: a geotherm is quoted at the Moho, at 660 km,
at the core-mantle boundary. A layer's two ends are its own
`outer_temperature_*` and the next layer down's, and the innermost layer closes
against `centre_temperature_*` on the body — the same contract the atmosphere
layers use, where each is described by its top and the lowest closes against the
datum. Twenty readings across seventeen bodies carry one today; everything else
has none, and a layer with no number should draw none rather than interpolate.
The outermost layer never carries one: its boundary is the surface, which
`temperatures` already measures.

The roll-up is a mass balance over layers rather than an elemental one — water
bound in a phyllosilicate counts as water, not as oxygen shared out among the
rocks — so a reader gets "two-thirds rock, one-third water" rather than an
oxide table. `heavy_elements` is the astronomer's Z, everything above helium,
and says the split is unresolved: an ice giant's are 0.76 of the planet as
rock and 0.89 as ice with nothing choosing between them.

Materials below 0.5% are dropped and the rest renormalized — Tethys's 0.1% of
rock drew an invisible sliver with a legend entry. The cut runs per bar, so a
material can miss the whole-body roll-up and still fill its own layer: a
sulphur-bearing core a percent of the body is 20% of the core and 0.2% of the
planet.

`sources` is the works behind what the panel shows, not the whole model: the
structure, every layer the cross-section draws, and the chemistry of the
materials that survived the sliver cut somewhere. The full bibliography is in
`credits.json` as `interior_references`.

`taxonomy_sources` credits the class letter rather than the composition, and
ships ids because 171,000 asteroids carry it — full citations would be
megabytes of bundle for two names that never vary. Always `"ssodnet"`, plus
`"mahlke"` where the class was reported under Mahlke's scheme or where the
albedo cut resolved an X into an E or an M. The frontend resolves both from
`$lib/credits/taxonomy-sources`, and the credits page lists them under object
metadata rather than in `interior_references`.

### `ring_features`

The catalogue behind the ring panel, from
`data/src/space_map_data/constants/rings/catalog.py`. For the four giants it is
every named feature the PDS Ring-Moon Systems Node's "vital statistics" tables
carry, cross-checked against the IAU Gazetteer's ring page. For Chariklo,
Haumea, Quaoar and Chiron there is no such table and the rows come from the
occultation papers instead, so those four carry only a handful of features
each, no IAU names, and — for Chiron — rings that the sources agree are not
permanent. Saturn's 43 rows are the largest table, so the whole thing rides
the object bundle rather than a lazily fetched tier like surface features do.

It is a catalogue, not a render manifest. The `rings` array says what the
scene draws; this says what the rings are, and includes features the renderer
deliberately omits — Saturn's Phoebe ring (it sits in Phoebe's orbital plane,
not Saturn's equator) and the arcs of Neptune, Quaoar and Chiron (azimuthal
structure a radial strip cannot carry). Where both describe
the same ring they agree by test, not by construction: the render tables carry
their own tuning and occasionally split a row (the E ring ships as two bundle
halves so its optical depth peaks at Enceladus).

Per-feature prose is split by whether it has a language. `note` is the PDS
table's own sentence and is English wherever it appears; the localized bundle
carries the Wikipedia extract for the locales that have an article. That
coverage is thin and lopsided — English Wikipedia folds every ring into "Rings
of X", so only the Cassini Division has an English article, while French and
Italian have nearly the full set. A panel showing one feature therefore has,
in order: the localized extract, else the English `note`, else nothing but
numbers.

Both the global and localized blocks are keyed by the same slug, so a feature
reads as one lookup in each. The keys are emitted inner → outer for
legibility, but that ordering does not put a parent before its children —
Uranus' ζ dust extensions lie inside the ζ ring they belong to — so a
consumer builds the tree by grouping on `parent` and sorting siblings by
radius.

`ring_sources` rides alongside: the same works the credits page lists for this
body's catalogue — PDS and IAU tables for the giants, the occultation papers
for the small bodies — trimmed to title and link so the panel can credit what
it shows without pulling the whole credits bundle. The per-source `contribution`
sentence stays on the credits page.

`ring_images` are pictures of the *rings*, kept apart from the body's own
`images` (portraits of the planet): they are selected from the "Rings of X"
topic item rather than the body's, and the first opens the Rings tab. Same
shape as an `images` entry, resolving against the same `/v1/images/<file>/`
bundles — including the credit, which rides in the variant's own metadata. Two
of the eight ringed bodies have none, since neither Haumea's nor Quaoar's rings
have an article in any language; the tab and the collection tile fall back to
the ring-plane chart. The same selection is pooled onto the `cat-ring-systems`
page — see `docs/export-format/groups.md`.

`galleries` are the *pooled* shelves: `features` takes one picture of each of
the body's notable surface features, `moons` up to two of each notable moon,
both walked in the ranking those lists already carry and interleaved so a
capped shelf still spans the system. Each picture's `subject` names what it is
of — a `feature_id` under `features`, an `Object.id` under `moons` — which is
what the tile is labelled by and what the viewer links out to. Files already
shown under `images` or `ring_images` are not repeated, and IAU locator maps
are dropped: they are outline drawings, not pictures of the feature. Shelf
sizes are `FEATURE_GALLERY_LIMIT` / `MOON_GALLERY_LIMIT` in
`export/objects/galleries.py`.

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
  launch_vehicle?: EntityRef;     // Wikidata P375; links to the family /g/lv-<slug> for both family QIDs and known specific configurations (name stays the variant, e.g. "Atlas V 401"), else a plain Wikipedia ref
  launch_site?: EntityRef;        // CelesTrak-derived takes precedence over Wikidata P1427
  developer?: EntityRef[];
  funder?: EntityRef[];
  country_of_origin?: EntityRef[];
  launch_contractor?: EntityRef[];
  part_of?: EntityRef[];          // Wikidata P361; QIDs already shown via a CelesTrak-derived field (constellation, bus, launch_site, operators, manufacturer) are dropped
  ring_features?: Record<string, {  // same keys as the global `ring_features` map; only the features this locale has anything for
    name?: string;                  // Wikidata label in this language. Never present for `en`: the catalogue name is the English name, and Wikidata's English labels are translations of the fr/it article titles ("Huygens Division" for the IAU's Huygens Gap)
    extract?: string;               // Wikipedia lead extract; absent when the locale has no article
    url?: string;                   // article URL
  }>;
  ring_system?: {                   // the "Rings of X" article — the ring panel's opening blurb. Unlike the individual features, all four exist in every shipped language
    name?: string;
    extract?: string;
    url?: string;
  };
  interior_page?: {                 // "Internal structure of X" — the Structure tab's interior blurb. 10 bodies, 7 of them Italian-only
    extract: string;                // always set: an article whose intro extract comes back empty is dropped rather than shipped as a bare link
    url?: string;
  };
  atmosphere_page?: {               // "Atmosphere of X" — the Structure tab's atmosphere blurb. 17 bodies, 12 with an English article
    extract: string;
    url?: string;
  };
  wikipedia?: {
    extract?: string;
    description?: string;
    url?: string;        // URL
  };
  notable_moon_names?: Record<string, string>; // notable-moon Object.id → localized label, only where it differs from the global name
  notable_moon_descriptions?: Record<string, string>; // notable-moon Object.id → localized Wikidata short description, for the planet-page moon lineup hover tooltip
  notable_feature_names?: Record<string, string>; // notable-feature "<body_id>:<feature_id>" → localized label, only where it differs
  notable_satellite_names?: Record<string, string>; // featured-satellite id-or-slug → localized label, only where it differs
  fragment_names?: Record<string, string>;     // fragment Object.id → localized label, only where it differs from the global name
  mission_member_names?: Record<string, string>; // mission-member Object.id → localized label, only where it differs from the global name
}

interface EntityRef { name: string; short_name?: string; wikipedia?: string; }
```
