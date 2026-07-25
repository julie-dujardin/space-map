/**
 * Per-group detail bundle loader: global + (optionally) localized, same
 * hash-bucketing scheme as object bundles (sha256-first-4-bytes % N).
 */

import { getLocale } from '$lib/paraglide/runtime.js';
import { fetchMetadata, hashBucket } from '$lib/fetch/metadata';
import { fetchGzipBundle } from '$lib/fetch/bundle-cache';
import { DATA_BASE } from '$lib/fetch/data-base';
import type { EntityRef, NotableMemberEntry, ObjectImage } from '$lib/fetch/objects/object-data';
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

export interface ReusableVehicle {
	/** Vehicle id, also the display label (Shuttle orbiter / Falcon core serial). */
	name: string;
	/** Flights flown by this individual vehicle. */
	n: number;
	first_flight?: string;
	last_flight?: string;
}

export interface GlobalGroupData {
	slug: string;
	type: GroupType;
	applies_to: GroupCategory;
	member_count: number;
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
	/** Discoveries per year across SBDB members (orbit_class / NEO / PHA), from `first_obs`. */
	discovery_histogram?: Record<string, number>;
	/** Member with the largest SBDB.diameter; absent when no member has a measured diameter. */
	largest_body?: {
		name: string;
		diameter_km: number;
		primary_type: 'spkid';
		primary_id: string;
	};
	/** PHA subset of this orbit_class group; absent on flag-pha (self-link suppressed) and when zero. */
	pha?: { n: number; primary_type: 'group'; primary_id: 'flag-pha' };
	/** Top 20 members picked at export time (image/sitelinks/diameter rank); small-body groups only. */
	notable_members?: NotableMemberEntry[];
	/** Moons category only: moons per planet/dwarf host, ordered by heliocentric
	 *  distance. Drives the moons-per-planet bar chart. */
	moon_counts?: { name: string; primary_type: 'object'; primary_id: string; n: number }[];
	/** Feature-type only: distinct bodies carrying this feature type (the chart
	 *  rows are capped, this is the full tally). */
	body_count?: number;
	/** Feature-type only: features of this type per body, most first (top 12).
	 *  Shares the ``moon_counts`` row shape — both drive CountPerBodyChart. */
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
	/** Same Commons pipeline / bundle layout as ``GlobalObjectData.images``. */
	images?: ObjectImage[];
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
	/** member Object.id → localized label for notable_members, only where it differs from the global name. */
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
