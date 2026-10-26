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
	NoBlending,
	OneFactor,
	OneMinusDstColorFactor,
	ShaderMaterial,
	Vector3,
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

/**
 * Built for each material, because the depth mode is set when three boots.
 * The pick pass draws with this same shader, so it tests and sizes a star as
 * the draw does; `pick` only adds the star's pick-id.
 */
export const starVertexShader = (pick = false): string => /* glsl */ `
uniform float uLimit;
uniform float uPixelRatio;
uniform float uGain;
uniform float uFade;
uniform float uFloor;
uniform float uDistancePc;
uniform vec3 uTint;
uniform ivec4 uHidden;
attribute float mag;
attribute vec3 starColour;
varying vec3 vColour;
${pick ? 'uniform highp uint uPickBase;\nflat varying highp uint vPick;' : ''}

void main() {
	${pick ? 'vPick = uPickBase + uint(gl_VertexID);' : ''}
	vec4 mv = modelViewMatrix * vec4(position, 1.0);
	float pc = uDistancePc > 0.0 ? uDistancePc : length(mv.xyz) / ${PC_SCENE.toFixed(4)};
	float m = mag + 5.0 * log2(max(pc, 1e-9)) * 0.30103 - 5.0;
	float above = max(uLimit - m, uFloor);
	if (above <= 0.0 || mv.z >= 0.0 || any(equal(ivec4(gl_VertexID), uHidden))) {
		// Too faint, behind the camera, or drawn on its own: put it off screen.
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
	vColour = starColour * uTint * core * fade * uGain;
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

/** Least light (linear, of 1) that a pick takes as a drawn star. A fainter
 *  fragment is under one step of an 8-bit screen. */
const PICK_MIN_LIGHT = 1 / 255;

/** Writes the pick-id where the star puts light. Where dots overlap, the
 *  depth test keeps the brighter light, as the screen shows it. */
const pickFragment = (): string => /* glsl */ `
varying vec3 vColour;
flat varying highp uint vPick;

void main() {
	vec2 c = gl_PointCoord * 2.0 - 1.0;
	float r2 = dot(c, c);
	if (r2 > 1.0) discard;
	float light = max(vColour.r, max(vColour.g, vColour.b)) * exp(-5.0 * r2);
	if (light < ${PICK_MIN_LIGHT.toFixed(6)}) discard;
	gl_FragDepth = ${isReversedDepth() ? 'light / (1.0 + light)' : '1.0 / (1.0 + light)'};
	gl_FragColor = vec4(
		float(vPick & 255u),
		float((vPick >> 8) & 255u),
		float((vPick >> 16) & 255u),
		float(vPick >> 24)
	) / 255.0;
}
`;

/** No floor: a star under the limit draws nothing. */
export const NO_FLOOR = -1e9;

/** Keeps the selected star visible even below the magnitude limit. */
export const FOCUS_FLOOR_MAG = 3;

/** Shared exposure keeps local stars and catalogue nodes on the same brightness scale. */
export function makeStarMaterial(shared: StarUniforms, floor = NO_FLOOR): ShaderMaterial {
	return new ShaderMaterial({
		uniforms: {
			...shared,
			uFade: { value: 0 },
			uFloor: { value: floor },
			// A local star's proxy must retain its true photometric distance.
			uDistancePc: { value: 0 },
			uTint: { value: new Vector3(1, 1, 1) },
			// Rows drawn on their own, -1 for none.
			uHidden: { value: new Int32Array([-1, -1, -1, -1]) }
		},
		vertexShader: starVertexShader(),
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

/**
 * The pick material of a drawn star material: its own uniform objects, so the
 * limit, fade, floor and hidden row are the ones the stars last drew with.
 * Rows take pick-ids from `base`. The pick target has one pixel per CSS pixel.
 */
export function makeStarPickMaterial(draw: ShaderMaterial, base: number): ShaderMaterial {
	return new ShaderMaterial({
		uniforms: {
			...draw.uniforms,
			uPixelRatio: { value: 1 },
			uPickBase: { value: base }
		},
		vertexShader: starVertexShader(true),
		fragmentShader: pickFragment(),
		blending: NoBlending,
		depthTest: true,
		depthWrite: true
	});
}
