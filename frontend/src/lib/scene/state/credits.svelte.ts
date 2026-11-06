import type { OrbitalSource, OrbitArchive } from '$lib/fetch/position/format';
import { orbitArchiveOf, orbitSourceInfo } from './orbit-sources';
import type { OrientationReference, OrientationSource } from '$lib/credits/orientation-sources';
import type { CreditFields, ImageryLayer } from '$lib/credits/imagery-layers';
import { patchCredits, tileCredit, type TiledMap } from '$lib/credits/tile-credit';
import type { PositionedBody } from '$lib/types/objects';
import type { ExtrasolarCredit } from '$lib/fetch/extrasolar/files';

/** The scope of an orbit archive that no one system holds. */
export const WHOLE_SCENE = 'whole-scene';

/** One credited work behind a body's imagery, recorded as the layer attaches.
 *  `systemId` scopes the bar and the popover to the system in view. */
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
	/** False once the starfield has taken the sky, or the layer is off. */
	skyboxDrawn = $state(true);
	/** The catalogues behind the starfield, while its stars draw. */
	stars = $state.raw<readonly ExtrasolarCredit[]>([]);
	/** The culture and catalogues behind the constellation lines, while they draw. */
	constellations = $state.raw<readonly ExtrasolarCredit[]>([]);
	/** Each archive behind the loaded scene and where its bodies are: their
	 *  parents, or `WHOLE_SCENE`. Reassigned so `$derived` bar consumers
	 *  recompute. */
	orbitFeeds = $state.raw(new Map<OrbitArchive, Set<string>>());

	/** A layer keeps one credit per body, so whichever path attaches it first —
	 *  per-system or standalone — wins. A surface or height map whose tile
	 *  pyramid holds another work is credited for both, and for each mosaic of
	 *  its patches. */
	registerImagery(layer: ImageryLayer, bodyId: string, systemId: string, meta: TiledMap): void {
		this.addImagery(layer, bodyId, systemId, meta, layer === 'rings');
		if (layer !== 'surface' && layer !== 'topography') return;
		const tiles = tileCredit(meta);
		for (const work of [...(tiles ? [tiles] : []), ...patchCredits(meta)]) {
			this.addImagery(layer, bodyId, systemId, work, true);
		}
	}

	/** `bySource` keys the credit on its source too, for a layer of several
	 *  works: one ring bundle cites more than one (Saturn). */
	private addImagery(
		layer: ImageryLayer,
		bodyId: string,
		systemId: string,
		meta: CreditFields,
		bySource: boolean
	): void {
		const key = [layer, bodyId, ...(bySource ? [meta.source] : [])].join('\u0000');
		if (this.imagery.has(key)) return;
		const { source, organisation, license, attribution, description, artist_impression } = meta;
		this.imagery.set(key, {
			layer,
			bodyId,
			systemId,
			source,
			organisation,
			license,
			attribution,
			description,
			artist_impression
		});
		this.imageryVersion++;
	}

	/** Credits of one layer, in insertion order. */
	imageryOf(layer: ImageryLayer): ImageryCredit[] {
		return [...this.imagery.values()].filter((c) => c.layer === layer);
	}

	setStars(credits: readonly ExtrasolarCredit[]): void {
		this.stars = credits;
	}

	setConstellations(credits: readonly ExtrasolarCredit[]): void {
		this.constellations = credits;
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

	recordOrbitSources(bodies: PositionedBody[]): void {
		let added = false;
		for (const { data } of bodies) {
			const archive = orbitArchiveOf(data);
			if (!archive) continue;
			const scoped = orbitSourceInfo(data.orbitalSource)?.scoped;
			if (this.addOrbitFeed(archive, scoped ? data.parentId : WHOLE_SCENE)) added = true;
		}
		if (added) this.orbitFeeds = new Map(this.orbitFeeds);
	}

	/** A minor chunk carries one provider byte for the whole file, and no parent
	 *  to scope it by: crediting it everywhere beats dropping the citation. */
	recordOrbitSource(source: OrbitalSource): void {
		const archive = orbitSourceInfo(source)?.archive;
		if (archive && this.addOrbitFeed(archive, WHOLE_SCENE)) {
			this.orbitFeeds = new Map(this.orbitFeeds);
		}
	}

	private addOrbitFeed(archive: OrbitArchive, scope: string): boolean {
		const scopes = this.orbitFeeds.get(archive) ?? new Set();
		if (scopes.has(scope)) return false;
		this.orbitFeeds.set(archive, scopes.add(scope));
		return true;
	}
}
