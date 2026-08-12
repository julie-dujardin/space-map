/**
 * Per-group detail bundle loader: global + (optionally) localized, same
 * hash-bucketing scheme as object bundles (sha256-first-4-bytes % N).
 */

import { getLocale } from '$lib/paraglide/runtime.js';
import { fetchMetadata, hashBucket } from '$lib/fetch/metadata';
import { fetchGzipBundle } from '$lib/fetch/bundle-cache';
import { DATA_BASE } from '$lib/fetch/data-base';
import type {
	EntityRef,
	ImageGalleryData,
	NotableMemberEntry,
	ObjectImage
} from '$lib/fetch/objects/object-data';
import type { GroupCategory, GroupType, OrganizationRole, SatelliteCategory } from './registry';

export type { NotableMemberEntry };

export interface LaunchSiteEntry extends EntityRef {
	n: number;
}

export interface ConstellationEntry extends EntityRef {
	n: number;
}

/** One GCAT launch-vehicle variant (e.g. "Atlas V 551") with its launch tally
 *  and physical specs from lv.tsv. Specs are present only when GCAT records them. */
export interface LaunchVehicleVariant {
	name: string;
	/** Distinct launches flown by this variant. */
	n: number;
	launch_mass_t?: number;
	leo_capacity_kg?: number;
	gto_capacity_kg?: number;
	thrust_kn?: number;
	length_m?: number;
	diameter_m?: number;
}

/** One GCAT place inside a SATCAT launch range, with its own point and pads.
 *  A range is not one place — the Eastern Range spans Canaveral, Kennedy and
 *  the commercial pads — so there is no range-level coordinate to fall back on. */
export interface GcatSite {
	/** GCAT unified site code, e.g. "CC", "KSC". */
	code: string;
	name?: string;
	/** Wikidata entity, where one was matched. */
	qid?: string;
	lat?: number;
	lon?: number;
	/** GCAT's stated uncertainty on the site point; coarse even at 0.05°. */
	error_deg?: number;
	/** Distinct launches from this place; sums to the range's launch_count. */
	launches: number;
	pads?: GcatPad[];
}

export interface GcatPad {
	/** GCAT launch-point code, e.g. "LC39A" — the chart's row label. */
	code: string;
	name: string;
	lat: number;
	lon: number;
	/** Distinct launches from this pad. Zero is common and real. */
	launches: number;
	qid?: string;
}

export interface ReusableVehicle {
	/** Vehicle id, also the display label (Shuttle orbiter / Falcon core serial). */
	name: string;
	/** Flights flown by this individual vehicle. */
	n: number;
	first_flight?: string;
	last_flight?: string;
}

/** One landform family: its constants key, its feature total, and the `ft-`
 *  slugs it holds (most-populated type first). */
export interface FeatureFamily {
	key: string;
	n: number;
	types: string[];
}

