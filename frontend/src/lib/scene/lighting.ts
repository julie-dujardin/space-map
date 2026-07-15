import { PMREMGenerator, type Texture, type WebGLRenderer } from 'three';
import { RoomEnvironment } from 'three/addons/environments/RoomEnvironment.js';

/** Ambient fill so no surface is pure black. Shared by the main and model scenes. */
export const AMBIENT_INTENSITY = 0.01;

/** Direct sunlight intensity. Shared by every path that sun-lights a body — the
 *  solar-system PointLight, the sub-system shadow DirectionalLight, and the
 *  model-overlay light — so a body reads the same brightness whether it renders
 *  as a sphere, a DEM, or a shape-model/spacecraft mesh. */
export const SUN_LIGHT_INTENSITY = 3.5;

/** Ambient level for the "high ambient" layer toggle: floods the scene with flat
 *  fill so a body's night side (and its texture/relief) is fully visible for
 *  inspection, regardless of Sun direction. */
export const AMBIENT_BOOST_INTENSITY = 1;

/** Base IBL intensity for the model-overlay env map: just enough that metallic
 *  spacecraft have something to reflect without overpowering the sun. Scaled by the
 *  eclipse factor per frame. Shape-model meshes opt out via an in-shader IBL stub
 *  (see `makeShapeModelMaterial`) so their nightside matches the sphere path. */
export const ENV_BASE_INTENSITY = 0.04;

/** Neutral IBL cubemap for the model-overlay scene. */
export function makeEnvMap(renderer: WebGLRenderer): Texture {
	const pmrem = new PMREMGenerator(renderer);
	const tex = pmrem.fromScene(new RoomEnvironment()).texture;
	pmrem.dispose();
	return tex;
}
