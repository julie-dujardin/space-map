import { type MeshStandardMaterial, type Texture, type TextureLoader } from 'three';
import { versionedUrl } from '$lib/fetch/data-base';
import { tagShaderModifier } from '$lib/scene/shaders/program-cache-key';

/**
 * Per-body specular-map metadata block from `systems/{bary}.json`. Mirrors
 * the shape emitted by `export/systems.py::specular_block` — single-frame
 * sibling of the surface texture, served from `{specular.id}/{tier}.webp`.
 */
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
 * Roughness target over open water. The mask is binary today (land=0,
 * ocean=255), so the value here is what the ocean lerps to. Land retains
 * `material.roughness` (1.0 by default), which keeps continents
 * indistinguishable from before the specular map was attached. Physically
 * realistic open-water values sit around ~0.2–0.4, but we use a much
 * rougher tuning to keep the sun glint from dominating the view.
 */
const OCEAN_ROUGHNESS = 0.55;

const SPECULAR_HOOK = Symbol('specular-hook');

type PatchedMaterial = MeshStandardMaterial & { [SPECULAR_HOOK]?: true };

/**
 * Load a body's specular mask and attach it to a `MeshStandardMaterial` as
 * a roughness map, with a shader patch that inverts the sampled value so a
 * white pixel (ocean) lowers roughness and a black pixel (land) keeps the
 * base roughness. The hook chains the existing `onBeforeCompile` so
 * eclipse/ring-shadow patches keep working on top.
 *
 * Idempotent on the hook side: the patch is installed at most once per
 * material, tracked via a Symbol property. Subsequent calls swap the
 * `roughnessMap` texture in place without stacking another hook.
 *
 * Returns the loaded texture so the caller can store it on the body for
 * later disposal, or `null` on fetch failure.
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
						// Mask convention: ocean = 1.0 (high specular intensity),
						// land = 0.0. Blend from material.roughness over land
						// toward uOceanRoughness over open water — the green
						// channel matches three.js' default roughnessmap sample.
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
 * Release the loaded specular texture and unset the material's roughness
 * map. The shader hook is left in place — it's gated on `USE_ROUGHNESSMAP`,
 * which three.js drops from the recompiled defines when `roughnessMap` is
 * null, so the patched chunk becomes a no-op until the next attach.
 */
export function disposeSpecularFromMaterial(material: MeshStandardMaterial): void {
	if (!material.roughnessMap) return;
	material.roughnessMap.dispose();
	material.roughnessMap = null;
	material.needsUpdate = true;
}
