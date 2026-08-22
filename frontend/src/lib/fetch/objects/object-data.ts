import { getLocale } from '$lib/paraglide/runtime.js';
import { fetchMetadata, hashBucket, type ProbeCoverage } from '$lib/fetch/metadata';
import { fetchGzipBundle } from '$lib/fetch/bundle-cache';
import { versionedUrl } from '$lib/fetch/data-base';
import type { PickedThumbnail } from '$lib/fetch/objects/images';
import type { PointingSpec } from '$lib/math/orientation';
import type { DisplacementMeta } from '$lib/scene/objects/surface/displacement';
import type { RingMeta } from '$lib/scene/objects/surface/rings';

// --- Global object data (non-localized) ---

export interface QuantityWithUnit {
	value: number;
	unit: string;
}

export interface CurrencyQuantity {
	value: number;
	currency: string;
}

/** One work a body's numbers were read off, as the atmosphere, interior and
 *  temperature blocks all ship it. `note` is a few words on what it gave — the
 *  credits page's full sentence stays there. */
export interface CitedWork {
	title: string;
	url: string;
	note?: string;
}

/** Where on the body a temperature applies; ordered headline-first by the exporter. */
export type TemperaturePart = 'surface' | 'cloud_top' | 'photosphere' | 'corona' | 'core';

/** What produces an extreme, where bare min/max would misread. */
export type TemperatureCondition = 'night' | 'day' | 'record';

/** One reading. `k` is always kelvin, so log positioning stays valid. */
export interface TemperatureReading {
	part: TemperaturePart;
	kind: 'min' | 'mean' | 'max';
	k: number;
	condition?: TemperatureCondition;
}

/** A body's temperatures, ordered headline-first by the exporter. `origin`
 *  applies to the whole block, not per reading: mixing an estimated
 *  radiative-equilibrium figure into measured readings would leave the bar
 *  readable as neither. */
export interface Temperatures {
	readings: TemperatureReading[];
	origin: 'measured' | 'estimated';
	sources?: CitedWork[];
}

/**
 * Per-image thumbnail manifest. Keys are size labels (s=512px, m=1024px,
 * xl=4096px on the longest side), values are extensions without the dot. A
 * label is absent when the source was smaller than the bucket — never
 * upscaled.
 */
export type ImageVariants = Partial<Record<'s' | 'm' | 'xl', string>>;

export interface ObjectImage {
	file: string;
	source_url: string;
	/** `photo`/`logo` are object-side kinds; `locator` is feature-only (IAU
	 *  outline maps); `radar` flags small-body radar/shape-model renders,
	 *  filterable once 3D shape rendering replaces them. Unknown values should
	 *  be treated as generic photos. */
	kind: 'photo' | 'logo' | 'locator' | 'radar';
	variants: ImageVariants;
	/** Attribution tier from the Commons license, for social-card use where a
	 *  required credit has no surface: `free` needs none, `credit` needs a text
	 *  attribution, `other` can't be honoured (copyleft/unknown). Absent on
	 *  pre-tiering exports — treat missing as non-`free`. */
	attr?: 'free' | 'credit' | 'other';
	/** Source pixel dimensions. Omitted for passthrough sources (SVG/WebM)
	 *  where the exporter never decoded a raster — clients should fall back
	 *  to measuring the loaded image. Both fields are present together. */
	width?: number;
	height?: number;
	/** What this picture is of, when the gallery pools several subjects: an
	 *  Object.id in a `moons` gallery, an IAU feature id in a `features` one.
	 *  Names the tile and links out of the viewer. */
	subject?: string | number;
	/** Short title from the Commons description, when it reads as a name rather
	 *  than a caption. Absent when the filename says as much — the tile falls
	 *  back to `imageLabel(file)`. The localized bundle overrides per language. */
	title?: string;
}

/**
 * One pooled image gallery beside the subject's own `images` — its surface
 * features, its moons, or (on a collection) one member. `key` is the URL
 * token: a fixed name for pooled kinds, the member's Object.id for a
 * collection's shelves.
 */
export interface ImageGalleryData {
	key: string;
	/** Set when the whole gallery is about one object — its shelves link to it.
	 *  Pooled galleries carry a per-image `subject` instead. */
	subject?: string;
	/** The subject's base-language name. Most shelf subjects are not notable
	 *  members, so the notable list cannot name them. */
	name?: string;
	images: ObjectImage[];
}

/** Texture attribution block — mirrors `texture_attribution()` in export/systems.py. */
export interface TextureAttribution {
	source: string;
	organisation: string;
	type: string;
	attribution?: string;
	description?: string;
	/** Only on `cylindrical_monthly`: number of monthly frames (always 12 today). */
	frames?: number;
}

/** One denormalized notable object for the detail-page strip + list — a
 *  group member or a moon. Picked at export time; carries everything the UI
 *  needs so no per-object bundle fetch is required to render the tile/row. */
