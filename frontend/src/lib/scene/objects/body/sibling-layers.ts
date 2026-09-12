/**
 * The texture bundles a body ships beside its surface map. All four are
 * fetched, credited and released the same way, so each declares only what is
 * its own — the load/credit/unload path is written once here.
 */
import { type Mesh, type MeshStandardMaterial, type TextureLoader } from 'three';
import { isLowEndDevice } from '$lib/device';
import { kmToScene } from '$lib/math/units';
import { sceneSettings } from '$lib/scene/settings.svelte';
import type { ContextManager } from '$lib/scene/state/context-manager.svelte';
import type { BodyObjects, TextureBundleMeta } from '$lib/scene/types';
import {
	CLOUD_RADIUS_OFFSET,
	cloudFrameForJd,
	disposeCloudNode,
	loadCloudNode,
	type CloudMeta
} from '../surface/clouds';
import {
	attachDisplacementMap,
	disposeDisplacementFromMaterial,
	type DisplacementMeta
} from '../surface/displacement';
import { attachEclipseShadowToBody } from '../surface/eclipse-shadow';
import { attachNightLights, disposeNightLightsFromMaterial } from '../surface/night-lights';
import { attachSelfShadowToBody, detachSelfShadow } from '../surface/self-shadow';
import { attachSpecularMap, disposeSpecularFromMaterial } from '../surface/specular';
import { attachSunTransmittanceToBody } from '../surface/sun-transmittance';

/** Metadata each sibling layer carries, keyed by its credit layer. */
interface SiblingMetas {
	specular: TextureBundleMeta;
	night: TextureBundleMeta;
	topography: DisplacementMeta;
	clouds: CloudMeta;
}

/** The credited imagery layers served beside a body's surface texture. */
export type SiblingLayer = keyof SiblingMetas;

/** The sibling-bundle fields of a body's metadata — a system file entry, or a
 *  standalone body's global detail block. */
export interface SiblingBundles {
	clouds?: CloudMeta;
	specular?: TextureBundleMeta;
	night?: TextureBundleMeta;
	/** Credited as `topography`; the export keeps the file-level name. */
	displacement?: DisplacementMeta;
}

/** What a layer's load needs from the scene. */
export interface SiblingLoadEnv {
	textureLoader: TextureLoader;
	currentJd: number;
	ctx?: ContextManager;
}

interface LayerSpec<M extends TextureBundleMeta> {
	/** This layer's block, when the body ships it. */
	meta(bundles: SiblingBundles): M | undefined;
	/** Already attached — gates both the load and the unload. */
	loaded(bo: BodyObjects): boolean;
	/** Tested before the credit is registered, so a client that skips the load
	 *  is never credited for the layer. May log why it declined. */
	enabled?(bodyId: string): boolean;
	load(bo: BodyObjects, meta: M, mesh: Mesh, env: SiblingLoadEnv): Promise<void>;
	/** `mesh` is null on a body downgraded back to a halo; only the cloud node
	 *  still owns resources then. */
	unload(bo: BodyObjects, mesh: Mesh | null): void;
}

/** Record order is load order: the cheap single-frame masks before the DEM and
 *  the cloud sphere. */
