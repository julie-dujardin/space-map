# Group detail files

Aggregation entities behind `/g/<slug>` pages (constellations, launch vehicles,
organizations, launch sites, countries, orbit classes, small-body flags, and IAU
surface-feature types).
Every group type's slug carries a type prefix (`const-`, `lv-`, `org-`, `site-`,
`bus-`, `country-`, `class-`, `flag-`, `cat-`, `comet-family-`, `ft-`) so slugs
never collide across types and a slug's type is recognizable on sight. A launch
vehicle (`lv-<slug>`) merges a rocket's spent stages tracked in orbit (the
former ROCKET `const-` page) with its GCAT launchlog history; `UPPER_STAGE`
constellations stay `const-`. Earth orbiters split across two category pages by
object type: working payloads under `cat-satellites`, spent stages and breakup
fragments under `cat-debris` (whose children are the curated breakup clouds plus
the `lv-` families). The `class-` orbit zones are shared — they're regions of
space, not fleets, so they hold both. An organization
(`org-<slug>`) is the merged company/agency entity that subsumes the former
operator and manufacturer roles; its roles are surfaced as tags rather than
separate pages. Group bundles use the **same hash-bucketing scheme as object
bundles** (sha256 first-4-bytes BE, mod N) so the frontend reuses
`hashBucket` for slug → bundle resolution.

Bucket counts ship in `metadata.json` under `group_bundles` as
`{ global: N, <lang>: N, ... }`. Target bundle sizes: `K_global = 1000`,
`K_localized = 600`. Source: `data/src/space_map_data/export/groups/`.

## `groups/__index__.json`

Small, **ungzipped** map written once. Loaded eagerly to validate
`/g/<slug>` URLs and render group listings without a bundle fetch:

```typescript
interface GroupIndexEntry {
  type: GroupType;            // "constellation" | "launch_vehicle" | "organization" | "launch_site" | "bus" | "country" | "orbit_class" | "small_body_flag" | "split_comet" | "mission" | "feature_type"
  applies_to: GroupCategory;  // "earth_sat" | "small_body" | "probe" | "category" | "surface_feature"
  n: number;                  // member count (surface features on a feature_type group)
  code?: string;              // feature_type groups only: the 2-letter IAU descriptor code (slug ↔ code without a duplicated table)
}
// File body: Record<slug, GroupIndexEntry>
```

## Global (`groups/__global__/{bucket}.json.gz`)

Written for every group. `bucket = sha256(slug)[:4] % N_global`. Each
bundle is a JSON object `{ "<slug>": GlobalGroupData, ... }`.

A `NotableEntry` is a denormalized record for the detail-page strip + list,
shared by group `notable_members` and object `notable_moons`:

```typescript
interface NotableEntry {
  name: string;                     // English Wikidata label (matching object bundles), or the DB fallback name
  id?: string;                      // full Object.id; route /<type>/<id> (e.g. spkid-2000004, naif-502). Absent on group entries
  group?: string;                   // group slug; route /g/<slug> instead of an object (featured constellations in notable_satellites)
  feature_id?: number;              // IAU feature id (feature_type groups); `id` holds the host body — route /<type>/<id>/f/<feature_id>. Label/description overrides key on "<id>:<feature_id>"
  diameter_km?: number;             // equivalent-sphere diameter (members) / mean PCK-radii diameter (moons)
  mass_kg?: number;                 // body mass from PCK GM (major bodies only — e.g. category planet/moon members)
  radii?: { a: number; b: number; c: number }; // triaxial PCK radii km, body-fixed X/Y/Z (equatorial a, polar c); major bodies, Ceres/Pluto + PCK moons
  radius_km?: number;               // scalar render radius (Wikidata P2120); lineup size fallback when no radii/diameter (most TNO dwarfs)
  pole?: { ra: number; dec: number; source?: "lightcurve" | "occultation" }; // IAU J2000 pole RA/Dec (deg); the lineup's true axial tilt. `source` is present only when the pole isn't the PCK's — small-body members tilt on DAMIT lightcurve poles, which the footer credits to DAMIT rather than to the IAU/NAIF
  albedo?: number;                  // SBDB geometric albedo (small bodies only); see `color`
  spec?: string;                    // SBDB taxonomic type, SMASS else Tholen (small bodies only); see `color`
  color?: string;                   // #rrggbb physically-derived surface colour (TrueColorTools). Small bodies: per-body TCT/SBDB colour, else taxonomy chroma × albedo, else albedo grey. Moons: per-body TCT colour (NAIF-keyed), else neutral grey × JPL Horizons geometric albedo. Absent → frontend generic tint
  first_obs?: string;               // discovery proxy — YYYY-MM-DD or YYYY (members only; moons omit it)
  model?: string;                   // shape-model slug (v1/models/<slug>/); lineup renders the mesh instead of a sphere. shape_model bundles only — spacecraft slugs excluded
  texture?: boolean;                // v1/textures/<id>/ surface map exists; explicit false ⇒ lineup skips the fetch. Absent only on pre-flag bundles (and mission/fragment strips), which the lineup still probes
  ring_mass?: RingMass;             // mass of the member's *rings*, not the member; `cat-ring-systems` only, and only for the six systems a source puts a figure on. Same shape as the object bundle's `ring_stats.mass` (see objects.md)
  thumbnail?: { file: string; label: "s" | "m" | "xl"; ext: string }; // smallest emitted variant, same picker as search cards
}
```