export interface NotableMemberEntry {
	/** English Wikidata label (matching object bundles), or the DB fallback name. */
	name: string;
	/** Full Object.id for focus/routing (e.g. "spkid-2000004", "naif-502").
	 *  Absent when the entry is a group (see `group`). */
	id?: string;
	/** Group slug for entries that route to a group page instead of an object —
	 *  e.g. a featured constellation (Starlink) in Earth's Satellites strip. */
	group?: string;
	/** IAU feature id for entries that route to a surface feature (feature-type
	 *  group members); `id` then holds the host body. Localized-name overrides
	 *  key on `<id>:<feature_id>`. */
	feature_id?: number;
	/** Equivalent-sphere diameter (members) or mean PCK-radii diameter (moons). */
	diameter_km?: number;
	/** Body mass (kg) from PCK GM; major bodies only. Drives the planets mass chart. */
	mass_kg?: number;
	/** SPICE PCK triaxial radii (km); the render shape for major bodies + Ceres/Pluto. */
	radii?: { a: number; b: number; c: number };
	/** Scalar render radius (km) from the Wikidata radius — the render-size
	 *  fallback for bodies with no PCK radii or SBDB diameter (most TNO dwarfs). */
	radius_km?: number;
	/** IAU J2000 pole RA/Dec (deg); the lineup's true axial tilt. `source` names
	 *  the publisher when it isn't the PCK — small-body members tilt on DAMIT
	 *  lightcurve poles, which the footer credits separately. */
	pole?: { ra: number; dec: number; source?: 'lightcurve' | 'occultation' };
	/** SBDB geometric albedo (small bodies only). */
	albedo?: number;
	/** SBDB taxonomic type — SMASS else Tholen (small bodies only). */
	spec?: string;
	/** Physically-derived #rrggbb surface colour (TrueColorTools); the lineup
	 *  sphere tint for small bodies. Absent → caller falls back to a generic tint. */
	color?: string;
	/** Discovery proxy — SBDB first_obs, YYYY-MM-DD or YYYY (members only). */
	first_obs?: string;
	/** DEM sibling bundle — lets the lineup render the same relief as the main map. */
	displacement?: DisplacementMeta;
	/** Shape-model slug (`v1/models/<slug>/`); the lineup loads the mesh instead
	 *  of a sphere. Shape-model bundles only — never a spacecraft model. */
	model?: string;
	/** A `v1/textures/<id>/` surface map exists. Explicit `false` lets the
	 *  lineup skip the fetch; absent (pre-flag bundle) means probe as before. */
	texture?: boolean;
	/** Mass of the member's *rings*, not the member — the Ring Systems page
	 *  charts its eight against each other. Ringed bodies only. */
	ring_mass?: RingMass;
	/** The Structure & Activity collections: the figure each page ranks its
	 *  members by, drawn on its tile instead of a photograph. */
	ocean?: MemberOcean;
	atmosphere_pressure?: AtmospherePressure;
	/** The layer stack, trimmed to what a tile-sized cutaway draws — geometry,
	 *  phase, and one material per layer (the colour keys off the dominant one). */
	cutaway?: InteriorLayer[];
	limb?: MemberLimb;
	/** The three heat pages share one row: a body is usually on more than one
	 *  of them, and the three tables are three views of one question. */
	activity?: MemberActivity;
	radiation?: MemberRadiation;
	thumbnail?: PickedThumbnail;
}

/** The body's ocean, as one row of the cat-oceans chart. Volume is geometry off
 *  the same radii the cross-section draws, since no one work quotes all eight. */
export interface MemberOcean {
	volume_km3: number;
	thickness_km: number;
	/** Under something — true on all but Earth's, which is the page's whole point. */
	subsurface: boolean;
	mass_fraction?: number;
}

/** Headline values only — the widths, qualifiers and citations that ride on
 *  the object bundle's `activity` have no room in a collection row. */
export interface MemberActivity {
	volcanism?: {
		kind: Volcanism['kind'];
		status: ActivityStatus;
		endogenic_power_w?: number;
		youngest_activity_years?: number;
		known_centres?: number;
	};
	tectonics?: { style: string; status: ActivityStatus };
	tidal?: { role: string; raised_by: string; power_w?: number };
	magnetism?: {
		kind: MagneticField['kind'];
		surface_field_t?: number;
		dipole_moment_a_m2?: number;
		dipole_tilt_deg?: number;
		/** A non-detection's bound rather than a measurement; never plotted. */
		surface_field_t_upper_limit?: true;
		dipole_moment_a_m2_upper_limit?: true;
	};
}

/** The body's own radiation block, minus what a collection row has no room
 *  for: the works, which the page cites once for the whole set, and the belt's
 *  extents, which are radii of a planet a row has no axis for. Whether there
 *  is a belt survives, because that is what puts a member in the second
 *  chart. */
export type MemberRadiation = Omit<RadiationBlock, 'belt' | 'sources'> & { belt?: true };

/** Enough atmosphere for a tile-sized limb: the bands, and what the air is
 *  mostly made of. `structure` is absent on the bodies with no named
 *  boundary anywhere — half the members — which draw a graded shell instead. */
export interface MemberLimb {
	species?: { formula: string; share: number }[];
	structure?: AtmosphereStructure;
}

/** Stable per-entry key: list keying and the localized-name/description maps
 *  both use it. Feature entries share their host body's `id`, so they key on
 *  the pair — mirrors `feature_member_key` in data/export/notable.py. */
export function memberEntryKey(e: NotableMemberEntry): string {
	if (e.feature_id != null) return `${e.id}:${e.feature_id}`;
	return e.group ?? e.id ?? '';
}

/** One rate-stable spin span's baseline, subtracted before encoding so
 *  keyframes carry only the slow residual. A spinner that changes rate
 *  across mission phases (Juno: 1↔2 RPM) has one per phase, selected per
 *  file by `baseline_index`. */
export interface SpinBaseline {
	kind: 'spin';
	/** Unit spin axis in J2000. */
	axis: [number, number, number];
	rate_rad_s: number;
	/** Quaternion [w, x, y, z] at phase zero (`anchor_jd`). */
	anchor: [number, number, number, number];
	/** JD of phase zero — the spin angle is `rate · (jd − anchor_jd)`. */
	anchor_jd: number;
	start_jd: number;
	end_jd: number;
}

/** Per-probe attitude manifest (refit from NAIF CK kernels), carried in the
 *  probe's `__global__` bundle. Binary chunks live at
 *  `v1/attitude/{id}/{name}` in `ATTI` v2 format. */
