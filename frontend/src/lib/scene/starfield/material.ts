/**
 * The point material of the starfield. Each star's apparent magnitude comes
 * from its absolute magnitude and its distance to the camera, so one node
 * draws right from anywhere. A star at the limit magnitude draws nothing and
 * brightens over the first magnitude above it, so a node that loads at the
 * limit does not pop in.
 */

import {
	AddEquation,
	CustomBlending,
	OneFactor,
	OneMinusDstColorFactor,
	ShaderMaterial,
	type IUniform
} from 'three';
import { isReversedDepth } from '$lib/scene/setup/depth-mode';
import { PC_SCENE } from './tree';

/** Uniforms every node shares; a node adds its own fade. */
export interface StarUniforms {
	/** Limit magnitude. A star this faint draws nothing. */
	uLimit: IUniform<number>;
	/** Device pixels per CSS pixel. */
	uPixelRatio: IUniform<number>;
	/** Gain on every star. It follows the sky's dimming in daylight. */
	uGain: IUniform<number>;
}

export function starUniforms(): StarUniforms {
	return {
		uLimit: { value: 7 },
		uPixelRatio: { value: 1 },
		uGain: { value: 1 }
	};
}

/** Magnitudes over which a star brightens from nothing at the limit. */
const FADE_MAG = 1;
/** A star's drawn energy goes as its flux to this power. This fits the
 *  eye's range into the range of the screen. */
const CONTRAST = 0.75;
/** Core brightness of a star at the limit, before the fade. */
const CORE_AT_LIMIT = 0.06;
/** Dot diameter (CSS px) of every star whose core is not yet full. */
const DOT_PX = 2.5;
const MAX_DOT_PX = 14;

/** Built for each material, because the depth mode is set when three boots. */
const vertexShader = (): string => /* glsl */ `
uniform float uLimit;
uniform float uPixelRatio;
uniform float uGain;
uniform float uFade;
attribute float mag;
attribute vec3 starColour;
varying vec3 vColour;

void main() {
	vec4 mv = modelViewMatrix * vec4(position, 1.0);
	float pc = length(mv.xyz) / ${PC_SCENE.toFixed(4)};
	float m = mag + 5.0 * log2(max(pc, 1e-9)) * 0.30103 - 5.0;
	float above = uLimit - m;
	if (above <= 0.0 || mv.z >= 0.0) {
		// Too faint, or behind the camera: put it off screen.
		gl_Position = vec4(2.0, 2.0, 2.0, 1.0);
		gl_PointSize = 0.0;
		vColour = vec3(0.0);
		return;
	}
	float fade = smoothstep(0.0, ${FADE_MAG.toFixed(1)}, above) * uFade;
	// Energy relative to a star at the limit. Past a full core, the dot grows.
	float energy = ${CORE_AT_LIMIT.toFixed(3)} * exp2(above * ${(0.4 * CONTRAST * Math.log2(10)).toFixed(5)});
	float core = min(energy, 1.0);
	float size = ${DOT_PX.toFixed(2)} * sqrt(max(energy, 1.0));
	vColour = starColour * core * fade * uGain;
	gl_Position = projectionMatrix * mv;
	// Past the far plane a star stays on it, behind everything else.
	${isReversedDepth() ? 'gl_Position.z = max(gl_Position.z, 0.0);' : 'gl_Position.z = min(gl_Position.z, gl_Position.w);'}
	gl_PointSize = min(size, ${MAX_DOT_PX.toFixed(1)}) * uPixelRatio;
}
`;

const FRAGMENT = /* glsl */ `
varying vec3 vColour;

void main() {
	vec2 c = gl_PointCoord * 2.0 - 1.0;
	float r2 = dot(c, c);
	if (r2 > 1.0) discard;
	gl_FragColor = vec4(vColour * exp(-5.0 * r2), 1.0);
}
`;

/** A node's material. The program is shared; the uniforms other than the
 *  node's fade are the shared objects. */
export function makeStarMaterial(shared: StarUniforms): ShaderMaterial {
	return new ShaderMaterial({
		uniforms: { ...shared, uFade: { value: 0 } },
		vertexShader: vertexShader(),
		fragmentShader: FRAGMENT,
		// Screen blending: overlapping stars brighten toward white but never
		// past it, so a dense field does not set off the bloom, which starts at 1.
		blending: CustomBlending,
		blendEquation: AddEquation,
		blendSrc: OneMinusDstColorFactor,
		blendDst: OneFactor,
		transparent: true,
		depthTest: true,
		depthWrite: false
	});
}