```typescript
interface GlobalGroupData {
  slug: string;
  type: GroupType;
  applies_to: GroupCategory;
  member_count: number;
  // Earth-orbiter groups only: the `cat-` slug the breadcrumb climbs to.
  // `applies_to` can't say — `cat-satellites` and `cat-debris` share `earth_sat`.
  // Spent stages (`lv-`) and breakup clouds go to `cat-debris`; every other
  // earth-sat group (fleets, operators, launch sites, orbit zones) to
  // `cat-satellites`.
  parent_category?: string;
  // IAU-named members; present (when > 0) on asteroid orbit_class groups and
  // the Asteroids category — asteroids are only ~1.7 % named. Comets are
  // omitted: they all carry a designation, so named/total is meaningless.
  named_count?: number;
  wikidata_qid?: string;
  url?: string;                     // Fallback external URL when no Wikidata QID
  website?: string;                 // Wikidata P856
  categories?: SatelliteCategory[]; // Constellation-only; top-level use cases (communications, navigation, ...)
  orbit_classes?: string[];         // Constellation-only; the zone slug(s) it calls home, so it lists among that zone's members
  roles?: ("operator" | "manufacturer")[]; // Organization-only; role tags shown as header badges

  // Earth-sat groups (constellation / organization / launch_site / country).
  // Computed from SATCAT; absent on small-body groups. Also present on the
  // Satellites and Debris categories, each summed over the primary shape
  // classes (LEO/MEO/...) for its own side of the payload/debris split.
  launch_histogram?: Record<string, number>;  // year string → count, sorted ascending
  first_launch_date?: string;                 // Earliest SATCAT launch_date among members (ISO date string)
  active_count?: number;                      // Members with ops_status operational/partial/extended and no decay
                                              // Also on cat-satellites, summed over the primary shape classes.
                                              // Not on cat-debris: the few fragments SATCAT still calls
                                              // operational are a data lag, not a fact about the population.
  decayed_count?: number;                     // Members with a SATCAT decay_date. Absent on the zone (class-)
                                              // and category pages: that scan counts current occupancy only.

  // Launch-vehicle groups (lv-<slug>) only. Computed from the GCAT launchlog,
  // not SATCAT — so launch_histogram + first_launch_date above are overridden
  // with the full launch history (the satcat figures only see spent stages
  // still catalogued in orbit; active_count / decayed_count keep that view).
  // Launches dedupe by GCAT launch_tag; payloads are the raw per-object rows
  // (many share one launch). Outcome from GCAT Launch_Code char 2 (S/F).
  launch_count?: number;                      // Distinct launches
  payload_count?: number;                     // Payload rows across all launches
  success_count?: number;                     // Launches with a success outcome
  failure_count?: number;                     // Launches with a failure outcome
  last_launch_date?: string;                  // Latest launch date (ISO string)
  variants?: {                                // Per-variant breakdown, most-launched first (top 48, paginated)
    name: string;                             // GCAT lv_type, e.g. "Atlas V 551" — also the join key into LocalizedGroupData.variant_refs
    n: number;                                // Distinct launches of this variant
    launch_mass_t?: number;                   // lv.tsv specs, present when GCAT records them
    leo_capacity_kg?: number;
    gto_capacity_kg?: number;
    thrust_kn?: number;
    length_m?: number;
    diameter_m?: number;
  }[];
  reusable_vehicles?: {                        // Top individual reusable vehicles by flights (top 40, paginated); Shuttle orbiters + Falcon cores
    name: string;                             // Vehicle id + display: orbiter name ("Discovery") or Falcon core serial ("B1067"); join key into LocalizedGroupData.reusable_vehicle_refs
    n: number;                                // Flights flown by this vehicle
    first_flight?: string;                    // ISO date of first/last flight
    last_flight?: string;
  }[];

  // Small-body groups (orbit_class / small_body_flag).
  // Computed from SBDB.first_obs (YYYY-MM-DD or partial YYYY).
  // Rows lacking a parseable year are excluded from the histogram but
  // still count in member_count. NEO/PHA flags overlap with the orbit
  // class an object belongs to, so the same row contributes to multiple
  // small-body histograms. Also present on the Asteroids and Comets
  // categories, summed over their constituent orbit classes (flags excluded).
  discovery_histogram?: Record<string, number>;  // year string → count, sorted ascending

  // Biggest member by diameter; absent when nothing has a measured size.
  // Present on orbit_class groups, flag-neo/flag-pha, and the Asteroids /
  // Comets / Planets / Dwarf planets / Moons categories. The small-body ones
  // inherit the largest of whatever classes partition them, measured from
  // SBDB; the major-body categories rank the PCK radii the renderer uses and
  // report 2 × the mean of the three axes.
  largest_body?: {
    name: string;        // SBDB full_name (fallback: name, pdes, spkid) or Object.name
    diameter_km: number; // equivalent-sphere diameter
    primary_type: "spkid" | "object";  // "object" ids are whole; spkid ones need the prefix
    primary_id: string;  // SBDB.spkid → /o/spkid-<id>, or Object.id → /<type>/<id>
  };

  // PHA member count for orbit_class groups and the Asteroids category;
  // absent when 0 and on flag-pha itself (self-link suppressed). NEO is
  // intentionally not shipped — by definition it's 100 % on IEO/ATE/APO/AMO
  // and 0 % on every other class.
  pha?: { n: number; primary_type: "group"; primary_id: "flag-pha" };

  // Top 20 members picked at export time, ordered by
  // (image_available, sitelinks_count, diameter desc, H asc, spkid).
  // Present on small-body orbit_class groups, flag-neo/flag-pha, the Asteroids
  // (dwarf planets excluded) + Comets categories, and every earth-sat zone
  // (earth_orbit_class) — where the list is sitelink-ranked and mixes in member
  // constellations (carrying `group` instead of `id`). Denormalized so
  // the strip + members list render without per-object bundle fetches.
  // Names are the English Wikidata label (matching object bundles), with
  // per-language overrides in LocalizedGroupData.notable_member_names.
  // Shares the NotableEntry shape with GlobalObjectData.notable_moons.
  // On a `split_comet` group (slug `comet-family-<pdes>`) these are the
  // family's fragments — the parentless counterpart to the `fragments` list a
  // catalogued parent comet carries on its own object page. On a `mission`
  // group (slug `mission-<slug>`) these are the mission's craft, primary first.
  // On the `cat-planets` / `cat-dwarf-planets` / `cat-moons` category pages
  // these are the bodies the lineup hero renders (planets in heliocentric
  // order; dwarf planets and moons by prominence).
  // On `cat-ring-systems` these are every body the ring catalogue covers, in
  // its curated order (the four giants outward, then the four small bodies);
  // the page tiles them onto their Rings tabs and charts their `ring_mass`
  // against each other. They are counted by their own categories too, so the
  // tally stays out of the `cat-solar-system` total.
  // On a `feature_type` group (slug `ft-<slug>`) these are surface features
  // (carrying `feature_id` beside their host body `id`), ranked by the
  // feature's own Wikidata sitelink count then diameter.
  notable_members?: NotableEntry[];

  // Feature-type groups (ft-<slug>, one per IAU 2-letter descriptor code) only.
  // Computed from the IAU gazetteer over the same features the map and search
  // index carry (matched to a body, with a position and a type code), so
  // member_count is the feature tally. A type the IAU defines but the current
  // gazetteer doesn't use still gets a page, with these fields absent.
  body_count?: number;                        // Distinct bodies carrying this feature type
  feature_bodies?: {                          // Bar-chart rows, most features first — every body the type appears on (paginated)
    name: string;                             // English Object.name; per-language overrides in LocalizedGroupData.body_names
    n: number;                                // Features of this type on that body
    primary_type: "object";
    primary_id: string;                       // Object.id; route /<type>/<id>
  }[];
  largest_feature?: {                         // Biggest example by IAU diameter; absent when none is measured
    name: string;                             // IAU feature name
    diameter_km: number;
    primary_type: string;                     // host body id type ("naif")
    primary_id: string;                       // host body id value; route /<type>/<id>/f/<secondary_id>
    secondary_type: "feature";
    secondary_id: string;                     // IAU feature id
  };
  first_approval_date?: string;               // Earliest IAU name-approval date among the features (ISO date)
  last_approval_date?: string;                // Latest IAU name-approval date (ISO date)
  approval_histogram?: Record<string, number>; // Approval year string → count, sorted ascending
  median_diameter_km?: number;                // Typical size of the landform; absent when under 5 members
                                              // — or under half of them — carry a measured diameter

  // `cat-surface-features` (the browse node above the ft- pages) only. Its
  // member_count is the whole gazetteer's feature tally, `body_count` above
  // spans every type, and `approval_histogram` sums every type's approvals.
  feature_type_count?: number;                // Types with at least one feature (= its child chips)
  feature_families?: {                        // Curated landform families (constants/nomenclature/families.py), narrative order
    key: string;                              // family key; the frontend localizes it (`feature_family_<key>`)
    n: number;                                // features across the family's types
    types: string[];                          // ft- slugs, most-populated first; unused types are omitted
  }[];
  naming_origins?: {                          // Name etymology (IAU `ethnicity`), most-named first, top 60 — the tail is one-offs
    name: string;                             // IAU-supplied English label ("Germany", "Greek", …); not localized
    n: number;
  }[];

  // `mission` groups only — focus redirect to the primary probe (not a filter).
  primary?: { primary_type: "object"; primary_id: string };  // "probe-<id>"

  // Stat-row facts, one page family each (export/groups/stats.py). Every one
  // is optional and only the pages listed emit it.
  median_perigee_km?: number;   // earth_orbit_class — typical perigee of the zone's population
  median_moid_au?: number;      // flag-neo / flag-pha — typical Earth MOID
  moon_total?: number;          // cat-planets / cat-dwarf-planets — moons hosted across the category
  host_count?: number;          // cat-moons — planet/dwarf hosts that have at least one moon
  child_group_count?: number;   // cat-comets (split families), cat-probes (missions),
                                // cat-debris (distinct fragment sources)
  launch_year?: number;         // mission- (its launch), cat-probes (the first probe launch)
  mission_status?: "operating" | "lost" | "ended";  // mission- — the primary craft's curated status
  discovery_year?: number;      // comet-family- — earliest first_obs among the fragments;
                                // cat-ring-systems — the year the earliest system was found (1610)
  perihelion_au?: number;       // comet-family- — smallest fragment perihelion (the family's orbit)
  ring_feature_count?: number;  // cat-ring-systems — rows in the ring catalogue across every
                                // system: the rings the tiles count plus the gaps, divisions,
                                // ringlets, regions and arcs inside them
  // cat-ring-systems — the system reaching furthest from its host, diffuse rows included
  // (Saturn's answer is the Phoebe ring). The card links to that body's Rings tab.
  widest_rings?: { name: string; span_km: number; primary_type: "object"; primary_id: string };

  inception?: string;               // Wikidata P571 — programme/operator inception (ISO date)
  dissolved?: string;               // Wikidata P576 — programme dissolution (ISO date)
  images?: ObjectImage[];           // Same pipeline / layout as GlobalObjectData.images
  galleries?: ImageGallery[];       // one shelf per notable member, keyed by its Object.id
}
```