export interface ProbeAttitude {
	/** Where the orientation stream came from. Only `spice_ck` today (refit from
	 *  NAIF CK kernels); absent on pre-`source` bundles — treat as `spice_ck`. */
	source?: 'spice_ck';
	/** CK reference frame the quaternions are expressed in. */
	frame: string;
	start_jd: number;
	end_jd: number;
	n_keyframes: number;
	/** Per-spin-phase baselines, or null for a non-spinner (keyframes are raw
	 *  J2000→body). Indexed by each file's `baseline_index`. */
	baselines: SpinBaseline[] | null;
	files: {
		name: string;
		start_jd: number;
		end_jd: number;
		n_keyframes: number;
		/** Index into `baselines` for the span this chunk recomposes against;
		 *  present only when `baselines` is non-null. */
		baseline_index?: number;
	}[];
}

export interface GlobalObjectData {
	id: string;
	type: string;
	name?: string;
	/** Host display name, present on moons only — lets the breadcrumb label the
	 *  parent even when its body isn't resident in the scene (small-body hosts
	 *  get culled by the streaming loader once focus moves on). */
	parent_name?: string;
	/** Moons only — #rrggbb physically-derived surface colour (TrueColorTools,
	 *  NAIF-keyed). Top-level because moons carry no `sbdb` block; small bodies
	 *  carry the equivalent under `sbdb.color`. The textureless sphere adopts it. */
	color?: string;
	color_method?: 'spectrum' | 'albedo';
	/** True when this body has IAU planetary nomenclature features exported.
	 *  Gates the per-body fetch of `v1/nomenclature/{positions,__global__}/{id}.*`. */
	has_nomenclature?: true;
	/** Top surface features of this body (sitelinks, then diameter), same shape
	 *  as a ft- page's members. Seeds the Features tab before search answers. */
	notable_features?: NotableMemberEntry[];
	/** Renderable features on this body — the Features tab badge. */
	feature_count?: number;
	map_texture_available?: boolean;
	/** Only present when `map_texture_available` — mirrors `texture` in systems/{bary}.json. */
	texture?: TextureAttribution;
	/** DEM sibling bundle — mirrors `displacement` in systems/{bary}.json. Carries
	 *  standalone bodies (Vesta/Ceres) that never load a system file. */
	displacement?: DisplacementMeta;
	/** Slug under `v1/models/{model_name}/` when this body has a 3D model bundle.
	 *  Multiple bodies can share one slug (e.g. all four Cluster II satellites
	 *  point at `cluster`); the frontend loads `high.glb` from that directory. */
	model_name?: string;
	/** Provenance of the shape model (natural bodies only): the technique tier,
	 *  the archive it came from, and — for mission shapes — a link to the
	 *  observing spacecraft. Drives the sources-section model paragraph. */
	model_source?: ModelSource;
	/** Best-available-asset render tier: high = faithful 3D model, map texture,
	 *  or procedural star surface; medium = lightcurve convex hull only; low =
	 *  size-only sphere/ellipsoid. Absent → no known physical extent (halo/point). */
	render_quality?: 'high' | 'medium' | 'low';
	atmosphere?: AtmosphereBlock;
	interior?: InteriorBlock;
	activity?: ActivityBlock;
	radiation?: RadiationBlock;
	/** Ring render bundles, inner → outer, mirroring `rings` in
	 *  systems/{bary}.json. Carries the four ringed small bodies, which orbit
	 *  the Sun directly and so appear in no system file. */
	rings?: RingMeta[];
	/** Named rings, gaps and ringlets of a ringed body, keyed by slug. The
	 *  catalogue behind the Rings tab — distinct from the `rings` render
	 *  bundles, and includes features we never draw. */
	ring_features?: Record<string, RingFeature>;
	/** The tables and papers the catalogue was read off — credited under the tab. */
	ring_sources?: Array<{ title: string; url: string; organisation: string }>;
	/** System-wide figures for the Rings tab's stat cards. Not to be confused
	 *  with the *localized* `ring_system`, which is the "Rings of X" article. */
	ring_stats?: RingStats;
	/** Pictures of the ring system — of the rings, not of the planet wearing
	 *  them. Selected from the "Rings of X" article; the first opens the tab.
	 *  Absent for the bodies whose rings no article illustrates. */
	ring_images?: ObjectImage[];
	temperatures?: Temperatures;
	images?: ObjectImage[];
	galleries?: ImageGalleryData[];
	sbdb_primary_designation?: string;
	provisional_designation?: string;
	nasa_science_url?: string;
	/** Natural moons only — discovery year from the JPL satellite-discovery
	 *  table (authoritative for the render gate). The detail page prefers a
	 *  Wikidata `discovery_date` only when its year agrees with this. */
	discovery_year?: number;
	/** Archive id (e.g. `"naif"`, `"esa"`, `"naif-pds3"`); resolves to a
	 *  label via `$lib/credits/archive-labels`. */
	ephemeris_source?: string;
	cross_refs?: {
		wikidata_qid?: string;
		naif_id?: number;
		spkid?: number;
		mpc_designation?: string;
		norad_cat_id?: number;
		cospar_id?: string;
	};
	orbit?: {
		epoch_jd: number;
		e: number;
		i: number;
		om: number;
		w: number;
		scale: string;
		parent_id: string;
		source: string;
		// Keplerian elements (standard orbits)
		a?: number;
		ma?: number;
		n?: number;
		// Parabolic elements (e=1 comets)
		q?: number;
		tp?: number;
		// SGP4 init fields (CelesTrak-sourced earth sats only)
		bstar?: number;
		mean_motion_dot?: number;
		mean_motion_ddot?: number;
		element_set_no?: number;
		rev_at_epoch?: number;
	};
	orientation?: {
		pole_ra_0: number;
		pole_ra_1: number;
		pole_dec_0: number;
		pole_dec_1: number;
		w0: number;
		w1: number;
		w2: number;
		/** Who published these elements. The export merges the IAU/NAIF PCK with
		 *  poles converted from DAMIT lightcurve inversions and with the four
		 *  ringed small bodies' occultation fits; absent on pre-`source`
		 *  bundles — treat as `pck`, which is what they all used to claim. */
		source?: 'pck' | 'lightcurve' | 'occultation';
		/** The paper behind an `occultation` pole — those come from the
		 *  literature, not a kernel. */
		reference?: { title: string; url: string };
	};
	nut_prec?: {
		ra: number[];
		dec: number[];
		pm: number[];
	};
	/** Hand-edited per-spacecraft pointing (spacecraft-orientation.yaml); the
	 *  focused model aims `primary.axis` at `primary.target`, rolling toward the
	 *  optional `secondary`. Absent → south-toward-parent default. */
	pointing?: PointingSpec;
	/** Refit-from-CK attitude stream (probes with NAIF CK kernels). Loaded
	 *  lazily on focus; supersedes `pointing` over its coverage window. */
	attitude?: ProbeAttitude;
	/** SPICE PCK triaxial radii (km) along body-fixed X, Y, Z (Z = spin axis).
	 *  When present, this is the shape the 3D scene renders — supersedes the
	 *  Wikidata radius and SBDB diameter as the authoritative size. */
	radii?: { a: number; b: number; c: number };
	/** Which table the radii were read off: the PCK, or the occultation fits of
	 *  the four ringed small bodies no kernel covers. Decides who the sidebar
	 *  credits for the size. */
	radii_source?: 'pck' | 'occultation';
	sbdb?: {
		neo?: boolean;
		pha?: boolean;
		/** OrbitClass enum *name* (e.g. "MBA", "APO") — also the export zone id. */
		class?: string;
		sats?: number;
		diameter?: number;
		extent?: string;
		albedo?: number;
		rot_per?: number;
		GM?: number;
		mass?: QuantityWithUnit;
		H?: number;
		G?: number;
		spec_B?: string;
		spec_T?: string;
		/** Physically-derived #rrggbb surface colour (TrueColorTools); the rendered
		 *  sphere tint for a textureless small body. */
		color?: string;
		/** How `color` was derived (present iff `color` is); credits the method. */
		color_method?: 'spectrum' | 'photometry' | 'taxonomy' | 'albedo';
		BV?: number;
		UB?: number;
		IR?: number;
		moid?: number;
		moid_jup?: number;
		t_jup?: number;
		per_y?: number;
		ad?: number;
		prefix?: string;
		M1?: number;
		M2?: number;
		K1?: number;
		K2?: number;
		PC?: number;
		first_obs?: string;
		last_obs?: string;
		data_arc?: number;
		n_obs_used?: number;
		condition_code?: number;
	};
	wikidata?: {
		discovery_date?: string[];
		launch_date?: string;
		mass?: QuantityWithUnit;
		radius?: QuantityWithUnit;
		density?: QuantityWithUnit;
		surface_gravity?: QuantityWithUnit;
		absolute_magnitude?: number;
		apparent_magnitude?: number;
		population?: number;
		website?: string[];
		blog?: string[];
		capital_cost?: CurrencyQuantity;
		length?: QuantityWithUnit;
		width?: QuantityWithUnit;
	};
	celestrak?: {
		object_type?: string;
		ops_status?: string;
		data_status?: string;
		launch_date?: string;
		decay_date?: string;
		period?: number; // minutes
		apogee?: number; // km
		perigee?: number; // km
		rcs?: number; // m²
		orbit_center?: string;
		orbit_center_docked_to?: number;
		launch_site_code?: string;
		owner?: string;
		constellation_slug?: string;
		categories?: string[];
		country_codes?: string[];
	};
	/** Probe objects only. Outermost SPK coverage envelope; the focused-probe
	 *  coverage-end pause arms a SimClock boundary stop from these bounds. */
	coverage?: ProbeCoverage;
	/** Top moons picked at export time (image/sitelinks/diameter rank); on
	 *  planets/dwarf planets and asteroids with satellites. */
	notable_moons?: NotableMemberEntry[];
	/** Total moon count of this body — drives the "+N more" tile. Present iff
	 *  notable_moons is. */
	moon_count?: number;
	/** Curated featured satellites (Earth only): the Moons section becomes a
	 *  Satellites section listing these after the Moon. Object entries route to
	 *  the object; a constellation entry carries `group` instead of `id`. */
	notable_satellites?: NotableMemberEntry[];
	/** Total tracked artificial satellites — folded into the "+N more" count. */
	satellite_count?: number;
	/** Group slug the "+N more" tile links to (the Satellites browse page). */
	satellites_group?: string;
	/** Pieces of a split comet, on the intact parent (e.g. 73P). Same shape +
	 *  strip UI as notable_moons; localized labels in `fragment_names`. */
	fragments?: NotableMemberEntry[];
	/** Total fragment count of this comet — drives the "+N more" tile. Present
	 *  iff `fragments` is. */
	fragment_count?: number;
	/** On a fragment body: the comet it broke off, for the breadcrumb + "Fragment
	 *  of" card. Routes to the parent object, or the family group when the intact
	 *  comet isn't catalogued (parentless families like Shoemaker-Levy 9). */
	fragment_of?: FragmentOf;
	/** On a mission's primary probe: link up to the /g/mission-<slug> page. Same
	 *  card + shape as fragment_of (always a group link). */
	mission?: FragmentOf;
	/** Sibling craft of this mission, on the primary probe. Strip UI like
	 *  notable_moons; localized labels in `mission_member_names`. */
	mission_members?: NotableMemberEntry[];
	/** Sibling craft count, present iff mission_members is. */
	mission_member_count?: number;
	/** On a member probe: the mission it belongs to, for the breadcrumb + card. */
	part_of_mission?: FragmentOf;
}

