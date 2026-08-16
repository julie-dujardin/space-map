import {
	AdditiveBlending,
	BufferGeometry,
	CanvasTexture,
	Color,
	Float32BufferAttribute,
	type Material,
	PointLight,
	Points,
	Scene,
	ShaderMaterial,
	Sprite,
	SpriteMaterial,
	Vector3
} from 'three';
import { SUN_LIGHT_INTENSITY } from '$lib/scene/lighting';
import {
	makeViewTintUniforms,
	VIEW_TINT_GLSL,
	type ViewTintUniforms
} from './surface/sun-transmittance';

/**
 * Photosphere → star-point bloom handoff constants, tuned together so the
 * star-point's per-pixel HDR matches the mesh's disc-averaged HDR:
 *   uIntensity · STAR_POINT_TEXEL_ALPHA = SUN_HDR_MULTIPLIER · LIMB_DISC_AVG
 * LIMB_DISC_AVG ≈ 0.8: the I(μ) = μ^α limb law disc-averages to 2/(α+2) at the
 * luminance-weighted α, matching the classical Eddington average (handoff is
 * insensitive to whether the exported α has arrived). STAR_POINT_TEXEL_ALPHA
 * is the circle-texture fill alpha. STAR_POINT_FLOOR_INTENSITY sits just
 * above the bloom threshold so faint stars still get a halo, not a hard speck.
 */
export const SUN_HDR_MULTIPLIER = 6;
const LIMB_DISC_AVG = 0.8;
/** Switch mesh → point when projected radius drops below SIZE/2 (equal areas). */
export const STAR_POINT_SIZE_PX = 4;
const STAR_POINT_TEXEL_ALPHA = 0.3;
export const STAR_POINT_HANDOFF_INTENSITY =
	(SUN_HDR_MULTIPLIER * LIMB_DISC_AVG) / STAR_POINT_TEXEL_ALPHA;
export const STAR_POINT_FLOOR_INTENSITY = 3;

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
		opacity: 0.6,
		depthWrite: false,
		depthTest: true
	});
	const corona = new Sprite(coronaMaterial);
	const glowSize = radius * 6;
	corona.scale.set(glowSize, glowSize, 1);

	return corona;
}

/**
 * Fixed-size dot for when the star's mesh is sub-pixel. Custom shader (not
 * `PointsMaterial`) so output can exceed 1.0 and feed bloom — otherwise the
 * sun's bloom vanishes the instant the mesh drops below one pixel.
 * `uIntensity` is driven per-frame from `screenR²` for inverse-square falloff.
 */
function makeStarPoint(color: string, circleTexture: CanvasTexture): Points {
	const geometry = new BufferGeometry();
	geometry.setAttribute('position', new Float32BufferAttribute(new Float32Array(3), 3));
	const c = new Color(color);
	const material = new ShaderMaterial({
		uniforms: {
			uColor: { value: new Vector3(c.r, c.g, c.b) },
			uIntensity: { value: STAR_POINT_HANDOFF_INTENSITY },
			uTint: { value: new Vector3(1, 1, 1) },
			uMap: { value: circleTexture }
		},
		vertexShader: `
			#include <common>
			#include <logdepthbuf_pars_vertex>
			void main() {
				gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0);
				gl_PointSize = ${STAR_POINT_SIZE_PX.toFixed(1)};
				#include <logdepthbuf_vertex>
			}
		`,
		fragmentShader: `
			#include <common>
			#include <logdepthbuf_pars_fragment>
			uniform vec3 uColor;
			uniform float uIntensity;
			uniform vec3 uTint;
			uniform sampler2D uMap;
			void main() {
				#include <logdepthbuf_fragment>
				vec4 texel = texture2D(uMap, gl_PointCoord);
				if (texel.a < 0.01) discard;
				gl_FragColor = vec4(uTint * uColor * uIntensity, texel.a);
			}
		`,
		transparent: true,
		depthTest: true,
		depthWrite: false
	});
	const points = new Points(geometry, material);
	points.frustumCulled = false;
	return points;
}

/**
 * Every scene-side object a star contributes beyond its photosphere mesh:
 * heliocentric PointLight, additive corona sprite, sub-pixel fallback point.
 * Added to `scene` and returned so the caller can track them on BodyObjects.
 */
export function buildStarExtras(
	scene: Scene,
	radius: number,
	color: string,
	circleTexture: CanvasTexture
): StarExtras {
	const light = new PointLight(0xffffff, SUN_LIGHT_INTENSITY, 0, 0);
	scene.add(light);
	const corona = makeStarGlow(radius, color);
	scene.add(corona);
	const starPoint = makeStarPoint(color, circleTexture);
	scene.add(starPoint);
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
