import { ObjectType, isAsteroid, type PositionedBody } from '$lib/types/objects';
import { fetchObjectDetail } from '$lib/fetch/objects/object-data';
import { bodyDataFromGlobal, pageOnlyBodyData } from '$lib/fetch/objects/global-body';
import { fetchLabels, type LabelMap } from '$lib/fetch/position/labels';
import type { ContextManager } from '$lib/scene/state/context-manager.svelte';
import { SSB_ID } from '$lib/constants';

/**
 * Bodies to add so that `targetId` is in the scene, built from the __global__
 * object file: the target last, after each ancestor the scene does not hold
 * (a moon of an asteroid loaded before the chunk of its host). The placement
 * pass gives them their places.
 *
 * A target whose bundle has no elements comes back as a page-only stand-in:
 * it has a page to open. An object with no bundle at all (or a parent cycle)
 * yields an empty array.
 *
 * Each entry's `zone` is the SBDB-class id (e.g. `"APO"`); null when the body
 * has no SBDB record, in which case the caller falls back to `parentId`-based
 * routing or `bodiesById`.
 */
export async function createPlaceholderBody(
	targetId: string,
	ctx: ContextManager,
	visited: Set<string> = new Set()
): Promise<Array<{ body: PositionedBody; zone: string | null }>> {
	if (visited.has(targetId)) {
		console.warn(`createPlaceholderBody: cycle detected at ${targetId} — hiding`);
		return [];
	}
	visited.add(targetId);
	let detail: Awaited<ReturnType<typeof fetchObjectDetail>>;
	try {
		detail = await fetchObjectDetail(targetId);
	} catch {
		console.warn(`createPlaceholderBody: failed to fetch global data for ${targetId} — hiding`);
		return [];
	}
	const global = detail.global;
	if (!global) {
		console.warn(`createPlaceholderBody: no catalogue record for ${targetId} — hiding`);
		return [];
	}
	const zone = global.sbdb?.class ?? null;
	const data = bodyDataFromGlobal(targetId, detail) ?? pageOnlyBodyData(targetId, detail);
	if (!data) return [];
	const parentId = data.parentId;
	const ancestors =
		parentId === '' || parentId === SSB_ID || ctx.getBody(parentId)
			? []
			: await createPlaceholderBody(parentId, ctx, visited);
	const body: PositionedBody = data.pageOnly
		? { data, position: null }
		: { data, position: null, orbitElements: data, orbitCenterId: parentId };
	return [...ancestors, { body, zone }];
}

/**
 * Route placeholders into the same per-zone store their real chunk will land
 * in, so a later stream reconciles them in place. Returns how many bodies were
 * routed into a bucket; the caller owns the flush.
 */
export function routePlaceholders(
	ctx: ContextManager,
	placeholders: Array<{ body: PositionedBody; zone: string | null }>,
	labels: LabelMap
): number {
	let added = 0;
	for (let i = 0; i < placeholders.length; i++) {
		const { body, zone } = placeholders[i];
		if (ctx.getBody(body.data.id)) continue;
		const type = body.data.objectType;
		const isCraft = type === ObjectType.SPACECRAFT || type === ObjectType.DEBRIS;
		const parentEntry = i > 0 ? placeholders[i - 1] : null;
		// Asteroid-moon placeholders steer into `small_body_moons` so they
		// reconcile via the auto-promote path into `bodyObjects` — not
		// `bodiesById`, where the moon `inSystem` filter would freeze them
		// once focus moves off.
		const resolvedZone =
			type === ObjectType.MOON && parentEntry && isAsteroid(parentEntry.body.data.objectType)
				? 'small_body_moons'
				: zone;
		if (isCraft && body.data.parentId !== '') {
			// Where its row from a position file lands, so the row replaces it.
			if (ctx.bodies.putSpacecraft(body)) added++;
			ctx.bodies.dirtySpacecraftGroups.add(body.data.parentId);
		} else if (resolvedZone && !body.data.pageOnly) {
			ctx.bodies.asteroidBucket(resolvedZone, labels).addPlaceholder(body);
			ctx.bodies.dirtyAsteroidZones.add(resolvedZone);
			added++;
		} else {
			// Major / undocumented / wikidata-only, or a stand-in with no row to
			// wait for: no zone to route into, so `bodiesById` holds it.
			ctx.bodies.addBodies([body]);
		}
		ctx.credits.recordOrbitSources([body]);
	}
	return added;
}

/** Add a single target to the running scene if absent — the in-session
 *  equivalent of {@link loadScene}'s URL-target placeholder pass (no reload). */
export async function ensureTargetStreamed(ctx: ContextManager, targetId: string): Promise<void> {
	if (ctx.getBody(targetId)) return;
	const placeholders = await createPlaceholderBody(targetId, ctx);
	if (placeholders.length === 0) return;
	const labels = await fetchLabels();
	const added = routePlaceholders(ctx, placeholders, labels);
	ctx.bodies.flushMinor(added > 0);
}