export interface FragmentOf {
	name: string;
	primary_type: 'object' | 'group';
	/** Parent Object.id ("object") or family group slug ("group"). */
	primary_id: string;
	thumbnail?: PickedThumbnail;
}

/** Shape-model provenance denormalized onto a natural body's global bundle. */
export interface ModelSource {
	/** Technique tier: spacecraft mission, Earth-based radar, or lightcurve
	 *  inversion. */
	provenance: 'missions' | 'radar' | 'lightcurve';
	/** Finer technique, where the tier alone would misdescribe the shape: DAMIT
	 *  ships non-convex solutions that needed resolved data (adaptive optics,
	 *  radar, occultation chords) beside its convex lightcurve hulls. */
	technique?: 'lightcurve_convex' | 'lightcurve_resolved';
	/** Who derived the shape, when that isn't the archive under another name —
	 *  a DAMIT bundle credits the inversion's authors ("Vernazza et al. (2021)"),
	 *  since the archive only distributes it. */
	author?: string;
	/** Archive the mesh was sourced from (free text, e.g. "PDS SBN (NEAR)"). */
	archive?: string;
	archive_url?: string;
	/** Observing spacecraft (mission shapes only), linking to its probe page. */
	mission?: FragmentOf;
}

/** Cited atmospheric facts for the ~two dozen bodies with a measured gaseous
 *  envelope — distinct from the render parameters in `v1/atmospheres.json`,
 *  which are stated at whichever level the shell is drawn from rather than
 *  the level a reader expects. One published pressure: the level is not
 *  decoration, since the four giants all read 0.1 bar at the cloud top, not
 *  the surface. */
