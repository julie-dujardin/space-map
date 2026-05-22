import {
	AdditiveBlending,
	BufferGeometry,
	CanvasTexture,
	Color,
	Float32BufferAttribute,
	PointLight,
	Points,
	Scene,
	ShaderMaterial,
	Sprite,
	SpriteMaterial,
	Vector3
} from 'three';

/**
 * HDR over-bright multiplier the photosphere fragment shader writes for each
 * pixel of the sun's disc (modulated by Eddington limb darkening). The bloom
 * pass + ACES tonemap above 1.0 turn this into the saturated white + halo
 * look. Shared with the star-point handoff calc so the dot's brightness
 * tracks the mesh's whenever this is tuned.
 */
export const SUN_HDR_MULTIPLIER = 6;
/**
 * Disc-averaged intensity factor for the Eddington limb-darkening law
 * `I(μ) = I₀(1 − u + u·μ)` with `u = 0.6`. Closed-form integral over the
 * projected disc: `⟨I⟩/I₀ = 1 − u/3 = 0.8`. Used to convert the centre-pixel
 * HDR (`SUN_HDR_MULTIPLIER`) into the average per-pixel HDR the star-point
 * needs to deliver for a smooth bloom handoff.
 */
const EDDINGTON_DISC_AVG = 0.8;
/**
 * Pixel diameter of the star-point sprite. The visibility pass switches from
 * mesh to point when the mesh's projected radius drops below `SIZE/2` — i.e.
 * the moment their on-screen areas coincide.
 */
export const STAR_POINT_SIZE_PX = 4;
/**
 * Uniform alpha of the circle texture sampled by the star-point shader
 * (`makeCircleTexture` fills with `globalAlpha = 0.3`). Under normal alpha
 * blending against a near-black background, the framebuffer ends up at
 * `uColor · uIntensity · texelAlpha`, so this divides out of the handoff
 * intensity calculation.
 */
const STAR_POINT_TEXEL_ALPHA = 0.3;
/**
 * HDR `uIntensity` the star-point shader emits at the handoff moment
 * (`screenR == STAR_POINT_SIZE_PX/2`, where mesh and point cover the same
 * area). Derived so the point's average per-pixel framebuffer HDR matches
 * the mesh's disc-averaged HDR:
 *
 *     uIntensity · texelAlpha = SUN_HDR_MULTIPLIER · EDDINGTON_DISC_AVG
 *
 * giving a continuous bloom contribution across the handoff. The visibility
 * pass scales this down as `(screenR / (SIZE/2))²` once past the handoff for
 * the inverse-square apparent-brightness fall-off with distance.
 */
export const STAR_POINT_HANDOFF_INTENSITY =
	(SUN_HDR_MULTIPLIER * EDDINGTON_DISC_AVG) / STAR_POINT_TEXEL_ALPHA;
/**
 * Lower bound on the star-point HDR uniform. Sits just above the bloom
 * threshold (1.0) so even at apparent fluxes well below handoff, the dot
 * still picks up a faint halo — roughly how a bright distant star reads on
 * a real-camera exposure rather than a hard LDR speck.
 */
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
	// Fade the alpha but keep the same RGB so canvas's sRGB interpolation never
	// produces a dark intermediate — a fade to `rgba(0,0,0,0)` reads as a black
	// ring through the bloom transition.
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
 * Photosphere centre colour: blackbody-to-sRGB for the Sun's effective
 * temperature (5778 K). Overrides the body's `BODY_COLORS` tint (which is the
 * saturated yellow used by the halo / corona / starPoint) because the actual
 * disc, lit by HDR + bloom + ACES, reads physically as warm white.
 */
const PHOTOSPHERE_CENTRE_COLOR = '#fff5eb';

/**
 * Limb tint: ≈ 4700 K blackbody-to-sRGB, matching the photospheric limb's
 * effective temperature (cooler upper photosphere sampled at grazing angles).
 * Confined to a thin rim by the `smoothstep` ramp in the fragment shader — a
 * linear mix on μ would pull most of the disc warm because μ stays high
 * across the projected area and only collapses at the silhouette.
 */
const PHOTOSPHERE_LIMB_COLOR = '#ffd9a8';

/**
 * Photosphere material for a star sphere. Eddington limb darkening
 * (I = 1 - u + u·μ, u ≈ 0.6) with a warmer tint at the rim — the limb is
 * cooler upper photosphere seen at grazing angles, so it reads more orange
 * than the white-hot disc centre. View-direction driven only; no per-frame
 * uniforms. Output is HDR (×6) so the bloom + ACES tone-map pipeline saturates
 * the centre to white and bleeds light outward.
 */
