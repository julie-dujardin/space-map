import {
	AdditiveBlending,
	BufferAttribute,
	BufferGeometry,
	CanvasTexture,
	Color,
	Float32BufferAttribute,
	type Material,
	PointLight,
	Points,
	Object3D,
	ShaderMaterial,
	Sprite,
	SpriteMaterial,
	Vector3
} from 'three';
import { SUN_LIGHT_INTENSITY } from '$lib/scene/lighting';
import { starColours } from '../starfield/colour';
import { makeStarMaterial, starUniforms } from '../starfield/material';
import { POINT_CLOUD_RENDER_ORDER } from './pointcloud';
import {
	makeViewTintUniforms,
	VIEW_TINT_GLSL,
	type ViewTintUniforms
} from './surface/sun-transmittance';

export const SUN_HDR_MULTIPLIER = 6;
/** Smaller discs have too few stable HDR samples. */
const STAR_DISC_MIN_RADIUS_PX = 2;
const STAR_DISC_FULL_RADIUS_PX = 6;
/** Solar approximation in the catalogue's Gaia bands. */
const SUN_ABS_G = 4.68;
const SUN_BP_RP = 0.823;
const CORONA_OPACITY = 0.6;

/** Bundle of scene objects the Sun contributes beyond the photosphere sphere. */
export interface StarExtras {
	light: PointLight;
	corona: Sprite;
	starPoint: Points;
}

/** Radial gradient canvas texture used by the corona sprite. */
function makeGlowTexture(color: string, size = 256): CanvasTexture {
	const canvas = document.createElement('canvas');
	canvas.width = size;
	canvas.height = size;
	const ctx = canvas.getContext('2d')!;
	const half = size / 2;
	const gradient = ctx.createRadialGradient(half, half, 0, half, half, half);
	// Fade alpha only, keep RGB fixed: fading to rgba(0,0,0,0) would interpolate
	// through a dark intermediate and read as a black ring under bloom.
	gradient.addColorStop(0, withAlpha(color, 1));
	gradient.addColorStop(0.15, withAlpha(color, 1));
	gradient.addColorStop(0.4, withAlpha(color, 0.3));
	gradient.addColorStop(1, withAlpha(color, 0));
	ctx.fillStyle = gradient;
	ctx.fillRect(0, 0, size, size);
	return new CanvasTexture(canvas);
}

function hexToRgb(hex: string): string {
	const r = parseInt(hex.slice(1, 3), 16);
	const g = parseInt(hex.slice(3, 5), 16);
	const b = parseInt(hex.slice(5, 7), 16);
	return `rgb(${r}, ${g}, ${b})`;
}

function withAlpha(rgbColor: string, alpha: number): string {
	return rgbColor.replace(')', `, ${alpha})`).replace('rgb(', 'rgba(');
}

/** Keeps the photosphere warm white under HDR and tone mapping. */
const PHOTOSPHERE_CENTRE_COLOR = '#fff5eb';

/**
 * Limb tint: ≈4700 K blackbody-to-sRGB, the cooler upper photosphere sampled
 * at grazing angles. Confined to a thin rim by the fragment shader's
 * `smoothstep` — a linear mix on μ would warm most of the disc, since μ
 * stays high until it collapses near the silhouette.
 */
const PHOTOSPHERE_LIMB_COLOR = '#ffd9a8';

/** Other stars use neutral limb darkening; the Sun retains its calibrated tint. */
export function makeStarSurfaceMaterial(colour?: Color): ShaderMaterial {
	const centre = colour ?? new Color(PHOTOSPHERE_CENTRE_COLOR);
	const limb = colour ?? new Color(PHOTOSPHERE_LIMB_COLOR);
	return new ShaderMaterial({
		uniforms: {
			uFade: { value: 1 },
			uGain: { value: 1 },
			uCentreColor: { value: new Vector3(centre.r, centre.g, centre.b) },
			uLimbColor: { value: new Vector3(limb.r, limb.g, limb.b) },
			uLimbAlpha: { value: new Vector3(0.5, 0.5, 0.5) },
			// Per-fragment atmospheric chroma, aimed at a nearby shell each frame by
			// updateAtmosphereShaders — a single colour can't work since the disc
			// outsizes the atmosphere band from orbit.
			...makeViewTintUniforms()
		},
		vertexShader: `
			#include <common>
			#include <logdepthbuf_pars_vertex>
			varying vec3 vNormalView;
			varying vec3 vViewDir;
			varying vec3 vWorldPos;
			void main() {
				vec4 viewPos = modelViewMatrix * vec4(position, 1.0);
				vNormalView = normalize(normalMatrix * normal);
				vViewDir = normalize(-viewPos.xyz);
				vWorldPos = (modelMatrix * vec4(position, 1.0)).xyz;
				gl_Position = projectionMatrix * viewPos;
				#include <logdepthbuf_vertex>
			}
		`,
		fragmentShader: `
			#include <common>
			#include <logdepthbuf_pars_fragment>
			uniform float uFade;
			uniform float uGain;
			uniform vec3 uCentreColor;
			uniform vec3 uLimbColor;
			uniform vec3 uLimbAlpha;
			varying vec3 vNormalView;
			varying vec3 vViewDir;
			varying vec3 vWorldPos;
			${VIEW_TINT_GLSL}
			void main() {
				#include <logdepthbuf_fragment>
				float mu = max(dot(normalize(vNormalView), normalize(vViewDir)), 0.0);
				// Hestroffer & Magnan power law, per channel — steeper blue exponent warms the rim.
				vec3 darkening = pow(vec3(max(mu, 1e-4)), uLimbAlpha);
				// Confine warmth to a thin rim: mu stays high across most of the disc
				// and only collapses near the silhouette, so a linear mix would warm too much.
				float warm = 1.0 - smoothstep(0.0, 0.35, mu);
				vec3 tint = mix(uCentreColor, uLimbColor, warm);
				// HDR over-bright: anything past 1.0 blooms and tone-maps via ACES,
				// saturating the centre to white with bleeding light, like a camera on the Sun.
				vec3 hdr = tint * darkening * ${SUN_HDR_MULTIPLIER.toFixed(1)} * uGain;
				gl_FragColor = vec4(atmoViewTint(vWorldPos) * hdr, uFade);
			}
		`
	});
}

