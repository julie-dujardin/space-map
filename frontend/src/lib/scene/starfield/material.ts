/**
 * The point material of the starfield. Each star's apparent magnitude comes
 * from its absolute magnitude and its distance to the camera, so one node
 * draws right from anywhere. A star at the limit magnitude draws nothing and
 * brightens over the first magnitude above it, so a node that loads at the
 * limit does not pop in. Dust (`scene/dust`) changes the magnitude and colour
 * before the limit test, so a star that dust hides also leaves the pick pass.
 */

import {
	AddEquation,
	CustomBlending,
	Matrix3,
	NoBlending,
	OneFactor,
	OneMinusDstColorFactor,
	ShaderMaterial,
	Vector3,
	type IUniform,
	type Texture
} from 'three';
import { BOUND_MAX, DUST_COLOUR_GLSL, K_G } from '$lib/scene/dust/extinction';
import { DUST_COLUMN_GLSL } from '$lib/scene/dust/lookup';
import { clampToFarGlsl, isReversedDepth } from '$lib/scene/setup/depth-mode';
import { PC_SCENE } from './tree';

/** Uniforms every node shares; a node adds its own fade. */
export interface StarUniforms {
	/** Limit magnitude. A star this faint draws nothing. */
	uLimit: IUniform<number>;
	/** Device pixels per CSS pixel. */
	uPixelRatio: IUniform<number>;
	/** Gain on every star. It follows the sky's dimming in daylight. */
	uGain: IUniform<number>;
	/** Sky map from `uDustOrigin`, read relative to that origin. */
	uDustCam: IUniform<Texture | null>;
	/** Sky map from the Sun. */
	uDustSun: IUniform<Texture | null>;
	/** Tree axes to nest axes. */
	uDustAxes: IUniform<Matrix3>;
	/** Origin of `uDustCam`, in pc on nest axes. */
	uDustOrigin: IUniform<Vector3>;
	/** Share of the sky maps' effect. At 0 a star reads no texture. */
	uDustShare: IUniform<number>;
}

export function starUniforms(): StarUniforms {
	return {
		uLimit: { value: 7 },
		uPixelRatio: { value: 1 },
		uGain: { value: 1 },
		uDustCam: { value: null },
		uDustSun: { value: null },
		uDustAxes: { value: new Matrix3() },
		uDustOrigin: { value: new Vector3() },
		uDustShare: { value: 0 }
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
/** Rows a node hides at once (`uHidden`): exact stars past this draw twice. */
export const HIDDEN_ROWS = 8;
const HIDDEN_VECTORS = HIDDEN_ROWS / 4;

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
uniform ivec4 uHidden[${HIDDEN_VECTORS}];
uniform highp sampler2DArray uDustCam;
uniform highp sampler2DArray uDustSun;
uniform highp mat3 uDustAxes;
uniform highp vec3 uDustOrigin;
uniform highp float uDustShare;
uniform highp float uDustNode;
uniform highp vec3 uStarBase;
attribute float mag;
attribute vec3 starColour;
attribute float dustBound;
varying vec3 vColour;
${pick ? 'uniform highp uint uPickBase;\nflat varying highp uint vPick;' : ''}
${DUST_COLUMN_GLSL}
${DUST_COLOUR_GLSL}

void main() {
	${pick ? 'vPick = uPickBase + uint(gl_VertexID);' : ''}
	vec4 mv = modelViewMatrix * vec4(position, 1.0);
	float pc = uDistancePc > 0.0 ? uDistancePc : length(mv.xyz) / ${PC_SCENE.toFixed(4)};
	// The catalogue magnitude holds the Sun's dust. A star takes the change.
	highp float dust = uDustNode;
	if (uDustShare > 0.0 && mv.z < 0.0) {
		highp vec3 star = uDustAxes * (uStarBase + position);
		dust += uDustShare * (dustColumn(uDustCam, uDustOrigin, star - uDustOrigin) - dustColumn(uDustSun, vec3(0.0), star));
	}
	// A gain past what the star's colour and brightness allow is an error of the nest.
	dust = max(dust, -dustBound * ${BOUND_MAX.toFixed(1)});
	float m = mag + 5.0 * log2(max(pc, 1e-9)) * 0.30103 - 5.0 + ${K_G.toFixed(3)} * dust;
	float above = max(uLimit - m, uFloor);
	ivec4 vertex = ivec4(gl_VertexID);
	bool hidden = ${Array.from({ length: HIDDEN_VECTORS }, (_, k) => `any(equal(vertex, uHidden[${k}]))`).join(' || ')};
	if (above <= 0.0 || mv.z >= 0.0 || hidden) {
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
	vColour = dustColour(starColour, dust) * uTint * core * fade * uGain;
	gl_Position = projectionMatrix * mv;
	// Past the far plane a star stays on it, behind everything else.
	${clampToFarGlsl()}
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
			// The change of dust column of a node with no sky map.
			uDustNode: { value: 0 },
			// Tree position that `position` starts from.
			uStarBase: { value: new Vector3() },
			// Rows drawn on their own, -1 for none.
			uHidden: { value: new Int32Array(HIDDEN_ROWS).fill(-1) }
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
