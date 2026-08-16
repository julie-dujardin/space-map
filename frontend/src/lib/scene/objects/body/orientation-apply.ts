import type { ContextManager } from '$lib/scene/state/context-manager.svelte';
import type { GlobalObjectData } from '$lib/fetch/objects/object-data';
import type { BodyObjects } from '../../types';

type Orientation = NonNullable<GlobalObjectData['orientation']>;

/**
 * Single place the scene adopts a body's orientation, whichever path found it
 * first — so the credit popover always has a source to point to.
 */
export function applyBodyOrientation(
	bo: BodyObjects,
	orientation: Orientation,
	ctx?: ContextManager,
	systemId?: string
): void {
	bo.body.orientation = orientation;
	ctx?.credits.registerOrientation({
		bodyId: bo.body.data.id,
		systemId: systemId ?? bo.body.data.id,
		source: orientation.source,
		reference: orientation.reference
	});
}