export interface AtmospherePressure {
	pa: number;
	/** Reference level the pressure is quoted at ("surface", "cloud_top", …). */
	level: string;
	qualifier?: 'upper_limit' | 'approximate' | 'variable';
}

export interface AtmosphereBlock {
	/** Enum from the pipeline, e.g. "exosphere", "gas_giant_envelope". */
	type: string;
	/** What sustains or varies this atmosphere ("volcanic", "seasonal_orbit",
	 *  …) — the frontend holds the sentence, the pipeline only the key. */
	note?: string;
	pressure?: AtmospherePressure;
	composition?: {
		/** What the shares are shares OF — thin envelopes only have per-species
		 *  column or number densities, never a mixing ratio. */
		unit: 'volume_fraction' | 'mass_fraction' | 'column_density' | 'number_density';
		/** Normalized over the listed species, descending. `limit` marks a
		 *  non-detection upper limit rather than a measured abundance. */
		species: { formula: string; share: number; limit?: boolean }[];
	};
	/** Named vertical layers, for the Structure tab's cross-section. Only the
	 *  dozen bodies whose layers anyone has named. */
	structure?: AtmosphereStructure;
	/** Works the numbers come from, deduped per body. */
	sources?: CitedWork[];
}

/** The vertical axis the block's single pressure sits on. Every field is
 *  optional: a boundary is a turning point in temperature, not a surface, so
 *  a source pins sometimes a height, sometimes a pressure. */
export interface AtmosphereStructure {
	/** What altitude 0 means. The giants hang off the 1 bar level and run
	 *  negative below it. */
	datum: 'surface' | 'one_bar' | 'photosphere';
	/** Lowest first. A layer's base is the one below's top; the lowest one's
	 *  base is `datum`. */
	layers: AtmosphereLayer[];
	/** The temperature at the datum, so the lowest layer has a base to be read
	 *  between. The body's surface reading, or the 1 bar temperature on a
	 *  giant. */
	datum_temperature_k?: number;
	/** And the pressure there — the block's own `pressure` where that is quoted
	 *  at the datum, 1 bar on the giants. */
	datum_pressure_pa?: number;
	/** Above it species sort by mass and the body's single composition stops
	 *  describing anything. */
	homopause_km?: number;
	homopause_pressure_pa?: number;
	/** Exosphere-only bodies: how fast it thins, in place of the boundaries it
	 *  has none of. */
	scale_height_km?: number;
}

export interface AtmosphereLayer {
	/** "troposphere", "thermosphere", "corona", … */
	role: string;
	top_km?: number;
	/** Where the boundary actually sits — Earth's tropopause runs 9 km over the
	 *  poles to 17 km over the equator. */
	top_km_range?: [number, number];
	top_pressure_pa?: number;
	top_temperature_k?: number;
	/** Spread over latitude and solar cycle, not an error bar on one number. */
	top_temperature_range_k?: [number, number];
	/** "well_mixed", "heterosphere", "exobase", … — the frontend holds the
	 *  sentence, the pipeline only the key. */
	note?: string;
	/** Raw mixing ratios in the block's `composition.unit`, NOT normalized
	 *  shares: a layer lists a species only where its abundance differs from the
	 *  body's. */
	species?: { formula: string; value: number }[];
}

/** What a body is made of, by mass. Two routes into one shape: a layer model
 *  for the bodies a mission constrained, or the bulk chemistry of a meteorite
 *  analogue for an asteroid that only has a spectrum (`estimated`). */
export interface InteriorBlock {
	/** How far the body separated — "differentiated", "rubble_pile", "fluid",
	 *  … Absent on the estimate route, where a spectrum says nothing about it. */
	structure?: string;
	/** Read off a taxonomic class, not measured on this body. */
	estimated?: true;
	/** Estimate route: meteorite group key, e.g. "ordinary_chondrite". */
	analogue?: string;
	/** Estimate route: the class as reported, and which taxonomy it belongs
	 *  to — a letter means different things under Tholen and Bus-DeMeo. */
	taxonomy_class?: string;
	taxonomy_scheme?: string;
	/** Estimate route: who to credit for the class letter, as ids rather than
	 *  citations — 171,000 asteroids carry this. Resolved by
	 *  `$lib/credits/taxonomy-sources`. */
	taxonomy_sources?: string[];
	/** "subsurface_ocean", "hydrated_rock", … — only the ocean note gets a
	 *  sentence; the rest is provenance metadata. */
	note?: string;
	/** At r=0, closing the innermost layer's span. Only where a body has a
	 *  published centre rather than a boundary — the Sun, and the giants whose
	 *  dilute cores have no radius to hang one on. */
	centre_temperature_k?: number;
	centre_temperature_range_k?: [number, number];
	/** Whole-body roll-up, descending. Absent where the source constrains
	 *  geometry but not masses (the Sun). */
	composition?: { material: string; share: number }[];
	/** Outermost first, layer-model route only — the estimate route has no
	 *  layers, and 150,000 asteroids take it. */
	layers?: InteriorLayer[];
	/** Works the numbers come from, deduped per body. */
	sources?: CitedWork[];
}

