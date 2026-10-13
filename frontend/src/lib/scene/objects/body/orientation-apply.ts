import type { ContextManager } from '$lib/scene/state/context-manager.svelte';
import type { GlobalObjectData } from '$lib/fetch/objects/object-data';
import type { PositionedBody } from '$lib/types/objects';

type Orientation = NonNullable<GlobalObjectData['orientation']>;

/**
 * Single place the scene adopts a body's orientation, whichever path found it
 * first: the credit popover always has a source to point to, and what stands
 * on the body is placed again.
 */
export function applyBodyOrientation(
	body: PositionedBody,
	orientation: Orientation,
	ctx?: ContextManager,
	systemId?: string
): void {
	body.orientation = orientation;
	if (ctx) ctx.bodies.dataVersion++;
	ctx?.credits.registerOrientation({
		bodyId: body.data.id,
		systemId: systemId ?? body.data.id,
		source: orientation.source,
		reference: orientation.reference
	});
}
