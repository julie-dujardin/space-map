import { isDrawn, type BodyObjects } from '$lib/scene/types';
import { isModelBearing } from './model';

/** A craft's model loads once it would span this many pixels, and goes again
 *  under the lower figure: between the two it stays as it is. */
export const NEARBY_LOAD_PX = 4;
export const NEARBY_UNLOAD_PX = 2;
/** Most craft models held for being near at once; the nearest win. */
export const NEARBY_MAX = 4;

/**
 * The models of the craft near enough to the camera to show as more than a
 * dot: a rover under a camera over its crater, an orbiter passing it. The
 * focus holds its own models; this loads and drops only the others.
 */
export class NearbyModels {
	private readonly held = new Set<BodyObjects>();
	/** Craft whose model failed to load: not asked for again this session. */
	private readonly failed = new WeakSet<BodyObjects>();

	constructor(
		private readonly load: (bo: BodyObjects) => Promise<void>,
		private readonly unload: (bo: BodyObjects) => void,
		/** Whether the focus holds `id`'s model: it is not this one's to drop. */
		private readonly focusHolds: (id: string) => boolean
	) {}

	/** `pxPerRad` turns a craft's angular size into pixels. Each craft's
	 *  `cachedDist` is this frame's. */
	update(bodyObjects: Map<string, BodyObjects>, pxPerRad: number): void {
		const near: { bo: BodyObjects; px: number }[] = [];
		for (const bo of bodyObjects.values()) {
			if (!isModelBearing(bo.body) || !isDrawn(bo) || bo.isCrashed) continue;
			if (bo.noPhysical === 'model' || this.failed.has(bo)) continue;
			if (this.focusHolds(bo.body.data.id)) continue;
			const px = (bo.radiusScene / bo.cachedDist) * pxPerRad;
			const wanted = px >= (this.held.has(bo) ? NEARBY_UNLOAD_PX : NEARBY_LOAD_PX);
			if (wanted) near.push({ bo, px });
		}
		near.sort((a, b) => b.px - a.px);
		const keep = new Set(near.slice(0, NEARBY_MAX).map((n) => n.bo));
		for (const bo of this.held) {
			if (keep.has(bo)) continue;
			this.held.delete(bo);
			if (!this.focusHolds(bo.body.data.id) && bodyObjects.get(bo.body.data.id) === bo) {
				this.unload(bo);
			}
		}
		for (const bo of keep) {
			this.held.add(bo);
			if (bo.model || bo.modelLoadPromise) continue;
			this.load(bo).catch((err: unknown) => {
				this.failed.add(bo);
				console.warn(`[models] ${bo.body.data.id} did not load:`, err);
			});
		}
	}

	/** The nearest craft held here whose model is in and drawn. */
	nearest(): BodyObjects | null {
		let nearest: BodyObjects | null = null;
		for (const bo of this.held) {
			if (!bo.model || !isDrawn(bo)) continue;
			if (!nearest || bo.cachedDist < nearest.cachedDist) nearest = bo;
		}
		return nearest;
	}
}
