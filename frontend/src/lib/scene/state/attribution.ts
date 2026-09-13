/**
 * Who to credit for what is on screen right now. The chips follow the camera:
 * orbit providers for the loaded objects, imagery organisations for the
 * focused system and body. Shared by the app's attribution bar and the SDK's
 * control, so an embed credits exactly what the site does.
 */

import type { ContextManager } from './context-manager.svelte';
import {
	ORBIT_SOURCE_ORDER,
	ORBIT_SOURCES,
	type NamedOrbitSource,
	type OrbitSourceInfo
} from './orbit-sources';

export type OrbitSourceLabels = Record<NamedOrbitSource, string>;

/** Organisation names as they are cited, translated only where the app has a
 *  translation of its own to pass in. */
export const DEFAULT_ORBIT_LABELS: OrbitSourceLabels = Object.fromEntries(
	ORBIT_SOURCE_ORDER.map((s) => [s, ORBIT_SOURCES[s].label])
) as OrbitSourceLabels;

/** True while the camera sits in a system this scoped source fed. A source
 *  recorded without parents came off the chunk-level path, where crediting it
 *  everywhere beats dropping the citation. */
function feedsFocusedSystem(ctx: ContextManager, source: NamedOrbitSource): boolean {
	const parents = ctx.credits.orbitSourceParents.get(source);
	if (!parents) return true;
	const sysId = ctx.visibility.focusedSystemId;
	for (const parent of parents) if (ctx.bodies.isInSystem(parent, sysId)) return true;
	return false;
}

/** Which sources belong in the credits right now: everything that contributed,
 *  less the system-scoped providers while the camera is elsewhere. */
export function creditedOrbitSources(
	ctx: ContextManager
): Array<{ source: NamedOrbitSource; info: OrbitSourceInfo }> {
	return ORBIT_SOURCE_ORDER.filter((s) => ctx.credits.orbitSources.has(s))
		.filter((s) => !ORBIT_SOURCES[s].scoped || feedsFocusedSystem(ctx, s))
		.map((source) => ({ source, info: ORBIT_SOURCES[source] }));
}

/** Credits for the focused system plus the focused body — the latter covers
 *  standalones like Bennu and Ceres, credited body-by-body. */
export function scopedCredits<T extends { bodyId: string; systemId?: string | null }>(
	ctx: ContextManager,
	all: Iterable<T>
): T[] {
	const systemId = ctx.visibility.focusedSystemId;
	const bodyId = ctx.visibility.focusedBodyId;
	return [...all].filter((c) => c.bodyId === bodyId || (systemId && c.systemId === systemId));
}

export interface AttributionChips {
	/** Where the positions come from. */
	orbits: string[];
	/** Who produced the maps, rings, clouds, terrain and models in view. */
	imagery: string[];
}

/** Reads the credit stores' version counters, so a caller in a `$derived` or
 *  `$effect` recomputes as the scene loads. */
export function attributionChips(
	ctx: ContextManager,
	labels: OrbitSourceLabels = DEFAULT_ORBIT_LABELS
): AttributionChips {
	const credits = ctx.credits;
	void credits.imageryVersion;
	void credits.modelVersion;

	// Deduped on the label, so the translation decides which sources collapse.
	const orbits = [...new Set(creditedOrbitSources(ctx).map(({ source }) => labels[source]))];

	const organisations = new Set<string>();
	for (const credit of scopedCredits(ctx, credits.imagery.values())) {
		organisations.add(credit.organisation);
	}
	// Models are body-scoped: a probe's model credit doesn't bleed into the
	// system's other bodies.
	const bodyId = ctx.visibility.focusedBodyId;
	const model = bodyId ? credits.model.get(bodyId) : undefined;
	if (model) organisations.add(model.organisation);

	return { orbits, imagery: [...organisations].sort() };
}