/** What the body is still doing: heat reaching the surface, the tide that
 *  supplies it, and the field a convecting core makes. 23 bodies. Lopsided on
 *  purpose — categorical fields are complete, numbers are not, and five
 *  bodies carry only a status. Lead with the status; measurements optional. */
export interface ActivityBlock {
	volcanism?: Volcanism;
	/** Rides with `volcanism`, never alone. */
	tectonics?: Tectonics;
	tidal?: TidalHeating;
	/** The Sun and the four giants have this and no other entry. */
	magnetism?: MagneticField;
	sources?: CitedWork[];
}

/** A dose rate and what was between it and the sky. The shielding is part of
 *  the number: against cosmic rays a hull barely matters, against trapped
 *  particles it is the whole difference. */
export interface DoseRate {
	sv_per_day: Measurement;
	shielding_g_cm2?: number;
}

/** How much ionizing radiation a place delivers, as a rate — a body is
 *  somewhere you stay, not something you cross. */
export interface RadiationBlock {
	/** What supplies most of the dose, and so whether shielding helps.
	 *  `trapped` is the one that kills in hours rather than decades. */
	kind?: 'cosmic' | 'trapped' | 'shielded';
	note?: string;
	/** Published: measured by an instrument that sat there, or computed by
	 *  someone else for a body-sized water target. */
	surface_dose?: DoseRate;
	orbit_dose?: DoseRate;
	/** Our own arithmetic, only where nothing is published and only outside a
	 *  magnetosphere. A solar-cycle mean; `range` is the cycle's own swing. */
	modelled_surface_dose?: {
		sv_per_day: number;
		range: [number, number];
		modelled: true;
		/** Past 9.5 au, where the radial gradient outruns the data behind it. */
		extrapolated?: true;
	};
	belt?: {
		inner_radii?: Measurement;
		peak_radii?: Measurement;
		outer_radii?: Measurement;
		/** The one rate-rule exception: a dose somebody actually flew. */
		crossing_dose_sv?: Measurement;
		note?: string;
	};
	sources?: CitedWork[];
}

/** One published number with what its source said about how sure it is. The
 *  qualifier is usually the finding here, so a bare `value` would misread. */
export interface Measurement {
	value: number;
	/** The published width, not an error bar: Venus's surface age is 250 Ma to
	 *  1 Ga across crater models. */
	range?: [number, number];
	/** A non-detection's bound. Titan's and Venus's magnetic moments have never
	 *  been anything else. */
	upper_limit?: true;
	/** A scaling or extrapolation rather than an observation of this body —
	 *  Venus's eruption count is Earth's record times a mass ratio, and without
	 *  this would draw exactly like Earth's own catalogue. */
	modelled?: true;
	/** The survey cut-off or database version a count belongs to. English free
	 *  text, so it shows as-is: "343 hot spots" is a property of the last
	 *  global map rather than of Io. */
	as_of?: string;
}

export type ActivityStatus = 'active' | 'probable' | 'suspected' | 'dormant' | 'extinct' | 'none';

export interface Volcanism {
	kind: 'silicate' | 'cryo' | 'both' | 'none';
	/** Five rungs rather than a boolean, because Venus, Mars and Earth are
	 *  three different claims and a boolean would make them one. */
	status: ActivityStatus;
	/** Everything mapped that could erupt; the survey's definition of a centre,
	 *  not ours. */
	known_centres?: Measurement;
	eruptions_per_year?: Measurement;
	erupted_volume_km3_per_year?: Measurement;
	/** Jets or plumes, on the bodies where a plume is the only countable thing. */
	plumes?: Measurement;
	plume_mass_kg_per_s?: Measurement;
	/** Heat leaving the body from inside, and the same over its area — Io
	 *  against Earth is 2× in power and 30× in flux. */
	endogenic_power_w?: Measurement;
	heat_flux_w_per_m2?: Measurement;
	/** Years before present. What separates "extinct" from "dormant", and the
	 *  number the argument is usually about. */
	youngest_activity_years?: Measurement;
	surface_age_years?: Measurement;
	/** Provenance metadata; nothing renders it yet. */
	note?: string;
}

export interface Tectonics {
	/** Not a ladder — an ice shell cracking over an ocean and a planet
	 *  shrinking onto its core are different machines, and only one of them
	 *  recycles a surface. */
	style:
		| 'plate_tectonics'
		| 'stagnant_lid'
		| 'contractional_lid'
		| 'mobile_lid'
		| 'ice_shell_tectonics'
		| 'impact_dominated'
		| 'none';
	status: ActivityStatus;
	/** How much the planet has shrunk as its core cooled. */
	radial_contraction_km?: Measurement;
	note?: string;
}

export interface TidalHeating {
	/** Object id of what raises the tide, so a panel can name and link it. */
	raised_by: string;
	/** How much of the heat budget the tide is. The honest resolution for most
	 *  of the list: the rate itself is rarely measured. */
	role: 'dominant' | 'significant' | 'minor' | 'negligible' | 'past';
	power_w?: Measurement;
	flux_w_per_m2?: Measurement;
	/** Tidal Love number — how much the body deforms; large means soft. */
	k2?: Measurement;
	/** Tidal quality factor; small dissipates hard. Io's ~11 is the lowest
	 *  measured anywhere. */
	q?: Measurement;
	/** Object ids of the partners keeping the eccentricity up, without which
	 *  the tide would switch itself off. */
	resonance_with?: string[];
	/** `power_w` and `volcanism.endogenic_power_w` are one measurement rather
	 *  than two — draw one heat row saying the tide accounts for all of it. */
	explains_heat_output?: true;
	note?: string;
}

