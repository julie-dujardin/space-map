import {
	AdditiveBlending,
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
	Vector3,
	Vector4
} from 'three';
import { BLOOM_THRESHOLD, SUN_LIGHT_INTENSITY } from '$lib/scene/lighting';
import {
	makeViewTintUniforms,
	VIEW_TINT_GLSL,
	type ViewTintUniforms
} from './surface/sun-transmittance';

/**
 * Photosphere → star-point handoff constants. The point gives the bloom the
 * light of the disc it replaces, or the glow steps at the handoff:
 * STAR_POINT_LIGHT is that light, in HDR × CSS px².
 * LIMB_DISC_AVG ≈ 0.8: the I(μ) = μ^α limb law disc-averages to 2/(α+2) at the
 * luminance-weighted α, matching the classical Eddington average (handoff is
 * insensitive to whether the exported α has arrived).
 */
export const SUN_HDR_MULTIPLIER = 6;
const LIMB_DISC_AVG = 0.8;
/** CSS px. Switch mesh → point when projected radius drops below SIZE/2 (equal areas). */
export const STAR_POINT_SIZE_PX = 4;
const STAR_POINT_LIGHT =
	SUN_HDR_MULTIPLIER * LIMB_DISC_AVG * Math.PI * (STAR_POINT_SIZE_PX / 2) ** 2;
/** The dot once the star has too little light for the bloom: in view, with no glow. */
const STAR_POINT_FLOOR = 0.9;
/** A focused star is at the centre of the canvas, a corner or a centre of a
 *  pixel: the dot is seated off both, or it flips between two seats. */
const STAR_POINT_SEAT_BIAS = 0.125;
const CORONA_OPACITY = 0.6;
/** The corona is gone at the handoff and whole at this many times its radius. */
const CORONA_WHOLE = 1.5;

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

/**
 * Photosphere centre colour: blackbody-to-sRGB at 5778 K. Overrides the
 * body's saturated-yellow `BODY_COLORS` tint (used by halo/corona/starPoint),
 * since the disc under HDR + bloom + ACES reads physically as warm white.
 */
const PHOTOSPHERE_CENTRE_COLOR = '#fff5eb';

/**
 * Limb tint: ≈4700 K blackbody-to-sRGB, the cooler upper photosphere sampled
 * at grazing angles. Confined to a thin rim by the fragment shader's
 * `smoothstep` — a linear mix on μ would warm most of the disc, since μ
 * stays high until it collapses near the silhouette.
 */
const PHOTOSPHERE_LIMB_COLOR = '#ffd9a8';

/**
 * Photosphere material. Per-channel power-law limb darkening I(μ) = μ^α(λ)
 * (Hestroffer & Magnan 1998) — α rises toward blue, physically warming the
 * rim — plus the artistic thin-rim tint below. α ships in atmospheres.json
 * ({@link setStarLimbAlpha}); neutral α = 0.5 until it lands. Output is HDR
 * (×6) so bloom + ACES saturate the centre to white and bleed light outward.
 */
