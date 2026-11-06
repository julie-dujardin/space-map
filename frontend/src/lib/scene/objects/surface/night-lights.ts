import {
	Color,
	SRGBColorSpace,
	type MeshStandardMaterial,
	type Texture,
	type TextureLoader
} from 'three';
import { versionedUrl } from '$lib/fetch/data-base';
import { MAX_ANISOTROPY } from './anisotropy';
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

/** The material's night gate: 1 masks the emissive map to the unlit side. */
type PatchedMaterial = MeshStandardMaterial & { [NIGHT_HOOK]?: { value: number } };

/**
 * The layers that draw on a material's emissive map, one at a time. Night
 * lights show on the unlit side only. A glow shows on both sides at full
 * strength.
 */
export type EmissiveLayer = 'night' | 'glow';

/** Load an emissive bundle's map at `tier`. Null when it fails to load. */
export async function loadEmissiveTexture(
	meta: TextureBundleMeta,
	tier: string,
	textureLoader: TextureLoader
): Promise<Texture | null> {
	const url = versionedUrl(`/v1/textures/${meta.id}/${tier}.webp`, 'textures');
	try {
		const texture = await textureLoader.loadAsync(url);
		texture.colorSpace = SRGBColorSpace;
		return texture;
	} catch (err) {
		console.warn(`Failed to load emissive map ${url}:`, err);
		return null;
	}
}

/**
 * Put a loaded map on the material's emissive slot as `layer`. Night lights
 * install the unlit-side shader hook once per material; the hook reuses
 * eclipse-shadow's `uSunDir`, so `attachEclipseShadowToBody` must run first.
 * A glow turns the gate of an installed hook off.
 */
export function attachEmissiveTexture(
	material: MeshStandardMaterial,
	texture: Texture,
	layer: EmissiveLayer
): void {
	texture.anisotropy = MAX_ANISOTROPY;
	material.emissiveMap = texture;
	// White so totalEmissiveRadiance passes the raw texture colour unchanged.
	material.emissive = new Color(0xffffff);
	const patched = material as PatchedMaterial;
	if (layer === 'night' && !patched[NIGHT_HOOK]) installNightHook(patched);
	const gate = patched[NIGHT_HOOK];
	if (gate) gate.value = layer === 'night' ? 1 : 0;
	material.needsUpdate = true;
}

/**
 * Unset the emissive map. The texture is the caller's to dispose. The shader
 * hook stays: three.js drops `USE_EMISSIVEMAP` once the map is null, so the
 * patched chunk is a no-op.
 */
export function detachEmissiveTexture(material: MeshStandardMaterial): void {
	if (!material.emissiveMap) return;
	material.emissiveMap = null;
	material.emissive.setRGB(0, 0, 0);
	material.needsUpdate = true;
}

function installNightHook(material: PatchedMaterial): void {
	const gate = { value: 1 };
	material[NIGHT_HOOK] = gate;
	const sunUniforms = getEclipseSceneUniforms();
	chainShaderHook(material, 'nightLights', (shader) => {
		// Shared uSunDir reference keeps a single source of truth for the sun direction.
		shader.uniforms.uSunDir = sunUniforms.uSunDir;
		shader.uniforms.uNightIntensity = { value: NIGHT_INTENSITY };
		shader.uniforms.uNightGate = gate;

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
				uniform float uNightGate;
				varying vec3 vNightOutwardWorld;`
			)
			.replace(
				'#include <emissivemap_fragment>',
				`#include <emissivemap_fragment>
				#ifdef USE_EMISSIVEMAP
					// Modulate by unlit-side factor: 1 night, 0 day. A glow has the gate off.
					vec3 nightOutward = normalize(vNightOutwardWorld);
					float nightDot = dot(nightOutward, uSunDir);
					float nightFactor = 1.0 - smoothstep(${TERMINATOR_LOW.toFixed(2)}, ${TERMINATOR_HIGH.toFixed(2)}, nightDot);
					totalEmissiveRadiance *= mix(1.0, nightFactor * uNightIntensity, uNightGate);
				#endif`
			);
	});
}
