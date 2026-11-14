import { type MeshStandardMaterial, type Texture, type TextureLoader } from 'three';
import { versionedUrl } from '$lib/fetch/data-base';
import { chainShaderHook } from '$lib/scene/shaders/program-cache-key';
import type { TextureBundleMeta } from '$lib/scene/types';
import { MAX_ANISOTROPY } from './anisotropy';

/**
 * Roughness target over open water.
 * Physically realistic open water is ~0.2–0.4; tuned rougher to keep the sun glint from dominating the view.
 */
const OCEAN_ROUGHNESS = 0.55;

const SPECULAR_HOOK = Symbol('specular-hook');

type PatchedMaterial = MeshStandardMaterial & { [SPECULAR_HOOK]?: true };

/**
 * Load a body's specular mask as a roughness map, with a shader patch that
 * inverts the sampled value: white (water) lowers roughness, black (land)
 * keeps base roughness. Chains onto `onBeforeCompile` so eclipse/ring-shadow
 * patches keep working. Idempotent: the hook installs at most once per
 * material; later calls just swap the texture.
 */
export async function attachSpecularMap(
	material: MeshStandardMaterial,
	specMeta: TextureBundleMeta,
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

	texture.anisotropy = MAX_ANISOTROPY;
	material.roughnessMap = texture;

	const patched = material as PatchedMaterial;
	if (!patched[SPECULAR_HOOK]) {
		patched[SPECULAR_HOOK] = true;
		chainShaderHook(material, 'specular', (shader) => {
			shader.uniforms.uOceanRoughness = { value: OCEAN_ROUGHNESS };
			shader.fragmentShader = shader.fragmentShader
				.replace('#include <common>', '#include <common>\nuniform float uOceanRoughness;')
				.replace(
					'#include <roughnessmap_fragment>',
					`float roughnessFactor = roughness;
					#ifdef USE_ROUGHNESSMAP
						// The fraction of the texel under water. Surface tiles give a
						// finer one where they cover the fragment.
						vec4 texelRoughness = texture2D(roughnessMap, vRoughnessMapUv);
						#ifdef SURFACE_TILES
							texelRoughness.g = tileWaterOver(texelRoughness.g);
						#endif
						roughnessFactor = mix(roughness, uOceanRoughness, texelRoughness.g);
					#endif`
				);
		});
	}
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