On `cat-ring-systems` the images are the per-body `ring_images` pooled (see
`docs/export-format/objects.md`), selected from the "Rings of X" topic items
(`constants/rings/wikidata.py`) rather than from the group's own Wikidata item
or its members: the item is the generic "planetary ring" concept, and the member
fallback would fill a page about rings with portraits of Jupiter and Saturn.
Saturn's article leads, since the first image is what the collection's tile
shows. Haumea and Quaoar contribute nothing — neither has a ring article in any
language.

`galleries` gives a collection's Images tab one shelf per member rather than
one undifferentiated pile: a member's `key` and `subject` are both its
`Object.id`, so the shelf is named after it and links to its page. Members come
from two rankings unioned — the top of the notable list, and the members with
the most pictures — which mostly agree, since `image_available` is already the
notable list's first sort key; the union is there so nothing notable and
nothing well-photographed is missed. Files the group's own `images` already
show are dropped, since a member-fallback group draws that gallery from these
very members. Counts are `MEMBER_GALLERY_COUNT` (per ranking) and
`MEMBER_GALLERY_IMAGES` (per shelf) in `export/groups/bundles.py`. The
localized bundles carry `image_titles` for both, keyed by filename — see
`docs/export-format/objects.md`.

The result is photographs only: cutaway schemes and belt maps are dropped for
every subject except an individual craft, since they restate what the scene and
the charts already draw, and they exist once per language
(`image_exclusion_reason(drop_subject_diagrams=...)`). That applies across the
tiers, not just here — a body, an orbit zone or a category no longer selects
one.

