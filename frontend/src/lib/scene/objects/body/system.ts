import { type Material, MeshStandardMaterial, type Scene, type TextureLoader } from 'three';
import { kmToScene } from '$lib/math/units';
import { applyOrientation } from '$lib/math/orientation';
import { getNutPrecAngles, ownerIdFor } from '$lib/fetch/systems-global';
import { DATA_BASE } from '$lib/fetch/data-base';
import type { ContextManager } from '$lib/scene/state/context-manager.svelte';
import { attachEclipseShadowToBody } from '../surface/eclipse-shadow';
import {
	attachRingShadowToPlanet,
	disposeRingNode,
	loadRingNode,
	type RingMeta
} from '../surface/rings';
import {
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
import type { BodyObjects } from '../../types';
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
	/**
	 * Planetary ring profile bundle — present only on bodies whose ingest
	 * produced one (e.g. Saturn). The renderer composes per-channel URLs as
	 * `/v1/rings/{body_id}/{channels[name]}`.
	 */
	rings?: RingMeta;
	/**
	 * Cloud-overlay bundle — present only on bodies whose ingest produced one
	 * (Earth today). The renderer composes per-tier URLs as
	 * `/v1/textures/{clouds.id}/{tier}.webp` (id ends in `_clouds`).
	 */
	clouds?: CloudMeta;
	/**
	 * Specular/roughness-map sibling bundle — present only on bodies whose
	 * ingest produced one (Earth today). Single-frame; the renderer composes
	 * URLs as `/v1/textures/{specular.id}/{tier}.webp` (id ends in `_specular`).
	 */
	specular?: SpecularMeta;
	/**
	 * Night-lights emissive sibling bundle — present only on bodies whose
	 * ingest produced one (Earth today). Single-frame; the renderer composes
	 * URLs as `/v1/textures/{night.id}/{tier}.webp` (id ends in `_night`).
	 */
	night?: NightMeta;
}

