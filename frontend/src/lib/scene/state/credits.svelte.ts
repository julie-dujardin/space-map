import { OrbitalSource } from '$lib/fetch/position/format';
import type { OrientationReference, OrientationSource } from '$lib/credits/orientation-sources';
import type { CreditFields, ImageryLayer } from '$lib/credits/imagery-layers';
import type { PositionedBody } from '$lib/types/objects';

/** One credited work behind a body's imagery, recorded as the layer attaches.
 *  `systemId` scopes the bar to the focused system; the popover shows all. */
export interface ImageryCredit extends CreditFields {
	layer: ImageryLayer;
	bodyId: string;
	systemId: string;
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
 *  re-read; registration is idempotent, so revisiting a system doesn't rebump. */
export class CreditsStore {
	imagery = new Map<string, ImageryCredit>();
	imageryVersion = $state(0);
	model = new Map<string, ModelCredit>();
	modelVersion = $state(0);
	orientation = new Map<string, OrientationCredit>();
	orientationVersion = $state(0);
	skybox = $state<SkyboxCredit | null>(null);
	/** Providers contributing to the loaded scene. Reassigned (not mutated) so
	 *  `$derived` bar consumers recompute. `UNKNOWN` is never added — pre-v3
	 *  chunks stay silent rather than showing a misleading label. */
	orbitSources = $state(new Set<OrbitalSource>());

	/** Rings key on the source too: one bundle cites several works (Saturn).
	 *  Every other layer keeps one credit per body, so whichever path attaches
	 *  it first — per-system or standalone — wins. */
	registerImagery(layer: ImageryLayer, bodyId: string, systemId: string, meta: CreditFields): void {
		const sep = '\u0000';
		const key =
			layer === 'rings' ? `${layer}${sep}${bodyId}${sep}${meta.source}` : `${layer}${sep}${bodyId}`;
		if (this.imagery.has(key)) return;
		const { source, organisation, license, attribution, description } = meta;
		this.imagery.set(key, {
			layer,
			bodyId,
			systemId,
			source,
			organisation,
			license,
			attribution,
			description
		});
		this.imageryVersion++;
	}

	/** Credits of one layer, in insertion order. */
	imageryOf(layer: ImageryLayer): ImageryCredit[] {
		return [...this.imagery.values()].filter((c) => c.layer === layer);
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
