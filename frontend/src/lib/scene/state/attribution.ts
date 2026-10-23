/**
 * Who to credit for what is on screen right now. The chips follow the camera:
 * orbit providers for the loaded objects, imagery organisations for the
 * focused system and body. Shared by the app's attribution bar and the SDK's
 * control, so an embed credits exactly what the site does.
 */

import { PROBE_ARCHIVES, type OrbitArchive } from '$lib/fetch/position/format';
import type { ContextManager } from './context-manager.svelte';
import {
	ORBIT_ARCHIVE_ORGANISATIONS,
	ORBIT_SOURCE_ORDER,
	ORBIT_SOURCES,
	type NamedOrbitSource
} from './orbit-sources';

/** Organisation names as they are cited, translated only where the app has a
 *  translation of its own to pass in. */
export type OrbitArchiveLabels = Record<OrbitArchive, string>;

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

/** Which archives belong in the credits right now: every one that fed a body
 *  of the scene, less the system-scoped providers while the camera is
 *  elsewhere. Several sources share an archive (SBDB serves both the small
 *  bodies and their moons), so each is listed once. */
export function creditedOrbitArchives(ctx: ContextManager): OrbitArchive[] {
	const credits = ctx.credits;
	const archives = new Set<OrbitArchive>();
	for (const source of ORBIT_SOURCE_ORDER) {
		if (!credits.orbitSources.has(source)) continue;
		const { archive, scoped } = ORBIT_SOURCES[source];
		if (scoped && !feedsFocusedSystem(ctx, source)) continue;
		if (archive) archives.add(archive);
		else for (const a of PROBE_ARCHIVES) if (a && credits.probeArchives.has(a)) archives.add(a);
	}
	return [...archives];
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
	/** The catalogues whose licence asks for credit, once stars have drawn. */
	stars: string[];
}

/** Reads the credit stores' version counters, so a caller in a `$derived` or
 *  `$effect` recomputes as the scene loads. */
export function attributionChips(
	ctx: ContextManager,
	labels: OrbitArchiveLabels = ORBIT_ARCHIVE_ORGANISATIONS
): AttributionChips {
	const credits = ctx.credits;
	void credits.imageryVersion;
	void credits.modelVersion;

	// Deduped on the label, so the translation decides which archives collapse.
	const orbits = [...new Set(creditedOrbitArchives(ctx).map((archive) => labels[archive]))];

	const organisations = new Set<string>();
	for (const credit of scopedCredits(ctx, credits.imagery.values())) {
		organisations.add(credit.organisation);
	}
	// Models are body-scoped: a probe's model credit doesn't bleed into the
	// system's other bodies.
	const bodyId = ctx.visibility.focusedBodyId;
	const model = bodyId ? credits.model.get(bodyId) : undefined;
	if (model) organisations.add(model.organisation);

	const stars = [...new Set(credits.stars.filter((c) => c.license).map((c) => c.organisation))];

	return { orbits, imagery: [...organisations].sort(), stars };
}