export interface GlobalGroupData {
	slug: string;
	type: GroupType;
	applies_to: GroupCategory;
	member_count: number;
	/** Earth-orbiter groups only: the `cat-` slug the breadcrumb climbs to.
	 *  `applies_to` can't say — satellites and debris share it. */
	parent_category?: string;
	/** Organization-only: role tags (operator and/or manufacturer) for badges. */
	roles?: OrganizationRole[];
	/** IAU-named members; present (when > 0) on asteroid orbit_class groups and the Asteroids category. */
	named_count?: number;
	wikidata_qid?: string;
	/** Fallback external URL when a group has no Wikidata QID. */
	url?: string;
	/** Wikidata P856 — official site. */
	website?: string;
	/** Constellation-only: CelesTrak-style top-level use cases (communications, navigation, …). */
	categories?: SatelliteCategory[];
	/** Launches per year across SATCAT members, sorted by year ascending. */
	launch_histogram?: Record<string, number>;
	/** Earliest SATCAT ``launch_date`` across members (ISO date string, precision may vary). */
	first_launch_date?: string;
	/** Members with ``ops_status`` operational/partial/extended and no decay. */
	active_count?: number;
	/** Members with a SATCAT decay_date. */
	decayed_count?: number;
	/** Launch-vehicle only: distinct GCAT launches (deduped by launch_tag). For lv-
	 *  groups ``launch_histogram`` / ``first_launch_date`` come from the launchlog
	 *  (the full history), not just the spent stages still catalogued in orbit. */
	launch_count?: number;
	/** Launch-vehicle only: payload rows across all launches (many per launch). */
	payload_count?: number;
	/** Launch-vehicle only: launches with a successful outcome (GCAT Launch_Code). */
	success_count?: number;
	/** Launch-vehicle only: launches with a failure outcome. */
	failure_count?: number;
	/** Launch-vehicle only: latest launch date (ISO string). */
	last_launch_date?: string;
	/** Launch-vehicle only: per-variant breakdown, most-launched first, with GCAT specs. */
	variants?: LaunchVehicleVariant[];
	/** Launch-vehicle only: top individual reusable vehicles (orbiters/boosters) by flights. */
	reusable_vehicles?: ReusableVehicle[];
	/** Launch-site only: the GCAT places this range covers, busiest first. */
	gcat_sites?: GcatSite[];
	/** Launch-site only: pads GCAT lists across the range, including unplaced ones. */
	pad_count?: number;
	/** Discoveries per year across SBDB members (orbit_class / NEO / PHA), from `first_obs`. */
	discovery_histogram?: Record<string, number>;
	/** Biggest member by diameter; absent when nothing has a measured size.
	 *  `spkid` ids need the prefix; `object` ids are already whole (the
	 *  solar-system categories, ranked from PCK radii rather than SBDB). */
	largest_body?: {
		name: string;
		diameter_km: number;
		primary_type: 'spkid' | 'object';
		primary_id: string;
	};
	/** PHA subset of this orbit_class group; absent on flag-pha (self-link suppressed) and when zero. */
	pha?: { n: number; primary_type: 'group'; primary_id: 'flag-pha' };
	/** Top 20 members picked at export time (image/sitelinks/diameter rank); small-body groups only. */
	notable_members?: NotableMemberEntry[];
	/** Moons category only: moons per planet/dwarf host, ordered by heliocentric
	 *  distance. Drives the moons-per-planet bar chart. */
	moon_counts?: { name: string; primary_type: 'object'; primary_id: string; n: number }[];
	/** Feature-type only: distinct bodies carrying this feature type. Also set on
	 *  the Surface Features category, where it counts bodies across every type. */
	body_count?: number;
	/** Surface Features category only: feature types with at least one feature
	 *  (its child chips). Marks the page whose members are features. */
	feature_type_count?: number;
	/** Surface Features category only: the curated landform families its type
	 *  chips group into, in the export's narrative order. */
	feature_families?: FeatureFamily[];
	/** Surface Features category only: features per name etymology (IAU
	 *  `ethnicity`), most-named first, capped at the top 60. */
	naming_origins?: { name: string; n: number }[];
	/** Feature-type only: features of this type per body, most first — every body
	 *  it appears on, uncapped (the gazetteer covers ~50). Shares the
	 *  ``moon_counts`` row shape; both drive CountPerBodyChart. */
	feature_bodies?: { name: string; primary_type: 'object'; primary_id: string; n: number }[];
	/** Feature-type only: biggest example by IAU diameter; routes to the feature. */
	largest_feature?: {
		name: string;
		diameter_km: number;
		primary_type: string;
		primary_id: string;
		secondary_type: 'feature';
		secondary_id: string;
	};
	/** Feature-type only: earliest / latest IAU name approval (ISO date strings). */
	first_approval_date?: string;
	last_approval_date?: string;
	/** Feature-type only: IAU name approvals per year, sorted ascending. */
	approval_histogram?: Record<string, number>;
	/** Mission groups: focus redirect to the primary probe. The camera flies
	 *  there when the mission is opened from outside (see MapPage); members open
	 *  it without moving the camera. */
	primary?: { primary_type: 'object'; primary_id: string };
	/** Wikidata P571 — programme/operator inception (ISO date string). */
	inception?: string;
	/** Wikidata P576 — programme dissolution (ISO date string). */
	dissolved?: string;
	/** Earth orbit zones: typical perigee of the population, in km. */
	median_perigee_km?: number;
	/** Small-body flags: typical Earth MOID, in AU. */
	median_moid_au?: number;
	/** Feature types: typical diameter of the landform, in km. Absent when too
	 *  few members carry a measured one (albedo features). */
	median_diameter_km?: number;
	/** Planets / Dwarf planets categories: moons hosted across the category. */
	moon_total?: number;
	/** Moons category: distinct planet/dwarf hosts that have a moon. */
	host_count?: number;
	/** Categories that list child groups: Comets → split families, Probes →
	 *  missions. The label comes from the page, not the field. */
	child_group_count?: number;
	/** Missions: launch year. Probes category: the first probe launch. */
	launch_year?: number;
	/** Missions: state of the primary craft. */
	mission_status?: 'operating' | 'lost' | 'ended';
	/** Split-comet families: year the parent was first observed. Ring Systems:
	 *  the year the earliest system was found. */
	discovery_year?: number;
	/** Ring Systems: rows in the ring catalogue across every system — the rings
	 *  the tiles count plus the gaps, ringlets and arcs inside them. */
	ring_feature_count?: number;
	/** Ring Systems: the catalogue tables the page's counts, spans and masses
	 *  come from — its credit line, since it ships none of the per-body bundles
	 *  that carry them. Same shape as `GlobalObjectData.ring_sources`. */
	ring_sources?: Array<{ title: string; url: string; organisation: string }>;
	/** Ring Systems: the system reaching furthest from its host; the card links
	 *  to its Rings tab. */
	widest_rings?: {
		name: string;
		span_km: number;
		primary_type: 'object';
		primary_id: string;
	};
	/** Split-comet families: parent perihelion distance, in AU. */
	perihelion_au?: number;
	/** Atmospheres: kinds of envelope across the members — the `atmosphere.type`
	 *  vocabulary in use. The chart under it plots pressure, not this. */
	atmosphere_type_count?: number;
	/** Atmospheres: the air reaching highest, over the layers the cross-section
	 *  draws to scale. Thermospheres, exospheres and coronae are excluded — the
	 *  same three the chart caps — or Earth wins at 10,000 km on a gas too thin
	 *  to draw. */
	tallest_atmosphere?: {
		name: string;
		km: number;
		primary_type: 'object';
		primary_id: string;
	};
	/** Oceans: every listed ocean added up, in km³. Reads as a multiple of
	 *  Earth's, the only comparison that makes the figure mean anything. */
	ocean_volume_km3?: number;
	/** Oceans: the thickest one. Not what the chart ranks by — that is volume,
	 *  which a large cold moon wins on area as much as on depth. */
	deepest_ocean?: BodyRef & { thickness_km: number };
	/** Volcanism: the bodies caught in the act, by name. A list because four is
	 *  few enough that a reader wants to know which. */
	erupting_now?: string[];
	/** Volcanism / Tidal heating: the body losing the most heat. Io on both. */
	hottest_body?: BodyRef & { watts: number };
	/** Volcanism: vents, edifices and thermal sources anyone has mapped. */
	known_centres?: number;
	/** Tectonics: how many ways a crust behaves across the members — five,
	 *  with Earth alone in one of them. */
	tectonic_style_count?: number;
	/** Tectonics: members whose crust is moving now, not probably or once. */
	tectonic_active_count?: number;
	/** Magnetic fields: members generating one now, rather than induced,
	 *  remanent or absent. */
	dynamo_count?: number;
	/** Magnetic fields: strongest surface field. Non-detection bounds excluded. */
	strongest_field?: BodyRef & { tesla: number };
	/** Magnetic fields: the dipole furthest off its rotation axis — Uranus, 59°. */
	most_tilted_field?: BodyRef & { degrees: number };
	/** Tidal heating: members whose heat budget the tide *is*. */
	tide_dominant_count?: number;
	/** Same Commons pipeline / bundle layout as ``GlobalObjectData.images``. */
	images?: ObjectImage[];
	/** One shelf per notable member, keyed by its Object.id. */
	galleries?: ImageGalleryData[];
}

