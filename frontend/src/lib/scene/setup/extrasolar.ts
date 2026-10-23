import { EXTRASOLAR_PREFIX, extrasolarObjectId } from '$lib/fetch/extrasolar/ids';
import { extrasolarLookup, type ExtrasolarLookupResult } from '$lib/fetch/extrasolar/lookup';
import type { ContextManager } from '$lib/scene/state/context-manager.svelte';
import { makeStarBody } from '$lib/scene/focus/star-focus';

/**
 * Look up the extrasolar object `objectId` (`x-<id>`) and keep its body in
 * the scene, also under the alias that named it. Resolves with what the
 * lookup found: an alias resolves with its live object's answer.
 */
export async function ensureExtrasolarBody(
	ctx: ContextManager,
	objectId: string
): Promise<ExtrasolarLookupResult> {
	const text = objectId.slice(EXTRASOLAR_PREFIX.length);
	const first = await extrasolarLookup.lookup(text);
	const result = first.kind === 'alias' ? await extrasolarLookup.live(text) : first;
	if (result.kind === 'live') {
		const held = ctx.getBody(extrasolarObjectId(result.record.id));
		const body = held?.extrasolar ? held : makeStarBody(result.record);
		ctx.bodies.addExtrasolar(body, first.kind === 'alias' ? [objectId] : []);
	}
	return result;
}
