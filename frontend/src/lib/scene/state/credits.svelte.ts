import { OrbitalSource } from '$lib/fetch/position/format';
import type { OrientationReference, OrientationSource } from '$lib/credits/orientation-sources';
import type { PositionedBody } from '$lib/types/objects';

/** Per-body texture attribution, recorded when system metadata loads.
 *  `systemId` scopes the bar to the focused system; the popover shows all. */
export interface TextureCredit {
	bodyId: string;
	systemId: string;
	source: string;
	organisation: string;
	license?: string;
	type: string;
	attribution?: string;
	description?: string;
}

/** Ring attribution, sibling to {@link TextureCredit} (same scoping). No
 *  `type` field — ring profiles are radial-only, unlike texture projections. */
export interface RingCredit {
	bodyId: string;
	systemId: string;
	source: string;
	organisation: string;
	license?: string;
	attribution?: string;
	description?: string;
}

/** Cloud-overlay attribution, sibling to {@link TextureCredit}. Earth-only
 *  today; surfaced under "Clouds" on the credits page. */
export interface CloudCredit {
	bodyId: string;
	systemId: string;
	source: string;
	organisation: string;
	license?: string;
	attribution?: string;
	description?: string;
}

/** Night-lights attribution, sibling to {@link CloudCredit}. Earth-only
 *  today; surfaced under "Night lights". */
export interface NightCredit {
	bodyId: string;
	systemId: string;
	source: string;
	organisation: string;
	license?: string;
	attribution?: string;
	description?: string;
}

/** Topography attribution, sibling to {@link NightCredit}; surfaced under "Topography". */
export interface DisplacementCredit {
	bodyId: string;
	systemId: string;
	source: string;
	organisation: string;
	license?: string;
	attribution?: string;
	description?: string;
}

/** Rotational-elements attribution, recorded when the scene adopts a body's
 *  orientation — credits whoever published the pole (PCK, DAMIT, a paper's fit). */
export interface OrientationCredit {
	bodyId: string;
	systemId: string;
	source: OrientationSource | undefined;
	reference?: OrientationReference;
}

export interface ModelCredit {
	bodyId: string;
	source: string;
	organisation: string;
	license?: string;
	/** Shape-model provenance, denormalized from `model_source` when the mesh loads. */
	provenance?: 'missions' | 'radar' | 'lightcurve';
	technique?: 'lightcurve_convex' | 'lightcurve_resolved';
	archive?: string;
	archiveUrl?: string;
	mission?: { name: string; id: string };
}

/** Whole-sky cubemap backdrop attribution — a single global asset, no per-body scoping. */
export interface SkyboxCredit {
	source: string;
	organisation: string;
	license?: string;
	attribution?: string;
	description?: string;
}

/** Attribution state for the credits bar, popover, and page. Each map pairs
 *  with a version counter bumped on first insertion so `$derived` consumers
 *  re-read; idempotent by `bodyId` so revisiting a system doesn't rebump. */
export class CreditsStore {
	texture = new Map<string, TextureCredit>();
	textureVersion = $state(0);
	ring = new Map<string, RingCredit>();
	ringVersion = $state(0);
	cloud = new Map<string, CloudCredit>();
	cloudVersion = $state(0);
	night = new Map<string, NightCredit>();
	nightVersion = $state(0);
	displacement = new Map<string, DisplacementCredit>();
	displacementVersion = $state(0);
	model = new Map<string, ModelCredit>();
	modelVersion = $state(0);
	orientation = new Map<string, OrientationCredit>();
	orientationVersion = $state(0);
	skybox = $state<SkyboxCredit | null>(null);
	/** Providers contributing to the loaded scene. Reassigned (not mutated) so
	 *  `$derived` bar consumers recompute. `UNKNOWN` is never added — pre-v3
	 *  chunks stay silent rather than showing a misleading label. */
	orbitSources = $state(new Set<OrbitalSource>());

	registerTexture(credit: TextureCredit): void {
		if (this.texture.has(credit.bodyId)) return;
		this.texture.set(credit.bodyId, credit);
		this.textureVersion++;
	}

	registerRing(credit: RingCredit): void {
		// Keyed by body + source: ring bundles cite several works (e.g. Saturn).
		const key = `${credit.bodyId}\u0000${credit.source}`;
		if (this.ring.has(key)) return;
		this.ring.set(key, credit);
		this.ringVersion++;
	}

	registerCloud(credit: CloudCredit): void {
		if (this.cloud.has(credit.bodyId)) return;
		this.cloud.set(credit.bodyId, credit);
		this.cloudVersion++;
	}

	registerNight(credit: NightCredit): void {
		if (this.night.has(credit.bodyId)) return;
		this.night.set(credit.bodyId, credit);
		this.nightVersion++;
	}

	registerDisplacement(credit: DisplacementCredit): void {
		if (this.displacement.has(credit.bodyId)) return;
		this.displacement.set(credit.bodyId, credit);
		this.displacementVersion++;
	}

	registerOrientation(credit: OrientationCredit): void {
		if (this.orientation.has(credit.bodyId)) return;
		this.orientation.set(credit.bodyId, credit);
		this.orientationVersion++;
	}

	registerModel(credit: ModelCredit): void {
		if (this.model.has(credit.bodyId)) return;
		this.model.set(credit.bodyId, credit);
		this.modelVersion++;
	}

	/** Fold each body's `orbitalSource` into the reactive set; no-op when the
	 *  batch is already known (keeps chunk flushes cheap). */
	recordOrbitSources(bodies: PositionedBody[]): void {
		let added = false;
		for (const b of bodies) {
			const src = b.data.orbitalSource;
			if (src === OrbitalSource.UNKNOWN || this.orbitSources.has(src)) continue;
			this.orbitSources.add(src);
			added = true;
		}
		if (added) this.orbitSources = new Set(this.orbitSources);
	}

	/** Record one chunk-level orbit source — minor chunks carry a single
	 *  provider byte for the whole file. */
	recordOrbitSource(src: OrbitalSource): void {
		if (src === OrbitalSource.UNKNOWN || this.orbitSources.has(src)) return;
		this.orbitSources.add(src);
		this.orbitSources = new Set(this.orbitSources);
	}
}
