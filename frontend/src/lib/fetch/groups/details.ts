/**
 * Per-group detail bundle loader: global + (optionally) localized, same
 * hash-bucketing scheme as object bundles (sha256-first-4-bytes % N).
 */

import { getLocale } from '$lib/paraglide/runtime.js';
import { fetchMetadata, hashBucket } from '$lib/fetch/metadata';
import { DATA_BASE } from '$lib/fetch/data-base';
import type { EntityRef, ObjectImage } from '$lib/fetch/objects/object-data';
import type { GroupCategory, GroupType, SatelliteCategory } from './registry';

export interface LaunchSiteEntry extends EntityRef {
	n: number;
}

export interface GlobalGroupData {
	slug: string;
	type: GroupType;
	applies_to: GroupCategory;
	member_count: number;
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
	/** Wikidata P571 — programme/operator inception (ISO date string). */
	inception?: string;
	/** Wikidata P576 — programme dissolution (ISO date string). */
	dissolved?: string;
	/** Same Commons pipeline / bundle layout as ``GlobalObjectData.images``. */
	images?: ObjectImage[];
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
	country_of_origin?: EntityRef[];
	instance_of?: EntityRef[];
	/** Top launch sites by member count, with localized name. */
	launch_sites?: LaunchSiteEntry[];
}

export interface GroupDetailData {
	global: GlobalGroupData | null;
	localized: LocalizedGroupData | null;
}

const bundleCache = new Map<string, Promise<Record<string, unknown>>>();

async function fetchBundle<T>(url: string): Promise<Record<string, T>> {
	let p = bundleCache.get(url);
	if (!p) {
		p = (async () => {
			const res = await fetch(url);
			if (!res.ok) {
				if (res.status === 404) return {};
				throw new Error(`fetchBundle: ${url} returned ${res.status} ${res.statusText}`);
			}
			const ds = new DecompressionStream('gzip');
			return (await new Response(res.body!.pipeThrough(ds)).json()) as Record<string, unknown>;
		})();
		bundleCache.set(url, p);
	}
	return p as Promise<Record<string, T>>;
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

	const globalPromise = fetchBundle<GlobalGroupData>(
		`${DATA_BASE}/v1/groups/__global__/${globalBucket}.json.gz`
	);
	const localizedPromise: Promise<LocalizedGroupData | undefined> =
		nLocalized > 0 && localizedBucket >= 0
			? fetchBundle<LocalizedGroupData>(
					`${DATA_BASE}/v1/groups/${lang}/${localizedBucket}.json.gz`
				).then((b) => b[slug])
			: Promise.resolve(undefined);

	const [globalBundle, localized] = await Promise.all([globalPromise, localizedPromise]);
	return {
		global: globalBundle[slug] ?? null,
		localized: localized ?? null
	};
}