export function makeStarSurfaceMaterial(): ShaderMaterial {
	const centre = new Color(PHOTOSPHERE_CENTRE_COLOR);
	const limb = new Color(PHOTOSPHERE_LIMB_COLOR);
	return new ShaderMaterial({
		uniforms: {
			uCentreColor: { value: new Vector3(centre.r, centre.g, centre.b) },
			uLimbColor: { value: new Vector3(limb.r, limb.g, limb.b) }
		},
		vertexShader: `
			#include <common>
			#include <logdepthbuf_pars_vertex>
			varying vec3 vNormalView;
			varying vec3 vViewDir;
			void main() {
				vec4 viewPos = modelViewMatrix * vec4(position, 1.0);
				vNormalView = normalize(normalMatrix * normal);
				vViewDir = normalize(-viewPos.xyz);
				gl_Position = projectionMatrix * viewPos;
				#include <logdepthbuf_vertex>
			}
		`,
		fragmentShader: `
			#include <common>
			#include <logdepthbuf_pars_fragment>
			uniform vec3 uCentreColor;
			uniform vec3 uLimbColor;
			varying vec3 vNormalView;
			varying vec3 vViewDir;
			void main() {
				#include <logdepthbuf_fragment>
				float mu = max(dot(normalize(vNormalView), normalize(vViewDir)), 0.0);
				// Eddington classical limb darkening, u=0.6 fits the visible band.
				float darkening = 1.0 - 0.6 + 0.6 * mu;
				// Confine the warm tint to a thin rim. A linear mix on mu would
				// pull most of the disc warm because mu = sqrt(1 - r²/R²) stays
				// high across the projected disc and only collapses near the
				// silhouette; the smoothstep keeps the rest cleanly at uCentreColor.
				float warm = 1.0 - smoothstep(0.0, 0.35, mu);
				vec3 tint = mix(uCentreColor, uLimbColor, warm);
				// HDR over-bright multiplier. The pipeline blooms anything past
				// 1.0 and tone-maps via ACES, so the disc centre saturates to
				// white with a soft halo of bleeding light — same look a camera
				// gets when pointed at the Sun, rather than a flat cream ball.
				gl_FragColor = vec4(tint * darkening * ${SUN_HDR_MULTIPLIER.toFixed(1)}, 1.0);
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
 * Single fixed-size dot, visible when the star's mesh is sub-pixel. Uses a
 * custom shader (not `PointsMaterial`) so its output can exceed 1.0 in linear
 * space and feed the bloom pass — without that, the dot is clamped to LDR and
 * the sun's bloom would vanish the instant the mesh drops below one pixel.
 * `uIntensity` is driven per-frame from `screenR²` (visibility/update.ts),
 * giving an inverse-square apparent-brightness fall-off with distance.
 */
function makeStarPoint(color: string, circleTexture: CanvasTexture): Points {
	const geometry = new BufferGeometry();
	geometry.setAttribute('position', new Float32BufferAttribute(new Float32Array(3), 3));
	const c = new Color(color);
	const material = new ShaderMaterial({
		uniforms: {
			uColor: { value: new Vector3(c.r, c.g, c.b) },
			uIntensity: { value: STAR_POINT_HANDOFF_INTENSITY },
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
			uniform sampler2D uMap;
			void main() {
				#include <logdepthbuf_fragment>
				vec4 texel = texture2D(uMap, gl_PointCoord);
				if (texel.a < 0.01) discard;
				gl_FragColor = vec4(uColor * uIntensity, texel.a);
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
 * Build every scene-side object a star contributes beyond its photosphere mesh:
 * the heliocentric PointLight, the additive corona sprite, and the sub-pixel
 * fallback point. All three are added to `scene` and returned so the caller can
 * track them on its BodyObjects record (for visibility / focus / cleanup paths).
 */
export function buildStarExtras(
	scene: Scene,
	radius: number,
	color: string,
	circleTexture: CanvasTexture
): StarExtras {
	const light = new PointLight(0xffffff, 2, 0, 0);
	scene.add(light);
	const corona = makeStarGlow(radius, color);
	scene.add(corona);
	const starPoint = makeStarPoint(color, circleTexture);
	scene.add(starPoint);
	return { light, corona, starPoint };
}