/** A stat card that points at one body. */
interface BodyRef {
	name: string;
	primary_type: 'object';
	primary_id: string;
}

export interface ChildGroupEntry extends EntityRef {
	/** Child group's type, so a category can section its children (orbit classes vs constellations). */
	role: GroupType;
	/** Child group's member count, for the chip. */
	n: number;
}

export interface LocalizedGroupData {
	name?: string;
	description?: string;
	wikipedia?: {
		extract?: string;
		description?: string;
		url?: string;
	};
	operators?: EntityRef[];
	/** Constellation-only: primes that build this constellation's hardware. */
	manufacturers?: EntityRef[];
	country_of_origin?: EntityRef[];
	instance_of?: EntityRef[];
	/** Top launch sites by member count, with localized name. */
	launch_sites?: LaunchSiteEntry[];
	/** Top constellations represented in this group's fleet (non-constellation groups only). */
	constellations?: ConstellationEntry[];
	/** Category-only: the child groups this category lists (zones, families, classes, constellations). */
	child_groups?: ChildGroupEntry[];
	/** lv- only: variant GCAT name → its Wikipedia ref, for variants matched to a more-specific Wikidata entity than the family. Keyed by the global `variants[].name`. */
	variant_refs?: Record<string, EntityRef>;
	/** lv- only: reusable-vehicle name → Wikipedia ref (Shuttle orbiters; cores have none). Keyed by `reusable_vehicles[].name`. */
	reusable_vehicle_refs?: Record<string, EntityRef>;
	/** site- only: GCAT pad code → Wikipedia ref. The pad chart keeps the GCAT
	 *  code as its label and uses this only for the link — a Wikipedia title is
	 *  often the parent complex's, shared by pads GCAT keeps apart. */
	pad_refs?: Record<string, EntityRef>;
	/** member Object.id → localized label for notable_members, only where it differs from the global name. */
	/** Commons filename → localized picture title; covers the collection's own
	 *  pictures and its member shelves alike. */
	image_titles?: Record<string, string>;
	notable_member_names?: Record<string, string>;
	/** member Object.id → localized Wikidata short description, for the lineup hero's hover tooltip. */
	notable_member_descriptions?: Record<string, string>;
	/** ft- only: `feature_bodies` row Object.id → localized body label. */
	body_names?: Record<string, string>;
}

