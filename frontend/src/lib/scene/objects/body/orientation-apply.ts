import type { ContextManager } from '$lib/scene/state/context-manager.svelte';
import type { GlobalObjectData } from '$lib/fetch/objects/object-data';
import { nutPrecFor } from '$lib/fetch/systems-global';
import type { NutPrecSums } from '$lib/math/orientation';
import type { PositionedBody } from '$lib/types/objects';

type Orientation = NonNullable<GlobalObjectData['orientation']>;

/**
 * Single place the scene adopts a body's orientation, whichever path found it
 * first: the credit popover always has a source to point to, and what stands
 * on the body is placed again. The nutation terms come with it, as a spin
 * without them can be tens of degrees off (Mimas).
 */
export function applyBodyOrientation(
	body: PositionedBody,
	orientation: Orientation,
	nutPrec: NutPrecSums | undefined,
	ctx?: ContextManager,
	systemId?: string
): void {
	body.orientation = orientation;
	body.nutPrec = nutPrecFor(body.data.id, nutPrec);
	if (ctx) ctx.bodies.dataVersion++;
	ctx?.credits.registerOrientation({
		bodyId: body.data.id,
		systemId: systemId ?? body.data.id,
		source: orientation.source,
		reference: orientation.reference
	});
}
