import type { ContextManager } from '$lib/scene/state/context-manager.svelte';
import type { GlobalObjectData } from '$lib/fetch/objects/object-data';
import type { BodyObjects } from '../../types';

type Orientation = NonNullable<GlobalObjectData['orientation']>;

/**
 * Adopt a body's rotational elements, from wherever they arrived — the system
 * file, the object bundle, or the shape-model path that races it. The single
 * place the scene takes an orientation, so the attribution popover can credit
 * whoever published it without each caller remembering to.
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