export interface GroupDetailData {
	global: GlobalGroupData | null;
	localized: LocalizedGroupData | null;
}

export async function fetchGroupDetail(slug: string, lang = getLocale()): Promise<GroupDetailData> {
	const meta = await fetchMetadata();
	const bundles = meta.group_bundles;
	if (!bundles || !bundles.global) return { global: null, localized: null };

	const nLocalized = bundles[lang] ?? 0;
	const [globalBucket, localizedBucket] = await Promise.all([
		hashBucket(slug, bundles.global),
		nLocalized ? hashBucket(slug, nLocalized) : Promise.resolve(-1)
	]);

	const globalPromise = fetchGzipBundle<GlobalGroupData>(
		`${DATA_BASE}/v1/groups/__global__/${globalBucket}.json.gz`
	);
	const localizedPromise: Promise<LocalizedGroupData | undefined> =
		nLocalized > 0 && localizedBucket >= 0
			? fetchGzipBundle<LocalizedGroupData>(
					`${DATA_BASE}/v1/groups/${lang}/${localizedBucket}.json.gz`
				).then((b) => b[slug])
			: Promise.resolve(undefined);

	const [globalBundle, localized] = await Promise.all([globalPromise, localizedPromise]);
	return {
		global: globalBundle[slug] ?? null,
		localized: localized ?? null
	};
}