## `groups/__orbit_samples__.json.gz`

Shared sample set for the orbit-class scatter plot shown on small-body
group pages. Fetched once and cached. Population per orbit class is read
from `__index__.json` (the `n` field) — counts are not duplicated here.

Allocation is sqrt-weighted by class population with a per-class floor of
`5` (or the class's population, whichever is smaller). No upper cap, so
MBA naturally dominates the chart. Target total ≈ 1000; actual count
typically lands in the 1000–1100 range. Source:
`build_orbit_class_samples` in
`data/src/space_map_data/export/groups/small_body.py`.

```typescript
interface OrbitClassSample {
  slug: string;        // class-<OrbitClass.name>, e.g. "class-Main-belt"
  name: string;        // SBDB full_name → name → pdes fallback
  a: number | null;    // Semi-major axis [AU]; null for parabolic (e = 1) comets
  e: number;           // Eccentricity
  q: number;           // Perihelion distance [AU]
  i: number | null;    // Inclination to ecliptic [deg]
  neo: boolean;
  pha: boolean;
}
interface OrbitSamplesFile {
  samples: OrbitClassSample[];
}
```

## `groups/__solar_system_map__.json.gz`

The Solar System minimap — the lineup hero on the `cat-solar-system` page. Sun +
planets + dwarf planets + the largest main-belt asteroids on a log
heliocentric-distance axis at true relative diameters, each nudged vertically by
its inclination, plus the Main-belt and Kuiper-belt bands. Fetched once and cached (tiny). Belt extents are robust
quantiles of the in-memory orbit-class samples (no extra catalog scan); the far
scattered dwarfs (Eris, Sedna) are still exported and clip off the chart's right
edge on the frontend. Source: `build_solar_system_map` in
`data/src/space_map_data/export/groups/solar_system_map.py`.

Planet `a`/`i` come from JPL Horizons mean elements baked at download time
(`planet_elements.json`; the majors carry no SBDB row); dwarf `a`/`i` from SBDB
(Pluto falls back to the same Horizons table); diameters from PCK radii (Sun +
planets) or Wikidata (dwarfs). `color` is set only for SBDB-tracked
small bodies — the frontend tints the rest from its shared palette.

```typescript
interface SolarSystemMapObject {
  id: string;          // Object.id — routing/focus id and localized-name key
  qid: string | null;  // Wikidata QID
  name: string;        // English fallback; frontend prefers the localized label
  kind: 'star' | 'planet' | 'dwarf' | 'asteroid' | 'moon';
  a: number;           // Semi-major axis [AU] — log x (moons inherit their planet's)
  i: number;           // Inclination to ecliptic [deg] — vertical offset (0 for moons)
  diameter_km: number;
  color: string | null; // resolved small-body tint; null → frontend palette
  // Moons only — major moons (≥1000 km, ≤4/planet) stacked above their planet:
  parent?: string;      // parent planet Object.id (placement anchor + link target)
  link_parent?: boolean; // true → link to the planet's moons tab; false → the moon
  // Ringed planets only (Saturn): ring span as multiples of the equatorial radius:
  rings?: { inner: number; outer: number };
  moon_count?: number;  // planets: total moons, shown in the moon tooltip
}
interface SolarSystemMapBelt {
  slug: string;        // linked group slug (class-MBA / class-TNO)
  label: string;       // displayed band label ("Main belt" / "Kuiper belt")
  kind: 'asteroid_belt' | 'kuiper_belt';
  inner_au: number;
  outer_au: number;
}
interface SolarSystemMapFile {
  objects: SolarSystemMapObject[];
  belts: SolarSystemMapBelt[];
}
```

## `groups/__sat_orbit_samples__.json.gz`

Earth-sat scatter samples. Same role as `__orbit_samples__.json.gz` but for
the 17-zone Earth orbit-class chart (`class-LEO` … `class-EQU`). Sampled
per shape class (one per sat: VLEO/LEO/MEO/HEO/GSO/GEO/IGSO/GRA/MOL/TUN/
GTO/CIS/VHEO, most specific wins) with sqrt-weighted allocation and a
per-class floor; total ≈ 1000. Each dot also carries its inclination band
(SSO/Polar/Retrograde/Equatorial, low orbits only) via `classes` so band
zones light up the same dots when focused. Source:
`build_earth_orbit_classes` in
`data/src/space_map_data/export/groups/earth_sat.py`.

Source data:
- Perigee/apogee (km altitude above Earth surface) from CelesTrak SATCAT
  (`satcat.perigee`, `satcat.apogee`).
- Inclination from the latest CelesTrak GP snapshot on disk
  (`gp-active.csv` + `groups/*.csv`); ~45 % of currently-active SATCAT
  rows have no GP entry and therefore no inclination — those park in the
  apogee/perigee-driven fallbacks (GSO/GTO/HEO instead of GEO/IGSO/MOL/
  TUN) and carry no inclination band. Space-Track ingest is planned to
  close that gap.
- Decayed sats (`decay_date` set) and non-Earth-centred orbits
  (`orbit_center != EARTH`) are excluded.

```typescript
interface EarthOrbitSample {
  slug: string;                  // Shape class slug, e.g. "class-LEO"
  name: string;                  // SATCAT OBJECT_NAME → Object.name fallback
  perigee_km: number;            // km above Earth surface
  apogee_km: number;             // km above Earth surface
  inclination_deg: number | null; // deg; null when no GP row
  classes: string[];             // Shape class + optional inclination band
}
interface EarthOrbitSamplesFile {
  samples: EarthOrbitSample[];
}
```

## Earth-sat orbit-class groups (`class-LEO`, `class-SSO`, …)

The 17 Earth orbit zones from
`data/src/space_map_data/constants/earth_sats/orbit_class.py` ship as
`GroupType.EARTH_ORBIT_CLASS` groups with bundles, membership entries in
`membership/earth.json.gz`, and bucket pages under `groups/__global__/`
and `groups/{lang}/` — the same shape as constellation/organization/etc.
groups. Per-class bundles carry `launch_histogram`, `first_launch_date`,
`active_count`, `median_perigee_km`, plus a localized `constellations` cross-link table
(no `launch_sites` breakdown). An object holds exactly one shape class plus at most
one inclination band (e.g. VLEO + SSO) — membership rules in
`classify_earth_orbit`.

Each zone also bakes a `notable_members` list (top 20, sitelink-ranked) that
merges its most-notable sats with the constellations whose dominant zone it is
(those carry `group` instead of `id`, routing to `/g/const-<slug>`). The
members tab continues the same mixed, sitelink-ranked list from the search index
— sats via `object.groups`, constellations via `group.orbit_classes`.

## Localized (`groups/{lang}/{bucket}.json.gz`)

Per-language bundles. `bucket = sha256(slug)[:4] % N_{lang}` where
`N_{lang}` is that language's count in `metadata.group_bundles`. A group
appears in a language only when it has Wikidata/Wikipedia data for that
language. On a 404 the frontend gives up — there is no English fallback
tier.

```typescript
interface LocalizedGroupData {
  name?: string;                      // Localized Wikidata label. Categories use a hand-set plural; orbit_class groups omit it (frontend uses `orbit_class_<NAME>` i18n keys, keeping IMB/MBA/OMB distinct).
  description?: string;
  wikipedia?: { extract?: string; description?: string; url?: string };
  operators?: EntityRef[];            // Constellation operators (constants, not Wikidata P137); link to /g/org-<slug>
  manufacturers?: EntityRef[];        // Constellation hardware primes; on a bus page, the bus's single manufacturer; link to /g/org-<slug>
  country_of_origin?: EntityRef[];    // Omitted on country pages (would be self)
  instance_of?: EntityRef[];
  launch_sites?: { name: string; n: number; primary_type: "group"; primary_id: string }[];   // Top sites by member count (top 24, paginated)
  constellations?: { name: string; n: number; primary_type: "group"; primary_id: string }[]; // Top constellations represented (top 24, or 40 on the Satellites category page; paginated). A ROCKET constellation has no `const-` page, so its row points at the `lv-` one instead. On `cat-debris` this is the "where the fragments came from" breakdown (breakup clouds + rocket families), counted once per object.
  child_groups?: { name: string; n: number; primary_type: "group"; primary_id: string; role: GroupType }[]; // Child groups rendered as chips, sectioned by role: a category's zones/families/classes/constellations, an organization's satellite buses, and a constellation's buses (n = within-constellation count, not the bus's global total). `cat-surface-features` lists every non-empty `ft-` type, most features first; its own member_count is the feature total (features aren't objects, so it stays out of the `cat-solar-system` tally)
  variant_refs?: Record<string, EntityRef>;  // lv-<slug> only: GCAT variant name (from the global `variants` list) → its Wikipedia ref, for variants matched to a more-specific Wikidata entity than the family. The breakdown keeps the GCAT name as its label and uses this only for the per-variant link; absent for family-level / unmatched variants.
  reusable_vehicle_refs?: Record<string, EntityRef>;  // lv-<slug> only: reusable-vehicle name (from `reusable_vehicles`) → its Wikipedia ref. Shuttle orbiters resolve; Falcon cores have no article so are absent (shown as serial + count).
  notable_member_names?: Record<string, string>; // notable-member Object.id → localized label, only where it differs from the global name (feature members key on "<body id>:<feature_id>")
  body_names?: Record<string, string>;        // ft-<slug> only: `feature_bodies` row Object.id → localized body label
}
```

## Membership index (`membership/earth.json.gz`)

A single gzipped inverted index for **earth-sat** groups, merging every
earth-sat group type (constellation, organization, launch_site, country,
earth orbit class) into one `{slug: [object_id, ...]}` map. Built from a
single SATCAT scan and consumed by the group page to list members without a
per-member fetch. Its content hash feeds the `membership` versioned class.

```typescript
// membership/earth.json.gz
type EarthMembership = Record<string /* group slug */, string[] /* Object.ids */>;
```

Small-body and probe group membership is **not** shipped here — those pages
resolve members at runtime through the search (Meili `objects`) index, which
scales past what a static inverted index can hold.