export interface MagneticField {
	/** "induced" is eddy currents in a conductive shell answering the field it
	 *  sits in — evidence about an ocean, not about a core. */
	kind: 'dynamo' | 'induced' | 'remanent' | 'none';
	/** Of the equivalent centred dipole. The one figure that compares across
	 *  bodies, which is why it is here even where a source publishes only a
	 *  surface field and this is arithmetic on it. */
	dipole_moment_a_m2?: Measurement;
	/** At the surface on the magnetic equator. `range` is the spread over the
	 *  real surface where the field is far from a dipole. */
	surface_field_t?: Measurement;
	/** Between the dipole and rotation axes — what separates Saturn from
	 *  Uranus, and the hardest thing for dynamo models to make. */
	dipole_tilt_deg?: Measurement;
	dipole_offset_radii?: Measurement;
	/** Years before present, for the bodies carrying only remanence now. */
	dynamo_ended_years?: Measurement;
	note?: string;
}

/** One shell of the cross-section. */
export interface InteriorLayer {
	/** "crust", "ice_shell", "ocean", "mantle", "core", "convective_zone", … */
	role: string;
	/** The source's own R, which is not the body's exported mean radius — the
	 *  two disagree by a few km on Europa depending on the paper. Normalize the
	 *  disc to the outermost layer or the stack gaps at the surface. */
	outer_radius_km: number;
	/** Where the layer stops, on the layers whose floor is not the next one's
	 *  top: under Earth's ocean is the sea floor, not the continental crust
	 *  that follows it. Absent on a shell, which ends where the next begins. */
	base_radius_km?: number;
	/** Share of the globe the layer covers, on the layers that are patches
	 *  rather than shells — Earth's two crusts meet at a coastline, not at a
	 *  depth, so they are drawn side by side along the disc's arc. */
	area_fraction?: number;
	/** Of the whole body. Absent where a source gives geometry but no mass. */
	mass_fraction?: number;
	mass_fraction_range?: [number, number];
	/** "solid", "liquid", "partial_melt", "fluid", "plasma". Absent where
	 *  nobody knows — Venus's core, which the tides allow to be solid. */
	state?: string;
	/** "ice_i", "ice_v", "ice_vi", … — which crystal structure a solid took,
	 *  where the pressure picks one. It supersedes `state`: "solid water" is
	 *  true of both an ice shell and the ice mantle far below it. */
	phase?: string;
	/** "basalt", "andesite", "anorthosite", "peridotite" — the petrologist's
	 *  name for the whole layer, superseding `state` for the same reason
	 *  `phase` does. Absent far more often than not, deliberately, where the
	 *  literature hasn't settled on one. */
	rock?: string;
	/** "core_size_disputed", "shell_thickness_modelled", … — provenance
	 *  metadata, except "continental_crust_only" which renames the layer. */
	note?: string;
	/** The mass is arithmetic on the source's radii and densities rather than a
	 *  number it quotes. */
	derived?: true;
	/** No boundary to draw: `outer_radius_km` is where the layer fades out
	 *  rather than where it ends. Jupiter's core is the case. */
	diffuse?: true;
	/** At `outer_radius_km`. Geotherms publish at boundaries — the Moho, 660 km,
	 *  the core-mantle boundary — so a layer's span reads against the next
	 *  layer down's. Never on the outermost layer: `temperatures` covers that
	 *  boundary. */
	outer_temperature_k?: number;
	/** Usually the whole claim, `outer_temperature_k` being absent: most of
	 *  these are a spread across models rather than an error bar on one. */
	outer_temperature_range_k?: [number, number];
	/** Of this layer, same materials and same sliver cut as the roll-up. */
	composition: { material: string; share: number; share_range?: [number, number] }[];
	/** Finer chemistry where the literature gives one. */
	detail?: {
		unit:
			| 'oxide_weight'
			| 'element_weight'
			| 'mineral_volume'
			| 'compound_weight'
			| 'compound_volume';
		entries: { species: string; fraction: number }[];
	};
}

// --- Localized object data ---

export interface EntityRef {
	name: string;
	short_name?: string;
	wikipedia?: string;
	/** ID-scheme for the focus target (e.g. "naif", "spkid"). */
	primary_type?: string;
	primary_id?: string;
	/** Refines the target within ``primary`` (currently always "feature"). */
	secondary_type?: string;
	secondary_id?: string;
}

export interface LocalizedObjectData {
	name?: string;
	description?: string;
	aliases?: string[];
	instance_of?: EntityRef[];
	discoverers?: EntityRef[];
	named_after?: EntityRef[];
	discovery_site?: EntityRef[];
	minor_planet_group?: EntityRef[];
	spectral_type?: EntityRef[];
	asteroid_family?: EntityRef;
	operators?: EntityRef[];
	constellation?: EntityRef;
	/** Satellite bus / platform (CelesTrak-derived); links to /g/bus-<slug>. */
	bus?: EntityRef;
	manufacturer?: EntityRef[];
	launch_vehicle?: EntityRef;
	launch_site?: EntityRef[];
	developer?: EntityRef[];
	funder?: EntityRef[];
	country_of_origin?: EntityRef[];
	launch_contractor?: EntityRef[];
	part_of?: EntityRef[];
	wikipedia?: {
		extract?: string;
		description?: string;
		url?: string;
	};
	/** Ring feature slug → localized label + Wikipedia lead, for the features
	 *  this locale has an article or label for (see `ring_features`). */
	ring_features?: Record<string, LocalizedRingFeature>;
	/** The "Rings of X" article in this locale — the ring panel's opening blurb. */
	ring_system?: LocalizedRingFeature;
	/** "Internal structure of X" in this locale, for the Structure tab. Thin
	 *  coverage: 10 bodies, 7 of them Italian-only. */
	interior_page?: TopicPage;
	/** "Atmosphere of X" in this locale, for the Structure tab. */
	atmosphere_page?: TopicPage;
	/** notable-moon Object.id → localized label, only where it differs from the global name. */
	/** Commons filename → localized picture title, only where the language has
	 *  one of its own. Covers every gallery on the page — they key by filename. */
	image_titles?: Record<string, string>;
	notable_moon_names?: Record<string, string>;
	/** notable-moon Object.id → localized Wikidata short description, for the planet-page moon lineup hover tooltip. */
	notable_moon_descriptions?: Record<string, string>;
	/** notable-feature `<body_id>:<feature_id>` → localized label, only where it differs. */
	notable_feature_names?: Record<string, string>;
	/** featured-satellite id/slug → localized label, only where it differs. */
	notable_satellite_names?: Record<string, string>;
	/** fragment Object.id → localized label, only where it differs from the global name. */
	fragment_names?: Record<string, string>;
	/** mission-member Object.id → localized label, only where it differs from the global name. */
	mission_member_names?: Record<string, string>;
}