/**
 * Fetch system metadata (textures + orientation + rings) and apply to all
 * bodies in that system. The metadata file is keyed by barycenter ID
 * (e.g. naif-3, naif-5).
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
		const resp = await fetch(`${DATA_BASE}/v1/systems/${barycenterId}.json`);
		if (!resp.ok) return;
		meta = await resp.json();
	} catch {
		return;
	}

	const promises: Promise<void>[] = [];
	for (const [bodyId, bodyMeta] of Object.entries(meta)) {
		if (ctx && bodyMeta.texture) {
			ctx.credits.registerTexture({
				bodyId,
				systemId: barycenterId,
				source: bodyMeta.texture.source,
				organisation: bodyMeta.texture.organisation,
				type: bodyMeta.texture.type,
				attribution: bodyMeta.texture.attribution,
				description: bodyMeta.texture.description
			});
		}
		const bo = bodyObjects.get(bodyId);
		if (!bo?.mesh) continue;

		// Apply orientation (axial tilt + spin) and cache for per-frame re-application.
		if (bodyMeta.orientation) {
			bo.body.orientation = bodyMeta.orientation;

			// Resolve per-body nutation/precession by joining coefficients with the
			// system-shared angles (one IAU table per planetary system).
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

		// Apply triaxial flattening. applyOrientation puts the body's pole on
		// local +Y and the ascending node on local +X, so SPICE (X, Y, Z)
		// maps to mesh local (X, Z, Y).
		if (bodyMeta.radii && bo.radiusScene > 0 && !bo.radiiApplied) {
			applyRadiiToMesh(bo, bodyMeta.radii);
		}

		// Record available tiers and load the base `low` tier if no texture is
		// loaded yet. Higher tiers are loaded on-demand by the per-frame LOD
		// update based on screen size. Skip if a tier is already loaded to avoid
		// downgrading (e.g. high → low → re-upgrade) on repeated system visits.
		if (bodyMeta.tiers?.length) {
			bo.availableTiers = bodyMeta.tiers;
			bo.availableFrames = bodyMeta.texture?.frames;
			if (!bo.textureTier) {
				const frame = textureFrameForJd(currentJd, bo.availableFrames);
				promises.push(loadBodyTextureTier(bo, 'low', frame, textureLoader));
			}
		}

		// Specular/roughness sibling — patches the body's material so ocean
		// pixels lower roughness while land keeps the base value. Idempotent
		// on the hook side; we still gate the texture load on `bo.specularMap`
		// to avoid refetching on every system reload.
		if (bodyMeta.specular && !bo.specularMap && bo.mesh) {
			const specMeta = bodyMeta.specular;
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

		// Night-lights emissive sibling — patches the body's material so the
		// unlit hemisphere glows with city lights. Same idempotent pattern
		// as the specular branch; the shader hook reuses the eclipse-shadow
		// scene uniforms for the sun direction.
		if (bodyMeta.night && !bo.emissiveMap && bo.mesh) {
			const nightMeta = bodyMeta.night;
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

		// Cloud overlay — second sphere parented to the body's mesh, lit by the
		// same scene lights. Idempotent: re-entering with `bo.clouds` set skips.
		if (bodyMeta.clouds && !bo.clouds && bo.mesh) {
			if (ctx) {
				ctx.credits.registerCloud({
					bodyId,
					systemId: barycenterId,
					source: bodyMeta.clouds.source,
					organisation: bodyMeta.clouds.organisation,
					attribution: bodyMeta.clouds.attribution,
					description: bodyMeta.clouds.description
				});
			}
			const cloudMeta = bodyMeta.clouds;
			const parentMesh = bo.mesh;
			const initialFrame = cloudFrameForJd(currentJd, cloudMeta.frames);
			if (!initialFrame) {
				// No snapshots exported for this body yet — skip the load
				// entirely so the renderer doesn't park a frameless node.
				continue;
			}
			promises.push(
				loadCloudNode(parentMesh, bo.radiusScene, cloudMeta, initialFrame).then((node) => {
					if (!node) return;
					if (bo.clouds) {
						// A concurrent system reload finished first — drop ours.
						node.mesh.geometry.dispose();
						node.material.map?.dispose();
						node.material.dispose();
						parentMesh.remove(node.mesh);
						return;
					}
					// Cloud sits at the same center as the body, so the eclipse
					// self-skip uniform can be shared — that also avoids a second
					// per-frame write in the renderer.
					if (bo.eclipseShadow) {
						attachEclipseShadowToBody(node.material, bo.eclipseShadow);
					}
					bo.clouds = node;
				})
			);
		}

		// Ring annulus — only present for ringed bodies (Saturn today). Idempotent:
		// re-entering the system with `bo.rings` already set is a no-op.
		if (bodyMeta.rings && !bo.rings) {
			if (ctx) {
				ctx.credits.registerRing({
					bodyId,
					systemId: barycenterId,
					source: bodyMeta.rings.source,
					organisation: bodyMeta.rings.organisation,
					attribution: bodyMeta.rings.attribution,
					description: bodyMeta.rings.description
				});
			}
			const ringMeta = bodyMeta.rings;
			promises.push(
				loadRingNode(bodyId, ringMeta, maxTextureSize).then((node) => {
					if (!node) return;
					if (bo.rings) {
						// A concurrent system reload finished first — drop ours.
						node.mesh.geometry.dispose();
						(node.mesh.material as Material).dispose();
						return;
					}
					bo.rings = node;
					scene.add(node.mesh);
					bo.extraObjects.push(node.mesh);
					// Analytical ring shadow on the planet itself. The planet
					// material is built as a MeshStandardMaterial in
					// `buildMajorBodies`; this swaps in an onBeforeCompile that
					// adds a ray-march to the ring plane after the standard
					// lighting calc.
					if (bo.mesh) {
						node.planetShadow = attachRingShadowToPlanet(
							bo.mesh.material as MeshStandardMaterial,
							node.innerScene,
							node.outerScene,
							node.transparency
						);
					}
					// Reverse direction: configure the ring's own analytical
					// planet-shadow with the planet's oblate-spheroid extent.
					// Saturn is essentially biaxial (a ≈ b), so collapsing the
					// two equatorial axes to their mean is exact enough for the
					// limb of the cast shadow.
					if (bodyMeta.radii) {
						const { a, b, c } = bodyMeta.radii;
						node.planetShadowOnRing.uPlanetEquatorialScene.value = kmToScene((a + b) / 2);
						node.planetShadowOnRing.uPlanetPolarScene.value = kmToScene(c);
					}
				})
			);
		}
	}
	await Promise.allSettled(promises);
}

/**
 * Drop GPU textures (and ring nodes) for every body that belongs to
 * `barycenterId`. Geometry, materials, and meshes stay in place so the bodies
 * still render — only textures are released. Counterpart to
 * {@link loadSystemData}; called when the user navigates away from a system
 * so unfocused systems don't keep their high-tier textures pinned on the GPU.
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
		const ring = bo.rings;
		if (ring) {
			ring.planetShadow?.detach();
			scene.remove(ring.mesh);
			const idx = bo.extraObjects.indexOf(ring.mesh);
			if (idx >= 0) bo.extraObjects.splice(idx, 1);
			disposeRingNode(ring);
			bo.rings = null;
		}
		const cloud = bo.clouds;
		if (cloud) {
			disposeCloudNode(cloud);
			bo.clouds = null;
		}
	}
}
