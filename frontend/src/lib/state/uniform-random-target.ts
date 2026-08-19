/**
 * The draw `/random` refuses to make: every catalogued thing in one hat.
 *
 * A ticket per object, per surface feature and per collection page, so the odds
 * are the catalogue's own shape: 99% of the tickets are objects, six draws in
 * seven land on a numbered rock in the Main Belt, and the 858 collection pages
 * share one draw in two thousand. This is what `/random` refuses, and why it
 * walks the collection tree instead.
 *
 * No memory of past draws and no reweighting. A repeat is what uniform looks
 * like, and at 1.6 M tickets there won't be one.
 */

import { fetchGzipBundle } from '$lib/fetch/bundle-cache';
import { versionedUrl } from '$lib/fetch/data-base';
import { fetchGroupDetail } from '$lib/fetch/groups/details';
import {
	categoryLabel,
	fetchGroupIndex,
	CAT_SOLAR_SYSTEM,
	CAT_SURFACE_FEATURES,
	type GroupIndex
} from '$lib/fetch/groups/registry';
import { fetchMetadata } from '$lib/fetch/metadata';
import { fetchBodyNomenclature } from '$lib/fetch/nomenclature/fetch';
import type { GlobalObjectData } from '$lib/fetch/objects/object-data';
import { getLocale, type Locale } from '$lib/paraglide/runtime.js';
import type { RandomTarget } from './random-target';

function randomIndex(n: number): number {
	return Math.floor(Math.random() * n);
}

/** One kind of destination: how many there are, and how to draw one. */
interface Pool {
	weight: number;
	draw: (locale: Locale) => Promise<RandomTarget | null>;
}

/**
 * Draw a destination with every catalogued thing equally likely.
 *
 * The counts come from the group index, which is a few kilobytes the app has
 * already loaded: the Solar System page counts the objects, the Surface
 * features page counts the landforms, and the index's own length counts the
 * collection pages. Nothing else is cheap enough to count per draw.
 */
export async function uniformRandomTarget(locale = getLocale()): Promise<RandomTarget | null> {
	let index: GroupIndex;
	try {
		index = await fetchGroupIndex();
	} catch (e) {
		console.warn('[uniform-random] the group index is unreachable — nothing to count.', e);
		return null;
	}

	const pool = pick([
		{ weight: index[CAT_SOLAR_SYSTEM]?.n ?? 0, draw: drawObject },
		{ weight: index[CAT_SURFACE_FEATURES]?.n ?? 0, draw: drawFeature },
		{ weight: Object.keys(index).length, draw: (l: Locale) => drawCollection(index, l) }
	]);
	if (!pool) return null;

	try {
		return await pool.draw(locale);
	} catch (e) {
		console.warn('[uniform-random] the drawn bundle is unreachable — no destination.', e);
		return null;
	}
}

/** A pool, in proportion to how much of the catalogue it is. */
function pick(pools: Pool[]): Pool | null {
	const total = pools.reduce((sum, p) => sum + p.weight, 0);
	if (total <= 0) return null;
	let ticket = Math.random() * total;
	for (const p of pools) {
		ticket -= p.weight;
		if (ticket < 0) return p;
	}
	return pools[pools.length - 1];
}

/**
 * One object out of the hash-bucketed detail bundles — the only enumeration of
 * the catalogue the frontend can reach, since no index lists 1.6 M ids.
 *
 * A bucket, then an entry in it. The hash spreads objects evenly to within a
 * few percent, so an object in a light bundle is a few percent likelier than
 * one in a heavy one; levelling that would cost a second megabyte to move odds
 * of one in 1.6 M by one part in thirty.
 */
async function drawObject(): Promise<RandomTarget | null> {
	const meta = await fetchMetadata();
	const buckets = meta.object_bundles?.global ?? 0;
	if (buckets <= 0) return null;

	const bundle = await fetchGzipBundle<GlobalObjectData>(
		versionedUrl(`/v1/objects/__global__/${randomIndex(buckets)}.json.gz`, 'objects')
	);
	const ids = Object.keys(bundle);
	if (ids.length === 0) return null;

	const id = ids[randomIndex(ids.length)];
	// The global bundle names every object; the localized overlay only renames
	// the few hundred with a translated name, and isn't worth a second bundle.
	return { kind: 'object', id, name: bundle[id]?.name ?? id };
}

/** One landform, drawn the same way. Bundle keys are `${bodyId}:${featureId}`. */
async function drawFeature(locale: Locale): Promise<RandomTarget | null> {
	const meta = await fetchMetadata();
	const buckets = meta.feature_bundles?.global ?? 0;
	if (buckets <= 0) return null;

	const bundle = await fetchGzipBundle<unknown>(
		versionedUrl(
			`/v1/nomenclature/details/__global__/${randomIndex(buckets)}.json.gz`,
			'nomenclature'
		)
	);
	const keys = Object.keys(bundle);
	if (keys.length === 0) return null;

	const [bodyId, rawId] = keys[randomIndex(keys.length)].split(':');
	const featureId = Number(rawId);
	return { kind: 'feature', bodyId, featureId, name: await featureName(bodyId, featureId, locale) };
}

/** Feature names live in the per-body label file, not the detail bundle. An
 *  unnamed target still routes: the name segment is decoration. */
async function featureName(bodyId: string, featureId: number, locale: Locale): Promise<string> {
	try {
		const features = await fetchBodyNomenclature(bodyId, locale);
		return features.find((f) => f.featureId === featureId)?.name ?? '';
	} catch {
		return '';
	}
}

/** One collection page. The index is the list of pages there are, so this pool
 *  needs no bundle at all. */
async function drawCollection(index: GroupIndex, locale: Locale): Promise<RandomTarget | null> {
	const slugs = Object.keys(index);
	if (slugs.length === 0) return null;
	const slug = slugs[randomIndex(slugs.length)];
	const detail = await fetchGroupDetail(slug, locale).catch(() => null);
	return { kind: 'group', slug, name: detail?.localized?.name ?? categoryLabel(slug) };
}
