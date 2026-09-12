import { MeshStandardMaterial, type Scene, SphereGeometry, type TextureLoader } from 'three';
import { kmToScene } from '$lib/math/units';
import { effectiveRadiusKm } from '$lib/types/objects';
import { isLowEndDevice } from '$lib/device';
import { applyOrientation } from '$lib/math/orientation';
import { getNutPrecAngles, ownerIdFor } from '$lib/fetch/systems-global';
import { dataBase } from '$lib/fetch/data-base';
import type { ContextManager } from '$lib/scene/state/context-manager.svelte';
import { attachEclipseShadowToBody } from '../surface/eclipse-shadow';
import { attachSunTransmittanceToBody } from '../surface/sun-transmittance';
import { disposeRingNode, type RingMeta } from '../surface/rings';
import { attachRingBundles } from '../surface/ring-attach';
import {
	CLOUD_RADIUS_OFFSET,
	cloudFrameForJd,
	disposeCloudNode,
	loadCloudNode,
	type CloudMeta
} from '../surface/clouds';
import {
	attachSpecularMap,
	disposeSpecularFromMaterial,
	type SpecularMeta
} from '../surface/specular';
import {
	attachNightLights,
	disposeNightLightsFromMaterial,
	type NightMeta
} from '../surface/night-lights';
import {
	attachDisplacementMap,
	disposeDisplacementFromMaterial,
	type DisplacementMeta
} from '../surface/displacement';
import { attachSelfShadowToBody, detachSelfShadow } from '../surface/self-shadow';
import { disposeNomenclatureLabels } from '../surface/nomenclature';
import type { BodyObjects } from '../../types';
import { applyBodyOrientation } from './orientation-apply';
import {
	applyRadiiToMesh,
	loadBodyTextureTier,
	textureFrameForJd,
	unloadBodyTexture
} from './textures';

interface SystemBodyMeta {
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
	/** Cloud-overlay bundle (Earth today). URLs: `/v1/textures/{clouds.id}/{tier}.webp`. */
	clouds?: CloudMeta;
	/** Specular/roughness sibling bundle (Earth today), single-frame.
	 *  URLs: `/v1/textures/{specular.id}/{tier}.webp`. */
	specular?: SpecularMeta;
	/** Night-lights emissive sibling bundle (Earth today), single-frame.
	 *  URLs: `/v1/textures/{night.id}/{tier}.webp`. */
	night?: NightMeta;
	/** Displacement/height sibling bundle (the Moon, planet DEMs), single-frame.
	 *  URLs: `/v1/textures/{displacement.id}/{tier}.webp`. */
	displacement?: DisplacementMeta;
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

		// Specular sibling: lowers roughness on ocean pixels. Gated on
		// `bo.specularMap` so reloads don't refetch.
		if (bodyMeta.specular && !bo.specularMap && bo.mesh) {
			const specMeta = bodyMeta.specular;
			ctx?.credits.registerImagery('specular', bodyId, barycenterId, specMeta);
			const material = bo.mesh.material as MeshStandardMaterial;
			promises.push(
				attachSpecularMap(material, specMeta, 'low', textureLoader).then((tex) => {
					if (!tex) return;
					if (bo.specularMap) {
						// A concurrent reload finished first — drop ours.
						tex.dispose();
						return;
					}
					bo.specularMap = tex;
				})
			);
		}

		// Night-lights sibling: city-light glow on the unlit hemisphere.
		// Reuses the eclipse-shadow uniforms for sun direction.
		if (bodyMeta.night && !bo.emissiveMap && bo.mesh) {
			const nightMeta = bodyMeta.night;
			ctx?.credits.registerImagery('night', bodyId, barycenterId, nightMeta);
			const material = bo.mesh.material as MeshStandardMaterial;
			promises.push(
				attachNightLights(material, nightMeta, 'low', textureLoader).then((tex) => {
					if (!tex) return;
					if (bo.emissiveMap) {
						tex.dispose();
						return;
					}
					bo.emissiveMap = tex;
				})
			);
		}

