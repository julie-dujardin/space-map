import { OrbitalSource } from '$lib/fetch/position/format';
import type { OrientationReference, OrientationSource } from '$lib/credits/orientation-sources';
import type { PositionedBody } from '$lib/types/objects';

/**
 * Per-body texture attribution recorded when its system metadata loads.
 * `systemId` is the barycenter ID the body belongs to, used by the bar to
 * show imagery credits only for the focused system while the popover shows
 * every loaded texture regardless of focus.
 */
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

/**
 * Per-body planetary-ring attribution recorded when its system metadata
 * loads. Sibling to {@link TextureCredit} — same scoping rules apply (bar
 * filters by focused system / focused body, popover surfaces all loaded).
 * No `type` field: textures distinguish projections (cylindrical, …), but
 * ring profiles are radial-only, so the qualifier is implicit.
 */
export interface RingCredit {
	bodyId: string;
	systemId: string;
	source: string;
	organisation: string;
	license?: string;
	attribution?: string;
	description?: string;
}

/**
 * Per-body cloud-overlay attribution recorded when its system metadata
 * loads. Sibling to {@link TextureCredit} / {@link RingCredit} — same
 * scoping rules apply. Earth is the only producer today; the credits page
 * surfaces these under their own "Clouds" section.
 */
export interface CloudCredit {
	bodyId: string;
	systemId: string;
	source: string;
	organisation: string;
	license?: string;
	attribution?: string;
	description?: string;
}

/**
 * Per-body night-lights attribution recorded when its system metadata loads.
 * Sibling to {@link CloudCredit} — same scoping rules apply. Earth is the
 * only producer today; the credits page surfaces these under their own
 * "Night lights" section.
 */
export interface NightCredit {
	bodyId: string;
	systemId: string;
	source: string;
	organisation: string;
	license?: string;
	attribution?: string;
	description?: string;
}

/**
 * Per-body displacement/topography attribution, recorded when system metadata
 * loads. Sibling to {@link NightCredit}; surfaced under "Topography".
 */
export interface DisplacementCredit {
	bodyId: string;
	systemId: string;
	source: string;
	organisation: string;
	license?: string;
	attribution?: string;
	description?: string;
}

/**
 * Per-body spacecraft-model attribution, recorded when its GLB finishes
 * loading. Scoped to the focused body only — the popover/bar surface this
 * for the single focused probe (vs. textures, which spread across a whole
 * planetary system). `source` is the catalog landing page (e.g.
 * `https://www.nasa.gov/3d-resources/`), `organisation` the catalog name
 * (`NASA-3D-Resources`).
 */
/**
 * Per-body rotational-elements attribution, recorded when the scene adopts a
 * body's orientation. The renderer spins bodies by these elements, so the
 * popover credits whoever published them — PCK for the kernels, DAMIT for a
 * lightcurve pole, the paper itself for an occultation fit.
 */
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
	/** Natural-body shape models carry their provenance too, denormalized from
	 *  `model_source` when the mesh loads: how the shape was derived, the
	 *  archive that distributes it, and the spacecraft that observed it. The
	 *  mesh is scene content, so this is the surface that credits it. */
	provenance?: 'missions' | 'radar' | 'lightcurve';
	technique?: 'lightcurve_convex' | 'lightcurve_resolved';
	archive?: string;
	archiveUrl?: string;
	mission?: { name: string; id: string };
}

/**
 * Whole-sky cubemap backdrop attribution. Recorded once when `loadSkybox`
 * resolves the bundle metadata; no per-body scoping because the skybox is a
 * single global asset rendered behind the whole scene.
 */
export interface SkyboxCredit {
	source: string;
	organisation: string;
	license?: string;
	attribution?: string;
	description?: string;
}

/**
 * Attribution state for the bottom-right bar, the in-map popover, and the
 * standalone credits page. Owns per-body imagery credits (texture/ring/cloud),
 * the global skybox credit, and the set of OrbitalSources contributing to the
 * loaded scene.
 *
 * Each map is paired with a version counter that bumps on first insertion for
 * a given body so `$derived` consumers re-read. Idempotent by `bodyId` so
 * revisiting a system doesn't spuriously bump versions.
 */
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
	/**
	 * Providers that have contributed at least one body to the loaded scene.
	 * Reassigned (not mutated) on new arrivals so `$derived` consumers — the
	 * bottom-right attribution bar — recompute. `OrbitalSource.UNKNOWN` is
	 * never added; pre-v3 chunks with no source byte stay silent rather than
	 * showing a misleading "Unknown" label.
	 */
	orbitSources = $state(new Set<OrbitalSource>());

	registerTexture(credit: TextureCredit): void {
		if (this.texture.has(credit.bodyId)) return;
		this.texture.set(credit.bodyId, credit);
		this.textureVersion++;
	}

	registerRing(credit: RingCredit): void {
		// Keyed by body *and* source: a body's ring bundles cite several works
		// (Saturn credits Björn Jónsson and NASA separately).
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

	/**
	 * Fold each body's `orbitalSource` into the reactive set. Reassigns on new
	 * entries so `$derived` consumers recompute; no-op when everything in the
	 * batch is already known (keeps minor-body chunk flushes cheap).
	 */
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

	/** Record one chunk-level orbit source. Minor chunks are single-source
	 *  (the elements payload carries one provider byte for the whole file), so
	 *  the columnar ingest path folds it in once per chunk instead of per row. */
	recordOrbitSource(src: OrbitalSource): void {
		if (src === OrbitalSource.UNKNOWN || this.orbitSources.has(src)) return;
		this.orbitSources.add(src);
		this.orbitSources = new Set(this.orbitSources);
	}
}
