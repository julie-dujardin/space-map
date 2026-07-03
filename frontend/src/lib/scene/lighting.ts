import { PMREMGenerator, type Texture, type WebGLRenderer } from 'three';
import { RoomEnvironment } from 'three/addons/environments/RoomEnvironment.js';

/** Ambient fill so no surface is pure black. Shared by the main and model scenes. */
export const AMBIENT_INTENSITY = 0.01;

/** Base IBL intensity for the model-overlay env map: just enough that metallic
 *  spacecraft have something to reflect without overpowering the sun. Scaled by the
 *  eclipse factor per frame. Non-metal shape-model meshes opt out (`envMapIntensity`
 *  = 0) so their nightside matches the sphere path, which gets no IBL. */
export const ENV_BASE_INTENSITY = 0.04;

/** Neutral IBL cubemap for the model-overlay scene. */
export function makeEnvMap(renderer: WebGLRenderer): Texture {
	const pmrem = new PMREMGenerator(renderer);
	const tex = pmrem.fromScene(new RoomEnvironment()).texture;
	pmrem.dispose();
	return tex;
}