/** What a ring feature is, in nomenclature terms. `division` is the broad
 *  separation between named rings (Cassini, Roche), `gap` a narrow clearing
 *  inside one; `region` marks the B ring's unnamed structural subdivisions and
 *  `dust` the diffuse bands that carry no formal name. */
export type RingFeatureKind = 'ring' | 'division' | 'gap' | 'ringlet' | 'region' | 'arc' | 'dust';

/** Ring-system mass in kilograms, with the hedges its source published.
 *  Measured for Saturn alone; everything else is an order of magnitude. */
export interface RingMass {
	low_kg: number;
	/** A published range. Never set together with `uncertainty_kg`. */
	high_kg?: number;
	approximate?: true;
	/** `low_kg` bounds the mass from above. */
	upper_limit?: true;
	uncertainty_kg?: number;
}

/** Vertical extent of the main rings, in metres — the dimension the Rings
 *  tab's radial chart has no axis for. Two bodies have one. */
export interface RingThickness {
	low_m: number;
	high_m?: number;
	/** Slug of the feature the figure describes, where it is one ring. */
	feature?: string;
}

export interface RingStats {
	/** The observation year, never the paper's — see docs/export-format. */
	discovery_year?: number;
	mass?: RingMass;
	thickness?: RingThickness;
}

/** Normal optical depth as its source states it — rarely a single number. */
export interface RingOpticalDepth {
	low: number;
	/** Absent for a single stated value. */
	high?: number;
	/** Source wrote "~". */
	approximate?: true;
	/** Source wrote "<": `low` bounds the value from above. */
	upper_limit?: true;
}

export interface RingFeature {
	name: string;
	kind: RingFeatureKind;
	/** Key of the containing feature. Keys run inner → outer, which does not
	 *  put a parent before its children, so group rather than walk. */
	parent?: string;
	/** Absent where the source publishes only a radius (the co-orbital rings). */
	inner_radius_km?: number;
	outer_radius_km?: number;
	mid_radius_km: number;
	width_km?: number;
	/** The radius is the source moon's orbit, not a measured edge. */
	radius_approximate?: true;
	optical_depth?: RingOpticalDepth;
	thickness_km?: number;
	eccentricity?: number;
	inclination_deg?: number;
	/** Provisional designation still in common use ("1986 U2R"). */
	designation?: string;
	/** Macroscopic particles (back-scatter bright) vs µm dust (forward-scatter bright). */
	particles?: 'dense' | 'dusty';
	/** Shepherds, embedded and source moons; `id` absent when the moon isn't exported. */
	moons?: Array<{ name: string; id?: string }>;
	wikidata_qid?: string;
	/** The PDS table's own description. English wherever it appears — there is
	 *  no translated source, so the localized extract replaces it when a locale
	 *  has an article. */
	note?: string;
}

export interface LocalizedRingFeature {
	name?: string;
	extract?: string;
	url?: string;
}

/** A Wikipedia article about a topic rather than about the body — "Atmosphere
 *  of Mars", not "Mars". Only present for locales that have the article; the
 *  extract is always set, since a link with nothing to introduce it renders
 *  nothing. */
export interface TopicPage {
	extract: string;
	url?: string;
}

// --- Fetching ---

export interface ObjectDetailData {
	global: GlobalObjectData | null;
	localized: LocalizedObjectData | null;
}

/**
 * Fetch the global + (optionally) localized detail bundles for `fileId`.
 * Bundles are hash-bucketed via `metadata.json → object_bundles` and cached.
 * Pass `body.data.hasLocalized` for `fetchLocalized` to skip the localized
 * fetch on bodies with no Wikidata (avoids a guaranteed 404).
 */
export async function fetchObjectDetail(
	fileId: string,
	fetchLocalized = true,
	lang = getLocale()
): Promise<ObjectDetailData> {
	const meta = await fetchMetadata();

	const nLocalized = fetchLocalized ? meta.object_bundles[lang] : 0;

	const [globalBucket, localizedBucket] = await Promise.all([
		hashBucket(fileId, meta.object_bundles.global),
		nLocalized ? hashBucket(fileId, nLocalized) : Promise.resolve(-1)
	]);

	const globalPromise = fetchGzipBundle<GlobalObjectData>(
		versionedUrl(`/v1/objects/__global__/${globalBucket}.json.gz`, 'objects')
	);
	const localizedPromise: Promise<LocalizedObjectData | undefined> =
		fetchLocalized && localizedBucket >= 0
			? fetchGzipBundle<LocalizedObjectData>(
					versionedUrl(`/v1/objects/${lang}/${localizedBucket}.json.gz`, 'objects')
				).then((b) => b[fileId])
			: Promise.resolve(undefined);

	const [globalBundle, localized] = await Promise.all([globalPromise, localizedPromise]);
	return {
		global: globalBundle[fileId] ?? null,
		localized: localized ?? null
	};
}
