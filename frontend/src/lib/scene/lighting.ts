import { PMREMGenerator, type PointLight, type Texture, type WebGLRenderer } from 'three';
import { RoomEnvironment } from 'three/addons/environments/RoomEnvironment.js';
import { AU_SCALE } from '$lib/math/units';

/** Ambient fill so no surface is pure black. Shared by the main and model scenes. */
export const AMBIENT_INTENSITY = 0.01;

/** Shared by every sun-lighting path (PointLight, sub-system shadow light,
 *  model-overlay light) so a body reads the same brightness as sphere, DEM, or mesh. */
export const SUN_LIGHT_INTENSITY = 3.5;

/** "High ambient" toggle: floods the scene so the night side is inspectable regardless of Sun direction. */
export const AMBIENT_BOOST_INTENSITY = 1;

/** Base IBL for the model-overlay env map, scaled by eclipse factor per frame.
 *  Shape-model meshes opt out via an in-shader IBL stub so their nightside matches the sphere path. */
export const ENV_BASE_INTENSITY = 0.04;

/** Inverse-square solar irradiance, normalized to 1 at 1 AU. Clamped near the Sun to avoid dividing by ~0. */
export function sunIrradianceFactor(sunDistScene: number): number {
	const au = Math.max(sunDistScene / AU_SCALE, 0.01);
	return 1 / (au * au);
}

/** Realistic = physical inverse-square decay tuned so 1 AU still hits
 *  SUN_LIGHT_INTENSITY; off = uniform brightness. `scale` is the debug tuner multiplier. */
export function applySunPointLightMode(light: PointLight, realistic: boolean, scale = 1): void {
	light.decay = realistic ? 2 : 0;
	light.intensity =
		(realistic ? SUN_LIGHT_INTENSITY * AU_SCALE * AU_SCALE : SUN_LIGHT_INTENSITY) * scale;
}

/** Neutral IBL cubemap for the model-overlay scene. */
export function makeEnvMap(renderer: WebGLRenderer): Texture {
	const pmrem = new PMREMGenerator(renderer);
	const tex = pmrem.fromScene(new RoomEnvironment()).texture;
	pmrem.dispose();
	return tex;
}