/** Soft additive corona billboard sized off radius. */
function makeStarGlow(radius: number, color: string): Sprite {
	const rgbColor = color.startsWith('#') ? hexToRgb(color) : color;

	const glowTexture = makeGlowTexture(rgbColor);
	const coronaMaterial = new SpriteMaterial({
		map: glowTexture,
		blending: AdditiveBlending,
		transparent: true,
		opacity: CORONA_OPACITY,
		depthWrite: false,
		depthTest: true
	});
	const corona = new Sprite(coronaMaterial);
	const glowSize = radius * 6;
	corona.scale.set(glowSize, glowSize, 1);

	return corona;
}

/** The unresolved Sun uses the same colour and point profile as catalogue stars. */
function makeStarPoint(): Points {
	const geometry = new BufferGeometry();
	geometry.setAttribute('position', new Float32BufferAttribute(new Float32Array(3), 3));
	geometry.setAttribute('mag', new Float32BufferAttribute([SUN_ABS_G], 1));
	const colour = starColours(new Float32Array([SUN_BP_RP]), new Uint8Array(3));
	geometry.setAttribute('starColour', new BufferAttribute(colour, 3, true));
	const material = makeStarMaterial(starUniforms());
	material.uniforms.uFade.value = 1;
	const points = new Points(geometry, material);
	points.frustumCulled = false;
	// Asteroid markers must not dim the Sun; solid bodies still occlude it by depth.
	points.renderOrder = POINT_CLOUD_RENDER_ORDER + 1;
	return points;
}

/** Keeps lighting and the unresolved point at the body's moving position. */
export function buildStarExtras(root: Object3D, radius: number, color: string): StarExtras {
	const light = new PointLight(0xffffff, SUN_LIGHT_INTENSITY, 0, 0);
	root.add(light);
	const corona = makeStarGlow(radius, color);
	root.add(corona);
	const starPoint = makeStarPoint();
	root.add(starPoint);
	return { light, corona, starPoint };
}

/** Colour the corona and star point by `AtmosphereFrameState.sunTint`. Chroma
 *  only — the shell's alpha owns dimming; the disc shades via VIEW_TINT_GLSL. */
export function applyStarTint(
	corona: Sprite | null,
	starPoint: Points | null,
	tint: Vector3
): void {
	if (corona) (corona.material as SpriteMaterial).color.setRGB(tint.x, tint.y, tint.z);
	if (starPoint) {
		((starPoint.material as ShaderMaterial).uniforms.uTint.value as Vector3).copy(tint);
	}
}

export function starDiscShare(radiusPx: number): number {
	const t = Math.min(
		Math.max(
			(radiusPx - STAR_DISC_MIN_RADIUS_PX) / (STAR_DISC_FULL_RADIUS_PX - STAR_DISC_MIN_RADIUS_PX),
			0
		),
		1
	);
	return t * t * (3 - 2 * t);
}

/** Avoids a brightness step while the photosphere becomes too small to sample. */
export function updateStarTransition(
	surface: ShaderMaterial | undefined,
	corona: Sprite | null,
	point: Points,
	radiusPx: number
): number {
	const discShare = starDiscShare(radiusPx);
	if (surface) {
		surface.uniforms.uFade.value = discShare;
		surface.transparent = discShare < 1;
		// The fading surface must not occlude the point at the star's centre.
		surface.depthWrite = discShare === 1;
	}
	point.visible = discShare < 1;
	(point.material as ShaderMaterial).uniforms.uFade.value = 1 - discShare;
	if (corona) {
		corona.visible = discShare > 0;
		(corona.material as SpriteMaterial).opacity = CORONA_OPACITY * discShare;
	}
	return discShare;
}

/** The photosphere's view-tint handle, for updateAtmosphereShaders to aim. */
export function starViewTintUniforms(
	material: Material | null | undefined
): ViewTintUniforms | null {
	const uniforms = (material as ShaderMaterial | null | undefined)?.uniforms;
	return uniforms?.uAtmoTEnable ? (uniforms as unknown as ViewTintUniforms) : null;
}

/** Push the exported limb-darkening exponents onto a photosphere material —
 *  no-op until the data (or the material) exists, so callers can just call it
 *  every frame. */
export function setStarLimbAlpha(
	material: Material | null | undefined,
	alpha: readonly [number, number, number] | null
): void {
	const uniforms = (material as ShaderMaterial | null | undefined)?.uniforms;
	if (alpha && uniforms?.uLimbAlpha) {
		(uniforms.uLimbAlpha.value as Vector3).set(alpha[0], alpha[1], alpha[2]);
	}
}
