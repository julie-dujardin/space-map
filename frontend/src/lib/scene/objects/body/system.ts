import { type Scene, SphereGeometry, type TextureLoader } from 'three';
import { kmToScene } from '$lib/math/units';
import { effectiveRadiusKm } from '$lib/types/objects';
import { applyOrientation } from '$lib/math/orientation';
import { getNutPrecAngles, ownerIdFor } from '$lib/fetch/systems-global';
import { dataBase } from '$lib/fetch/data-base';
import type { ContextManager } from '$lib/scene/state/context-manager.svelte';
import { disposeRingNode, type RingMeta } from '../surface/rings';
import { attachRingBundles } from '../surface/ring-attach';
import { disposeNomenclatureLabels } from '../surface/nomenclature';
import type { BodyObjects } from '../../types';
import { applyBodyOrientation } from './orientation-apply';
import { loadSiblingLayers, type SiblingBundles, unloadSiblingLayers } from './sibling-layers';
import {
	applyRadiiToMesh,
	loadBodyTextureTier,
	textureFrameForJd,
	unloadBodyTexture
} from './textures';

interface SystemBodyMeta extends SiblingBundles {
	tiers?: string[];
	/** Attribution block — matches `export/systems.py::texture_attribution`. */
	texture?: {
		source: string;
		organisation: string;
		license?: string;
		type: string;
		attribution?: string;
		description?: string;
		/** Only on `cylindrical_monthly`: number of monthly frames (always 12 today). */
		frames?: number;
	};
	orientation?: {
		pole_ra_0: number;
		pole_ra_1: number;
		pole_dec_0: number;
		pole_dec_1: number;
		w0: number;
		w1: number;
		w2: number;
	};
	/** Per-body IAU nutation/precession coefficients (paired with global angles). */
	nut_prec?: { ra: number[]; dec: number[]; pm: number[] };
	/** SPICE PCK triaxial radii (km) along body-fixed X, Y, Z (Z = spin axis). */
	radii?: { a: number; b: number; c: number };
	/** Ring bundles, inner → outer. Split per opacity range (Saturn has
	 *  three) since one 8-bit strip can't span six orders of magnitude. */
	rings?: RingMeta[];
}

/**
 * Fetch and apply system metadata (textures, orientation, rings) to every
 * body in the system, keyed by barycenter ID (naif-3, naif-5, …).
 */
export async function loadSystemData(
	barycenterId: string,
	bodyObjects: Map<string, BodyObjects>,
	scene: Scene,
	textureLoader: TextureLoader,
	currentJd: number,
	maxTextureSize: number,
	ctx?: ContextManager
): Promise<void> {
	let meta: Record<string, SystemBodyMeta>;
	try {
		const resp = await fetch(`${dataBase()}/v1/systems/${barycenterId}.json`);
		if (!resp.ok) return;
		meta = await resp.json();
	} catch {
		return;
	}

	const promises: Promise<void>[] = [];
	for (const [bodyId, bodyMeta] of Object.entries(meta)) {
		if (bodyMeta.texture)
			ctx?.credits.registerImagery('surface', bodyId, barycenterId, bodyMeta.texture);
		const bo = bodyObjects.get(bodyId);
		if (!bo?.mesh) continue;

		// Apply orientation (axial tilt + spin) and cache for per-frame re-application.
		if (bodyMeta.orientation) {
			applyBodyOrientation(bo, bodyMeta.orientation, ctx, barycenterId);

			// Join per-body nut/prec coefficients with the system-shared IAU angles.
			if (bodyMeta.nut_prec) {
				const naifMatch = bodyId.match(/^naif-(-?\d+)$/);
				const naifId = naifMatch ? parseInt(naifMatch[1], 10) : null;
				const angles = naifId !== null ? getNutPrecAngles(ownerIdFor(naifId)) : undefined;
				if (angles) {
					bo.body.nutPrec = { ...bodyMeta.nut_prec, angles };
				}
			}

			applyOrientation(bo.mesh, bodyMeta.orientation, currentJd, bo.body.nutPrec);
		}

		// Triaxial flattening: SPICE (X, Y, Z) maps to mesh local (X, Z, Y) per
		// applyOrientation's basis. Skipped when a DEM already carries the full
		// shape (Vesta, Ceres) to avoid double-counting it.
		if (
			bodyMeta.radii &&
			bo.radiusScene > 0 &&
			!bo.radiiApplied &&
			!bodyMeta.displacement?.absolute_radius
		) {
			applyRadiiToMesh(bo, bodyMeta.radii);
		}

		// Load the base tier once; per-frame LOD upgrades from there. Skip if
		// already loaded so repeat visits don't downgrade high → low.
		if (bodyMeta.tiers?.length) {
			bo.availableTiers = bodyMeta.tiers;
			bo.availableFrames = bodyMeta.texture?.frames;
			if (!bo.textureTier) {
				const frame = textureFrameForJd(currentJd, bo.availableFrames);
				promises.push(loadBodyTextureTier(bo, 'low', frame, textureLoader));
			}
		}

		// Specular, night lights, DEM relief and the cloud overlay.
		promises.push(
			...loadSiblingLayers(bodyId, barycenterId, bodyMeta, bo, { textureLoader, currentJd, ctx })
		);

		// Ring annuli, one node per bundle (Saturn has three).
		if (bodyMeta.rings?.length) {
			promises.push(
				...attachRingBundles(
					bodyId,
					barycenterId,
					bodyMeta.rings,
					bodyMeta.radii,
					bo,
					scene,
					maxTextureSize,
					ctx
				)
			);
		}
	}
	await Promise.allSettled(promises);
}

/**
 * Release GPU textures (and rings) for every body in `barycenterId`, keeping
 * geometry/mesh intact. Counterpart to {@link loadSystemData}, called on
 * leaving a system so it stops pinning high-tier textures on the GPU.
 */
export function unloadSystemTextures(
	barycenterId: string,
	bodyObjects: Map<string, BodyObjects>,
	scene: Scene,
	ctx: ContextManager
): void {
	for (const bo of bodyObjects.values()) {
		if (!ctx.visibility.isBodyInSystem(bo.body, barycenterId)) continue;
		unloadBodyTexture(bo);
		unloadSiblingLayers(bo);
		// A terrain window is ~100k vertices; drop back to the plain sphere on unload.
		if (bo.terrainWindow && bo.mesh) {
			bo.terrainWindow = null;
			const radius = kmToScene(effectiveRadiusKm(bo.body.data));
			const old = bo.mesh.geometry;
			bo.mesh.geometry = new SphereGeometry(radius, 24, 24);
			old.dispose();
			bo.currentSegments = 24;
		}
		for (const ring of bo.rings) {
			ring.planetShadow?.disable();
			scene.remove(ring.mesh);
			const idx = bo.extraObjects.indexOf(ring.mesh);
			if (idx >= 0) bo.extraObjects.splice(idx, 1);
			disposeRingNode(ring);
		}
		bo.rings = [];
		disposeNomenclatureLabels(bo);
	}
}