		// Displacement sibling drives true-scale vertex relief. The DEM is the
		// heaviest per-body asset, so low-end clients keep the flat sphere
		// (mirrors the standalone branch in textures.ts).
		if (bodyMeta.displacement && !bo.displacementMap && bo.mesh && isLowEndDevice()) {
			console.info(`Low-end device: skipping DEM relief for ${bodyId}`);
		} else if (bodyMeta.displacement && !bo.displacementMap && bo.mesh) {
			const dispMeta = bodyMeta.displacement;
			ctx?.credits.registerImagery('topography', bodyId, barycenterId, dispMeta);
			const material = bo.mesh.material as MeshStandardMaterial;
			promises.push(
				attachDisplacementMap(material, dispMeta, 'low', textureLoader, bo.radiusScene).then(
					(tex) => {
						if (!tex) return;
						if (bo.displacementMap) {
							// A concurrent reload finished first — drop ours.
							tex.dispose();
							return;
						}
						bo.displacementMap = tex;
						bo.displacementMeta = dispMeta;
						bo.displacementTier = 'low';
						// Self-shadow + relief shading march the same height field.
						bo.selfShadow = attachSelfShadowToBody(material, tex, kmToScene(dispMeta.scale_km));
					}
				)
			);
		}

		// Cloud overlay: second sphere parented to the body's mesh. Idempotent via `bo.clouds`.
		if (bodyMeta.clouds && !bo.clouds && bo.mesh) {
			ctx?.credits.registerImagery('clouds', bodyId, barycenterId, bodyMeta.clouds);
			const cloudMeta = bodyMeta.clouds;
			const parentMesh = bo.mesh;
			const initialFrame = cloudFrameForJd(currentJd, cloudMeta.frames, cloudMeta.coverage);
			if (!initialFrame) {
				// No exported snapshot yet — skip rather than park a frameless node.
				continue;
			}
			// A deck body's overlay is its shell's render level (Venus: the cloud
			// top, 65 km up) — the march floor, so no ray marches on behind it.
			// Its direct light still sees only the haze above the usual
			// clearance: the disc's tuned look, the sun dimming the deck under
			// the whole column would be a different one. Elsewhere the overlay
			// keeps its anti-z-fight clearance over the surface.
			const deckRatio = bo.atmosphere
				? bo.atmosphere.planetRadiusKm / bo.atmosphere.surfaceRadiusKm
				: 1;
			const cloudRatio = deckRatio > 1 ? deckRatio : CLOUD_RADIUS_OFFSET;
			const cloudTintRatio = CLOUD_RADIUS_OFFSET * deckRatio;
			promises.push(
				loadCloudNode(parentMesh, bo.radiusScene, cloudMeta, initialFrame, cloudRatio).then(
					(node) => {
						if (!node) return;
						if (bo.clouds) {
							// A concurrent system reload finished first — drop ours.
							node.mesh.geometry.dispose();
							node.material.map?.dispose();
							node.material.dispose();
							parentMesh.remove(node.mesh);
							return;
						}
						// Cloud shares the body's center, so it reuses the eclipse
						// self-skip uniform instead of a second per-frame write.
						if (bo.eclipseShadow) {
							attachEclipseShadowToBody(node.material, bo.eclipseShadow);
							if (bo.atmosphere) {
								(bo.sunTint ??= []).push(
									attachSunTransmittanceToBody(
										node.material,
										bo.atmosphere.params,
										bo.radiusScene,
										bo.atmosphere.surfaceRadiusKm,
										bo.eclipseShadow,
										bo.atmosphere,
										cloudTintRatio
									)
								);
							}
						}
						bo.clouds = node;
					}
				)
			);
		}

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
		if (bo.specularMap && bo.mesh) {
			disposeSpecularFromMaterial(bo.mesh.material as MeshStandardMaterial);
			bo.specularMap = null;
		}
		if (bo.emissiveMap && bo.mesh) {
			disposeNightLightsFromMaterial(bo.mesh.material as MeshStandardMaterial);
			bo.emissiveMap = null;
		}
		if (bo.displacementMap && bo.mesh) {
			disposeDisplacementFromMaterial(bo.mesh.material as MeshStandardMaterial);
			bo.displacementMap = null;
			bo.displacementTier = undefined;
			detachSelfShadow(bo.selfShadow);
			bo.selfShadow = null;
		}
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
		const cloud = bo.clouds;
		if (cloud) {
			disposeCloudNode(cloud);
			bo.clouds = null;
		}
		disposeNomenclatureLabels(bo);
	}
}