const SIBLING_LAYERS: { [L in SiblingLayer]: LayerSpec<SiblingMetas[L]> } = {
	// Lowers roughness on ocean pixels.
	specular: {
		meta: (bundles) => bundles.specular,
		loaded: (bo) => bo.specularMap !== null,
		async load(bo, meta, mesh, env) {
			const tex = await attachSpecularMap(
				mesh.material as MeshStandardMaterial,
				meta,
				'low',
				env.textureLoader
			);
			if (!tex) return;
			if (bo.specularMap) {
				// A concurrent reload finished first — drop ours.
				tex.dispose();
				return;
			}
			bo.specularMap = tex;
		},
		unload(bo, mesh) {
			if (!mesh) return;
			disposeSpecularFromMaterial(mesh.material as MeshStandardMaterial);
			bo.specularMap = null;
		}
	},

	// City-light glow on the unlit hemisphere; reuses the eclipse-shadow sun
	// direction, so the eclipse patch must already be attached.
	night: {
		meta: (bundles) => bundles.night,
		loaded: (bo) => bo.emissiveMap !== null,
		async load(bo, meta, mesh, env) {
			const tex = await attachNightLights(
				mesh.material as MeshStandardMaterial,
				meta,
				'low',
				env.textureLoader
			);
			if (!tex) return;
			if (bo.emissiveMap) {
				tex.dispose();
				return;
			}
			bo.emissiveMap = tex;
		},
		unload(bo, mesh) {
			if (!mesh) return;
			disposeNightLightsFromMaterial(mesh.material as MeshStandardMaterial);
			bo.emissiveMap = null;
		}
	},

	// True-scale vertex relief, plus the self-shadow march over the same field.
	topography: {
		meta: (bundles) => bundles.displacement,
		loaded: (bo) => bo.displacementMap !== null,
		enabled(bodyId) {
			// The DEM is the heaviest per-body asset, so low-end clients keep the
			// flat sphere.
			if (isLowEndDevice()) {
				console.info(`Low-end device: skipping DEM relief for ${bodyId}`);
				return false;
			}
			return sceneSettings().showDisplacement;
		},
		async load(bo, meta, mesh, env) {
			const material = mesh.material as MeshStandardMaterial;
			const tex = await attachDisplacementMap(
				material,
				meta,
				'low',
				env.textureLoader,
				bo.radiusScene
			);
			if (!tex) return;
			if (bo.displacementMap) {
				tex.dispose();
				return;
			}
			bo.displacementMap = tex;
			bo.displacementMeta = meta;
			bo.displacementTier = 'low';
			// Debug: self-shadow off → relief without in-shader cast shadows.
			bo.selfShadow = sceneSettings().showSelfShadow
				? attachSelfShadowToBody(material, tex, kmToScene(meta.scale_km))
				: null;
		},
		unload(bo, mesh) {
			if (!mesh) return;
			disposeDisplacementFromMaterial(mesh.material as MeshStandardMaterial);
			bo.displacementMap = null;
			bo.displacementTier = undefined;
			detachSelfShadow(bo.selfShadow);
			bo.selfShadow = null;
		}
	},

	// A second sphere parented to the body's mesh rather than a map on its
	// material: the overlay carries its own frames, eclipse and sun tint.
	clouds: {
		meta: (bundles) => bundles.clouds,
		loaded: (bo) => bo.clouds !== null,
		async load(bo, meta, mesh, env) {
			const frame = cloudFrameForJd(env.currentJd, meta.frames, meta.coverage);
			// No exported snapshot yet — skip rather than park a frameless node.
			if (!frame) return;
			// A deck body's overlay is its shell's render level (Venus: the cloud
			// top, 65 km up) — the march floor, so no ray marches on behind it.
			// Its direct light still sees only the haze above the usual clearance:
			// the disc's tuned look, the sun dimming the deck under the whole
			// column would be a different one. Elsewhere the overlay keeps its
			// anti-z-fight clearance over the surface.
			const deckRatio = bo.atmosphere
				? bo.atmosphere.planetRadiusKm / bo.atmosphere.surfaceRadiusKm
				: 1;
			const cloudRatio = deckRatio > 1 ? deckRatio : CLOUD_RADIUS_OFFSET;
			const node = await loadCloudNode(mesh, bo.radiusScene, meta, frame, cloudRatio);
			if (!node) return;
			if (bo.clouds) {
				disposeCloudNode(node);
				return;
			}
			// The overlay shares the body's center, so it reuses the eclipse
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
							CLOUD_RADIUS_OFFSET * deckRatio
						)
					);
				}
			}
			bo.clouds = node;
		},
		unload(bo) {
			if (!bo.clouds) return;
			disposeCloudNode(bo.clouds);
			bo.clouds = null;
		}
	}
};

const LAYER_ORDER = Object.keys(SIBLING_LAYERS) as SiblingLayer[];

/**
 * Load one sibling bundle onto `bo`, or nothing — returning null — when the
 * body ships no such bundle, it is already loaded, the body has no mesh, or the
 * layer is switched off. The credit is registered only when the load starts.
 */
export function loadSiblingLayer<L extends SiblingLayer>(
	layer: L,
	bodyId: string,
	systemId: string,
	bundles: SiblingBundles,
	bo: BodyObjects,
	env: SiblingLoadEnv
): Promise<void> | null {
	const spec = SIBLING_LAYERS[layer];
	const meta = spec.meta(bundles);
	if (!meta || !bo.mesh || spec.loaded(bo)) return null;
	if (spec.enabled && !spec.enabled(bodyId)) return null;
	env.ctx?.credits.registerImagery(layer, bodyId, systemId, meta);
	return spec.load(bo, meta, bo.mesh, env);
}

/** Every sibling bundle `bundles` declares, as the loads it started. */
export function loadSiblingLayers(
	bodyId: string,
	systemId: string,
	bundles: SiblingBundles,
	bo: BodyObjects,
	env: SiblingLoadEnv
): Promise<void>[] {
	const started: Promise<void>[] = [];
	for (const layer of LAYER_ORDER) {
		const load = loadSiblingLayer(layer, bodyId, systemId, bundles, bo, env);
		if (load) started.push(load);
	}
	return started;
}

/** Release one sibling bundle, keeping the body's mesh and geometry. No-op when
 *  the layer isn't loaded. */
export function unloadSiblingLayer(layer: SiblingLayer, bo: BodyObjects): void {
	const spec = SIBLING_LAYERS[layer];
	if (spec.loaded(bo)) spec.unload(bo, bo.mesh);
}

/** Release every loaded sibling bundle. */
export function unloadSiblingLayers(bo: BodyObjects): void {
	for (const layer of LAYER_ORDER) unloadSiblingLayer(layer, bo);
}
