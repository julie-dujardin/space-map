/**
 * Who to credit for what is on screen right now. The chips follow the camera:
 * orbit providers for the loaded objects, imagery organisations for the
 * focused system and body. Shared by the app's attribution bar and the SDK's
 * control, so an embed credits exactly what the site does.
 */

import { OrbitalSource } from '$lib/fetch/position/format';
import type { ContextManager } from './context-manager.svelte';

type NamedSource = Exclude<OrbitalSource, OrbitalSource.UNKNOWN>;

/** Display order after de-duplication; NASA-produced sources collapse into one chip. */
const ORBIT_ORDER: NamedSource[] = [
	OrbitalSource.HORIZONS,
	OrbitalSource.SBDB,
	OrbitalSource.SPICE,
	OrbitalSource.SBDB_MOON,
	OrbitalSource.ASTERSAT,
	OrbitalSource.SPICE_PROBE,
	OrbitalSource.CELESTRAK,
	OrbitalSource.SPACETRACK
];

/** Only Earth satellites come from these, so they stay out of the bar elsewhere. */
const EARTH_SAT_SOURCES = new Set<OrbitalSource>([
	OrbitalSource.CELESTRAK,
	OrbitalSource.SPACETRACK
]);

export type OrbitSourceLabels = Record<NamedSource, string>;

/** Organisation names as they are cited, translated only where the app has a
 *  translation of its own to pass in. */
export const DEFAULT_ORBIT_LABELS: OrbitSourceLabels = {
	[OrbitalSource.HORIZONS]: 'NASA',
	[OrbitalSource.SBDB]: 'NASA',
	[OrbitalSource.SPICE]: 'NASA',
	[OrbitalSource.SBDB_MOON]: 'NASA',
	[OrbitalSource.ASTERSAT]: 'Natural Satellites Data Base',
	[OrbitalSource.SPICE_PROBE]: 'NASA',
	[OrbitalSource.CELESTRAK]: 'CelesTrak',
	[OrbitalSource.SPACETRACK]: 'Space-Track.org'
};

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
	void credits.textureVersion;
	void credits.ringVersion;
	void credits.cloudVersion;
	void credits.displacementVersion;
	void credits.modelVersion;

	const inEarthSystem = ctx.visibility.isFocusedOnEarthSystem();
	const seen = new Set<string>();
	const orbits: string[] = [];
	for (const source of ORBIT_ORDER) {
		if (!credits.orbitSources.has(source)) continue;
		if (EARTH_SAT_SOURCES.has(source) && !inEarthSystem) continue;
		const label = labels[source];
		if (seen.has(label)) continue;
		seen.add(label);
		orbits.push(label);
	}

	const systemId = ctx.visibility.focusedSystemId;
	const bodyId = ctx.visibility.focusedBodyId;
	const organisations = new Set<string>();
	for (const store of [credits.texture, credits.ring, credits.cloud, credits.displacement]) {
		for (const credit of store.values()) {
			if (credit.bodyId === bodyId || (systemId && credit.systemId === systemId)) {
				organisations.add(credit.organisation);
			}
		}
	}
	// Models are body-scoped: a probe's model credit doesn't bleed into the
	// system's other bodies.
	const model = bodyId ? credits.model.get(bodyId) : undefined;
	if (model) organisations.add(model.organisation);

	return { orbits, imagery: [...organisations].sort() };
}
