import { Color, type MeshStandardMaterial, type Texture, type TextureLoader } from 'three';
import { SRGBColorSpace } from 'three';
import { versionedUrl } from '$lib/fetch/data-base';
import { getEclipseSceneUniforms } from './eclipse-shadow';
import { chainShaderHook } from '$lib/scene/shaders/program-cache-key';
import type { TextureBundleMeta } from '$lib/scene/types';

/** Brightness multiplier on unlit-side emissive: Black Marble is bright enough that cities would read as a second lit hemisphere at 1.0. */
const NIGHT_INTENSITY = 0.2;
/**
 * Soft cutoff (`dot(outward, sunDir)`, negative = unlit) around the
 * terminator, biased onto the lit side so emission reaches full strength by
 * the time Lambert falloff kills the diffuse term — otherwise a black wedge
 * appears between them.
 */
const TERMINATOR_LOW = -0.125;
const TERMINATOR_HIGH = 0.1;

const NIGHT_HOOK = Symbol('night-lights-hook');

type PatchedMaterial = MeshStandardMaterial & { [NIGHT_HOOK]?: true };

/**
 * Load a body's night-lights map as an emissive map, gated by a shader patch
 * that multiplies emissive by an unlit-side factor (1 night, 0 day, smoothstep
 * at the terminator). Reuses eclipse-shadow's `uSunDir`, so
 * `attachEclipseShadowToBody` should run first. Idempotent: the hook installs
 * once per material; later calls just swap `emissiveMap`.
 */
export async function attachNightLights(
	material: MeshStandardMaterial,
	nightMeta: TextureBundleMeta,
	tier: string,
	textureLoader: TextureLoader
): Promise<Texture | null> {
	const url = versionedUrl(`/v1/textures/${nightMeta.id}/${tier}.webp`, 'textures');
	let texture: Texture;
	try {
		texture = await new Promise<Texture>((resolve, reject) => {
			textureLoader.load(url, resolve, undefined, reject);
		});
	} catch (err) {
		console.warn(`Failed to load night-lights map ${url}:`, err);
		return null;
	}
	texture.colorSpace = SRGBColorSpace;
	attachNightTexture(material, texture);
	return texture;
}

/**
 * Put an already-loaded map on the unlit side, installing the shader hook the
 * first time. Split out from the loader so a host's own picture goes on the
 * same way the export's does.
 */
export function attachNightTexture(material: MeshStandardMaterial, texture: Texture): void {
	material.emissiveMap = texture;
	// White so totalEmissiveRadiance passes the raw texture colour unchanged.
	material.emissive = new Color(0xffffff);

	const patched = material as PatchedMaterial;
	if (!patched[NIGHT_HOOK]) {
		patched[NIGHT_HOOK] = true;
		const sunUniforms = getEclipseSceneUniforms();
		chainShaderHook(material, 'nightLights', (shader) => {
			// Shared uSunDir reference keeps a single source of truth for the sun direction.
			shader.uniforms.uSunDir = sunUniforms.uSunDir;
			shader.uniforms.uNightIntensity = { value: NIGHT_INTENSITY };

			// World-space outward direction: unit-sphere `position` is already
			// outward; mat3(modelMatrix) carries rotation + scale to world space.
			shader.vertexShader = shader.vertexShader
				.replace('#include <common>', '#include <common>\nvarying vec3 vNightOutwardWorld;')
				.replace(
					'#include <begin_vertex>',
					'#include <begin_vertex>\nvNightOutwardWorld = mat3(modelMatrix) * position;'
				);

			shader.fragmentShader = shader.fragmentShader
				.replace(
					'#include <common>',
					// uSunDir is declared by the chained eclipse-shadow hook; redeclaring fails compilation.
					`#include <common>
					uniform float uNightIntensity;
					varying vec3 vNightOutwardWorld;`
				)
				.replace(
					'#include <emissivemap_fragment>',
					`#include <emissivemap_fragment>
					#ifdef USE_EMISSIVEMAP
						// Modulate by unlit-side factor: 1 night, 0 day.
						vec3 nightOutward = normalize(vNightOutwardWorld);
						float nightDot = dot(nightOutward, uSunDir);
						float nightFactor = 1.0 - smoothstep(${TERMINATOR_LOW.toFixed(2)}, ${TERMINATOR_HIGH.toFixed(2)}, nightDot);
						totalEmissiveRadiance *= nightFactor * uNightIntensity;
					#endif`
				);
		});
	}
	material.needsUpdate = true;
}

/**
 * Release the night-lights texture and unset the emissive map. The shader
 * hook stays: gated on `USE_EMISSIVEMAP`, which three.js drops once
 * `emissiveMap` is null, so the patched chunk becomes a no-op.
 */
export function disposeNightLightsFromMaterial(material: MeshStandardMaterial): void {
	if (!material.emissiveMap) return;
	material.emissiveMap.dispose();
	material.emissiveMap = null;
	material.emissive.setRGB(0, 0, 0);
	material.needsUpdate = true;
}
