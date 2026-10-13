import { type Material, Matrix4, type Mesh, type MeshStandardMaterial, Vector3 } from 'three';
import { chainShaderHook } from '$lib/scene/shaders/program-cache-key';

/**
 * Draws a body's surface from an anchor at the camera.
 *
 * A vertex of a planet is a radius away from the origin of its mesh, and so is
 * the camera. The model-view product takes one of these large numbers from the
 * other: at 32 bits the result is good to 22 cm on Mars and 43 cm on Earth,
 * and its rounding changes with the matrix, so the ground a few metres from
 * the camera jumps on each frame the body turns. The offset of a vertex from
 * the anchor is exact at 32 bits, and the CPU places the anchor at 64 bits.
 */

const PARS = /* glsl */ `
uniform vec3 uEyeAnchor;
uniform vec3 uEyeAnchorView;
`;

/** `project_vertex` of three.js, for a mesh with no batching and no instancing. */
const PROJECT_VERTEX = /* glsl */ `
vec4 mvPosition = vec4( mat3( modelViewMatrix ) * ( transformed - uEyeAnchor ) + uEyeAnchorView, 1.0 );
gl_Position = projectionMatrix * mvPosition;
`;

interface Anchor {
	/** In the frame of the mesh. */
	local: { value: Vector3 };
	/** In view space. */
	view: { value: Vector3 };
}

const anchors = new WeakMap<Material, Anchor>();
const _modelView = new Matrix4();
const _inverse = new Matrix4();
const _eye = new Vector3();

function patch(material: Material, anchor: Anchor): void {
	chainShaderHook(material, 'cameraRelative', (shader) => {
		shader.uniforms.uEyeAnchor = anchor.local;
		shader.uniforms.uEyeAnchorView = anchor.view;
		shader.vertexShader = shader.vertexShader
			.replace('#include <common>', `#include <common>\n${PARS}`)
			.replace('#include <project_vertex>', PROJECT_VERTEX);
	});
}

/** Make `mesh` draw its `material` camera-relative. The mesh owns its
 *  `onBeforeRender` from here on. */
export function attachCameraRelative(mesh: Mesh, material: MeshStandardMaterial): void {
	const anchor: Anchor = { local: { value: new Vector3() }, view: { value: new Vector3() } };
	anchors.set(material, anchor);
	patch(material, anchor);
	// Per render call: each pass has its own camera.
	mesh.onBeforeRender = (_renderer, _scene, camera) => {
		_modelView.multiplyMatrices(camera.matrixWorldInverse, mesh.matrixWorld);
		_eye.setFromMatrixPosition(_inverse.copy(_modelView).invert());
		// Rounded as the GPU holds it: the shader's subtraction is then exact.
		anchor.local.value.set(Math.fround(_eye.x), Math.fround(_eye.y), Math.fround(_eye.z));
		anchor.view.value.copy(anchor.local.value).applyMatrix4(_modelView);
	};
}

/** Make `twin`, which a pass draws in the place of `material`, put the surface
 *  where `material` does: a depth of its own is off by the same rounding. */
export function shareCameraRelative(material: Material, twin: Material): void {
	const anchor = anchors.get(material);
	if (anchor) patch(twin, anchor);
}