export function makeStarSurfaceMaterial(): ShaderMaterial {
	const centre = new Color(PHOTOSPHERE_CENTRE_COLOR);
	const limb = new Color(PHOTOSPHERE_LIMB_COLOR);
	return new ShaderMaterial({
		uniforms: {
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
				vec3 hdr = tint * darkening * ${SUN_HDR_MULTIPLIER.toFixed(1)};
				gl_FragColor = vec4(atmoViewTint(vWorldPos) * hdr, 1.0);
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

/** Pixels of a dot `size` wide that is seated on a pixel corner. */
function dotPixels(size: number): number {
	const reach = Math.ceil(size / 2);
	let count = 0;
	for (let y = -reach; y < reach; y++) {
		for (let x = -reach; x < reach; x++) {
			if ((x + 0.5) ** 2 + (y + 0.5) ** 2 <= (size * size) / 4) count++;
		}
	}
	return count;
}

/**
 * Stands for the star once its disc is too small to draw: a disc of a few
 * pixels is sampled at one or two of them, so its HDR output changes as it
 * crosses the pixel grid. `uFlux` is the star's light: 1 at the handoff, then
 * inverse-square.
 * The bloom takes a pixel whole or not at all, so the dot must not change the
 * pixels it gives as it moves: it is seated on a pixel corner, with no soft
 * edge, and its light is on pixels that are all over the threshold.
 */
function makeStarPoint(color: string): Points {
	const geometry = new BufferGeometry();
	geometry.setAttribute('position', new Float32BufferAttribute(new Float32Array(3), 3));
	const c = new Color(color);
	const disc = new Color(PHOTOSPHERE_CENTRE_COLOR);
	const viewport = new Vector4(0, 0, 1, 1);
	const size = STAR_POINT_SIZE_PX.toFixed(1);
	const uniforms = {
		uColor: { value: new Vector3(c.r, c.g, c.b) },
		uDiscColor: { value: new Vector3(disc.r, disc.g, disc.b) },
		uFlux: { value: 1 },
		uPixelRatio: { value: 1 },
		uPixels: { value: dotPixels(STAR_POINT_SIZE_PX) },
		uViewport: { value: viewport },
		uTint: { value: new Vector3(1, 1, 1) }
	};
	const material = new ShaderMaterial({
		uniforms,
		vertexShader: `
			#include <common>
			#include <logdepthbuf_pars_vertex>
			uniform float uPixelRatio;
			uniform vec4 uViewport;
			varying vec2 vSeat;
			void main() {
				gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0);
				vec2 halfView = 0.5 * uViewport.zw;
				vec2 seat = floor((gl_Position.xy / gl_Position.w + 1.0) * halfView + ${(0.5 + STAR_POINT_SEAT_BIAS).toFixed(3)});
				gl_Position.xy = (seat / halfView - 1.0) * gl_Position.w;
				vSeat = uViewport.xy + seat;
				// A margin: the square of the point must not cut the dot.
				gl_PointSize = ${size} * uPixelRatio + 2.0;
				#include <logdepthbuf_vertex>
			}
		`,
		fragmentShader: `
			#include <common>
			#include <logdepthbuf_pars_fragment>
			uniform vec3 uColor;
			uniform vec3 uDiscColor;
			uniform float uFlux;
			uniform float uPixelRatio;
			uniform float uPixels;
			uniform vec3 uTint;
			varying vec2 vSeat;
			void main() {
				#include <logdepthbuf_fragment>
				vec2 p = gl_FragCoord.xy - vSeat;
				float radius = 0.5 * ${size} * uPixelRatio;
				if (dot(p, p) > radius * radius) discard;
				// The disc's colour at the handoff, so the glow keeps it there.
				vec3 colour = uTint * mix(uColor, uDiscColor, uFlux);
				float luma = max(luminance(colour), 0.0001);
				// What the bloom takes for sure, and what it leaves for sure.
				float over = ${(BLOOM_THRESHOLD * 1.05).toFixed(2)} / luma;
				float under = ${(BLOOM_THRESHOLD * 0.95).toFixed(2)} / luma;
				// The disc's light at the handoff, on all the pixels. With too little
				// for all, the four at the centre have it: the glow goes on for a
				// fainter star.
				float all = ${STAR_POINT_LIGHT.toFixed(3)} * uFlux * uPixelRatio * uPixelRatio / uPixels;
				float four = all * uPixels / 4.0;
				float value = clamp(all, ${STAR_POINT_FLOOR.toFixed(1)}, under);
				if (all >= over) {
					value = all;
				} else if (four >= over && max(abs(p.x), abs(p.y)) < 1.0) {
					value = four;
				}
				gl_FragColor = vec4(colour * value, 1.0);
			}
		`,
		transparent: true,
		depthTest: true,
		depthWrite: false
	});
	const points = new Points(geometry, material);
	points.frustumCulled = false;
	// The shader places pixels in the viewport of the pass that draws it.
	points.onBeforeRender = (renderer) => {
		renderer.getCurrentViewport(viewport).floor();
		const pixelRatio = renderer.getPixelRatio();
		if (pixelRatio !== uniforms.uPixelRatio.value) {
			uniforms.uPixelRatio.value = pixelRatio;
			uniforms.uPixels.value = dotPixels(STAR_POINT_SIZE_PX * pixelRatio);
		}
	};
	return points;
}

/**
 * Every scene-side object a star contributes beyond its photosphere mesh:
 * heliocentric PointLight, additive corona sprite, sub-pixel fallback point.
 * Added to `root`, the body's own group, and returned for BodyObjects.
 */
export function buildStarExtras(root: Object3D, radius: number, color: string): StarExtras {
	const light = new PointLight(0xffffff, SUN_LIGHT_INTENSITY, 0, 0);
	root.add(light);
	const corona = makeStarGlow(radius, color);
	root.add(corona);
	const starPoint = makeStarPoint(color);
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

/** Fade the corona out as the disc comes to the handoff (`t` = 1), where the
 *  point takes over: on the point, it would lift pixels over the bloom
 *  threshold as the star moves. */
export function fadeStarCorona(corona: Sprite | null, t: number): void {
	if (!corona) return;
	const part = Math.min(Math.max((t - 1) / (CORONA_WHOLE - 1), 0), 1);
	corona.visible = part > 0;
	(corona.material as SpriteMaterial).opacity = CORONA_OPACITY * part;
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
