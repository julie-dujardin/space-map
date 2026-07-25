import { getLocale } from '$lib/paraglide/runtime.js';
import { fetchMetadata, hashBucket, type ProbeCoverage } from '$lib/fetch/metadata';
import { fetchGzipBundle } from '$lib/fetch/bundle-cache';
import { versionedUrl } from '$lib/fetch/data-base';
import type { PickedThumbnail } from '$lib/fetch/objects/images';
import type { PointingSpec } from '$lib/math/orientation';
import type { DisplacementMeta } from '$lib/scene/objects/surface/displacement';

// --- Global object data (non-localized) ---

export interface QuantityWithUnit {
	value: number;
	unit: string;
}

export interface CurrencyQuantity {
	value: number;
	currency: string;
}

/**
 * Per-image thumbnail manifest emitted by the exporter.
 *
 * Keys are size labels (s=512px, m=1024px, xl=4096px on the longest side),
 * values are file extensions (without a leading dot). A label is absent when
 * the source was smaller than the bucket — we never upscale. The smallest
 * available label always covers the source, since a source below 512px gets
 * emitted as `s` verbatim.
 */
export type ImageVariants = Partial<Record<'s' | 'm' | 'xl', string>>;

export interface ObjectImage {
	file: string;
	source_url: string;
	/** `photo` (P18 / Wikipedia pageimage) and `logo` (P154) are the object-side
	 *  kinds; `locator` (P242) is feature-only — IAU outline maps for surface
	 *  features. `radar` flags small-body radar/shape-model renders, kept visible
	 *  for now but filterable once 3D shape rendering replaces them. New kinds may
	 *  appear; consumers should treat unknown values as generic photos. */
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

/**
 * One denormalized notable object for the detail-page strip + list — a group
 * member (asteroid) or a moon. Picked at export time; carries everything the
 * UI needs so no per-object bundle fetch is required to render the tile/row.
 */
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
	/** IAU J2000 pole RA/Dec (deg) from PCK; the lineup's true axial tilt (major bodies + dwarfs). */
	pole?: { ra: number; dec: number };
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
	thumbnail?: PickedThumbnail;
}

/** Stable per-entry key: list keying and the localized-name/description maps
 *  both use it. Feature entries share their host body's `id`, so they key on
 *  the pair — mirrors `feature_member_key` in data/export/notable.py. */
export function memberEntryKey(e: NotableMemberEntry): string {
	if (e.feature_id != null) return `${e.id}:${e.feature_id}`;
	return e.group ?? e.id ?? '';
}

/** One rate-stable spin span's baseline, subtracted before encoding so the
 *  keyframes carry only the slow residual. A spinner that changes rate across
 *  mission phases (Juno: 1↔2 RPM) has one per phase; each file's
 *  `baseline_index` selects the span active over it. */
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

/**
 * Per-probe attitude manifest (refit from NAIF CK kernels), carried in the
 * probe's `__global__` bundle. Binary chunks live at `v1/attitude/{id}/{name}`
 * in `ATTI` v2 format (see `docs/export-format/probe-attitude.md`).
 */
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
	images?: ObjectImage[];
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
		temperature?: QuantityWithUnit;
		min_temperature?: QuantityWithUnit;
		max_temperature?: QuantityWithUnit;
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
	/** Archive the mesh was sourced from (free text, e.g. "PDS SBN (NEAR)"). */
	archive?: string;
	archive_url?: string;
	/** Observing spacecraft (mission shapes only), linking to its probe page. */
	mission?: FragmentOf;
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
	/** notable-moon Object.id → localized label, only where it differs from the global name. */
	notable_moon_names?: Record<string, string>;
	/** notable-moon Object.id → localized Wikidata short description, for the planet-page moon lineup hover tooltip. */
	notable_moon_descriptions?: Record<string, string>;
	/** featured-satellite id/slug → localized label, only where it differs. */
	notable_satellite_names?: Record<string, string>;
	/** fragment Object.id → localized label, only where it differs from the global name. */
	fragment_names?: Record<string, string>;
	/** mission-member Object.id → localized label, only where it differs from the global name. */
	mission_member_names?: Record<string, string>;
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
