/**
 * Whether the Overview's Atmosphere and Interior sections have a Structure tab
 * to send anyone to, and what they will find when they get there.
 *
 * Both sections link to the same tab, so both ask the same question: the air
 * and the body cut open are two halves of one page, and either half existing is
 * reason enough for the other's section to point at it.
 */

import type { GlobalObjectData } from '$lib/fetch/objects/object-data';
import { atmosphereProfile } from './atmosphere-cross-section';

export interface StructureLink {
	/** Whether a stack of named layers is actually drawn there. Callisto has an
	 *  atmosphere structure whose exosphere nobody has put a top on, so it
	 *  arrives with nothing to draw and only its composition to show. */
	layers: boolean;
}

export function structureLink(global: GlobalObjectData | null): StructureLink | null {
	const interiorLayers = global?.interior?.layers?.length ?? 0;
	const air = global?.atmosphere?.structure;
	if (!interiorLayers && !air) return null;
	const bands = air ? (atmosphereProfile(air)?.bands.length ?? 0) : 0;
	return { layers: interiorLayers > 0 || bands > 0 };
}
