import type { ContextManager } from '$lib/scene/state/context-manager.svelte';
import type { GlobalObjectData } from '$lib/fetch/objects/object-data';
import { nutPrecAwaited, nutPrecFor } from '$lib/fetch/systems-global';
import type { NutPrecSums } from '$lib/math/orientation';
import type { PositionedBody } from '$lib/types/objects';

type Orientation = NonNullable<GlobalObjectData['orientation']>;

/**
 * Single place the scene adopts a body's orientation, whichever path found it
 * first: the credit popover always has a source to point to, and what stands
 * on the body is placed again. The nutation terms come with it, as a spin
 * without them can be tens of degrees off (Mimas). Where global.json, which
 * holds the angles the terms pair with, has not loaded, the sums are kept for
 * {@link joinAwaitedNutation}, and the body is not drawn till then.
 */
export function applyBodyOrientation(
	body: PositionedBody,
	orientation: Orientation,
	nutPrec: NutPrecSums | undefined,
	ctx?: ContextManager,
	systemId?: string
): void {
	const id = body.data.id;
	body.orientation = orientation;
	body.nutPrec = nutPrecFor(id, nutPrec);
	body.nutPrecAwaited = nutPrecAwaited(id, nutPrec) ? nutPrec : undefined;
	if (body.nutPrecAwaited) ctx?.bodies.nutationAwaited.set(id, body);
	else ctx?.bodies.nutationAwaited.delete(id);
	if (ctx) ctx.bodies.dataVersion++;
	ctx?.credits.registerOrientation({
		bodyId: id,
		systemId: systemId ?? id,
		source: orientation.source,
		reference: orientation.reference
	});
}

/**
 * Settle the bodies whose spin came while global.json had not loaded, now
 * that it has, or will not: each takes its nutation terms where the file came
 * in, and goes on without them where it did not. Each is drawn from then on.
 * Returns the bodies whose spin changed, which the caller turns before they
 * show: Mimas's by 45° in 2026.
 */
export function joinAwaitedNutation(ctx: ContextManager): PositionedBody[] {
	const awaited = ctx.bodies.nutationAwaited;
	const turned: PositionedBody[] = [];
	for (const body of awaited.values()) {
		body.nutPrec = nutPrecFor(body.data.id, body.nutPrecAwaited);
		body.nutPrecAwaited = undefined;
		if (body.nutPrec) turned.push(body);
	}
	const settled = awaited.size > 0;
	awaited.clear();
	if (settled) ctx.bodies.dataVersion++;
	return turned;
}
