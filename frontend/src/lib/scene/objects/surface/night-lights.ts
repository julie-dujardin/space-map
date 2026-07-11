import { Color, type MeshStandardMaterial, type Texture, type TextureLoader } from 'three';
import { SRGBColorSpace } from 'three';
import { versionedUrl } from '$lib/fetch/data-base';
import { getEclipseSceneUniforms } from './eclipse-shadow';

/**
 * Per-body night-lights metadata block from `systems/{bary}.json`. Mirrors
 * `export/systems.py::night_block` — single-frame emissive sibling of the
 * surface texture, served from `{night.id}/{tier}.webp`.
 */
export interface NightMeta {
	id: string;
	tiers: string[];
	source: string;
	organisation: string;
	license?: string;
	type: string;
	attribution?: string;
	description?: string;
}

/**
 * Brightness multiplier on the unlit-side emissive contribution. The
 * Black Marble composite is already pretty bright; trim it down so cities
 * don't read as a second illuminated hemisphere.
 */
const NIGHT_INTENSITY = 0.2;
/**
 * Soft cutoff (in `dot(outward, sunDir)`) around the terminator. Negative
 * dot is the unlit side; positive is the lit side. The band is biased
 * heavily onto the lit side so emission has nearly reached full strength
 * by the time `cos θ` Lambert falloff has driven the diffuse contribution
 * to zero (around `dotNL ≈ 0`). Without that bias the diffuse term goes
 * dark before the emissive term lights up, leaving a black wedge at the
 * terminator.
 */
const TERMINATOR_LOW = -0.125;
const TERMINATOR_HIGH = 0.1;

const NIGHT_HOOK = Symbol('night-lights-hook');

type PatchedMaterial = MeshStandardMaterial & { [NIGHT_HOOK]?: true };

/**
 * Load a body's night-lights map and attach it to a `MeshStandardMaterial`
 * as an emissive map, gated by a shader patch that multiplies the emissive
 * contribution by an unlit-side factor (1 on the night side, 0 on the day
 * side, with a smoothstep around the terminator).
 *
 * Reuses the eclipse-shadow scene uniforms for `uSunDir`; that means
 * `attachEclipseShadowToBody` should run on the same material first (true
 * for every system body today). Idempotent: the hook is installed at most
 * once per material; subsequent calls swap `emissiveMap` in place.
 *
 * Returns the loaded texture (caller stores it on the body for later
 * disposal), or `null` on fetch failure.
 */
export async function attachNightLights(
	material: MeshStandardMaterial,
	nightMeta: NightMeta,
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

	material.emissiveMap = texture;
	// `totalEmissiveRadiance` starts from `material.emissive` and is then
	// multiplied by the sampled emissive map, so white pushes through the
	// raw texture colour unchanged.
	material.emissive = new Color(0xffffff);

	const patched = material as PatchedMaterial;
	if (!patched[NIGHT_HOOK]) {
		patched[NIGHT_HOOK] = true;
		const sunUniforms = getEclipseSceneUniforms();
		const prev = material.onBeforeCompile;
		material.onBeforeCompile = (shader, renderer) => {
			prev?.(shader, renderer);
			// Pin the shared uSunDir reference — eclipse-shadow does the same
			// for its uniforms, so chaining keeps a single source of truth
			// for the sun direction.
			shader.uniforms.uSunDir = sunUniforms.uSunDir;
			shader.uniforms.uNightIntensity = { value: NIGHT_INTENSITY };

			// World-space radial direction at the surface point. On the unit
			// sphere `position` is the outward direction; `mat3(modelMatrix)`
			// carries the rotation + (non-uniform) scale into world space.
			// Normalising in the fragment shader keeps the direction smooth
			// across triaxial bodies.
			shader.vertexShader = shader.vertexShader
				.replace('#include <common>', '#include <common>\nvarying vec3 vNightOutwardWorld;')
				.replace(
					'#include <begin_vertex>',
					'#include <begin_vertex>\nvNightOutwardWorld = mat3(modelMatrix) * position;'
				);

			shader.fragmentShader = shader.fragmentShader
				.replace(
					'#include <common>',
					// `uSunDir` is declared by the eclipse-shadow hook we
					// chain after; redeclaring would fail shader compilation
					// with "'uSunDir' : redefinition".
					`#include <common>
					uniform float uNightIntensity;
					varying vec3 vNightOutwardWorld;`
				)
				.replace(
					'#include <emissivemap_fragment>',
					`#include <emissivemap_fragment>
					#ifdef USE_EMISSIVEMAP
						// Modulate by the unlit-side factor: 1 on the night
						// side, 0 on the day side. Without USE_EMISSIVEMAP the
						// chunk above is a no-op and emission stays at zero,
						// so we don't need to gate the lit-side fall-off too.
						vec3 nightOutward = normalize(vNightOutwardWorld);
						float nightDot = dot(nightOutward, uSunDir);
						float nightFactor = 1.0 - smoothstep(${TERMINATOR_LOW.toFixed(2)}, ${TERMINATOR_HIGH.toFixed(2)}, nightDot);
						totalEmissiveRadiance *= nightFactor * uNightIntensity;
					#endif`
				);
		};
	}
	material.needsUpdate = true;
	return texture;
}

/**
 * Release the loaded night-lights texture and unset the material's emissive
 * map. The shader hook stays in place — it's gated on `USE_EMISSIVEMAP`,
 * which three.js drops from the recompiled defines when `emissiveMap` is
 * null, so the patched chunk becomes a no-op until the next attach.
 */
export function disposeNightLightsFromMaterial(material: MeshStandardMaterial): void {
	if (!material.emissiveMap) return;
	material.emissiveMap.dispose();
	material.emissiveMap = null;
	material.emissive.setRGB(0, 0, 0);
	material.needsUpdate = true;
}
