import { type MeshStandardMaterial, type Texture, type TextureLoader } from 'three';
import { versionedUrl } from '$lib/fetch/data-base';
import { tagShaderModifier } from '$lib/scene/shaders/program-cache-key';

/** Per-body specular-map metadata: single-frame sibling of the surface texture, served from `{specular.id}/{tier}.webp`. */
export interface SpecularMeta {
	id: string;
	tiers: string[];
	source: string;
	organisation: string;
	type: string;
	attribution?: string;
	description?: string;
}

/**
 * Roughness target over open water (mask is binary: land=0, ocean=255).
 * Physically realistic open water is ~0.2–0.4; tuned rougher to keep the sun glint from dominating the view.
 */
const OCEAN_ROUGHNESS = 0.55;

const SPECULAR_HOOK = Symbol('specular-hook');

type PatchedMaterial = MeshStandardMaterial & { [SPECULAR_HOOK]?: true };

/**
 * Load a body's specular mask as a roughness map, with a shader patch that
 * inverts the sampled value: white (ocean) lowers roughness, black (land)
 * keeps base roughness. Chains onto `onBeforeCompile` so eclipse/ring-shadow
 * patches keep working. Idempotent: the hook installs at most once per
 * material; later calls just swap the texture.
 */
export async function attachSpecularMap(
	material: MeshStandardMaterial,
	specMeta: SpecularMeta,
	tier: string,
	textureLoader: TextureLoader
): Promise<Texture | null> {
	const url = versionedUrl(`/v1/textures/${specMeta.id}/${tier}.webp`, 'textures');
	let texture: Texture;
	try {
		texture = await new Promise<Texture>((resolve, reject) => {
			textureLoader.load(url, resolve, undefined, reject);
		});
	} catch (err) {
		console.warn(`Failed to load specular map ${url}:`, err);
		return null;
	}

	material.roughnessMap = texture;

	const patched = material as PatchedMaterial;
	if (!patched[SPECULAR_HOOK]) {
		patched[SPECULAR_HOOK] = true;
		const prev = material.onBeforeCompile;
		material.onBeforeCompile = (shader, renderer) => {
			prev?.(shader, renderer);
			shader.uniforms.uOceanRoughness = { value: OCEAN_ROUGHNESS };
			shader.fragmentShader = shader.fragmentShader
				.replace('#include <common>', '#include <common>\nuniform float uOceanRoughness;')
				.replace(
					'#include <roughnessmap_fragment>',
					`float roughnessFactor = roughness;
					#ifdef USE_ROUGHNESSMAP
						// Mask: ocean=1.0, land=0.0. Green channel matches three.js' default roughnessmap sample.
						vec4 texelRoughness = texture2D(roughnessMap, vRoughnessMapUv);
						roughnessFactor = mix(roughness, uOceanRoughness, texelRoughness.g);
					#endif`
				);
		};
	}
	tagShaderModifier(material, 'specular');
	material.needsUpdate = true;
	return texture;
}

/**
 * Release the specular texture and unset the roughness map. The shader hook
 * stays: gated on `USE_ROUGHNESSMAP`, which three.js drops once
 * `roughnessMap` is null, so the patched chunk becomes a no-op.
 */
export function disposeSpecularFromMaterial(material: MeshStandardMaterial): void {
	if (!material.roughnessMap) return;
	material.roughnessMap.dispose();
	material.roughnessMap = null;
	material.needsUpdate = true;
}
