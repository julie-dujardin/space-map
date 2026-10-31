import {
	AdditiveBlending,
	CanvasTexture,
	Color,
	type Mesh,
	ShaderMaterial,
	Sprite,
	SpriteMaterial,
	Vector3
} from 'three';
import { planckianRgb } from '$lib/scene/starfield/colour';
import { SOLAR_RADIUS_KM } from '$lib/math/units';

/** What a star's disc is drawn from. */
export interface Photosphere {
	/** Effective temperature, K. */
	teff: number;
}

/** Limb darkening I(μ) = μ^α per channel, α = −0.023 + 0.292/λ (Hestroffer &
 *  Magnan 1998, λ in µm), at the sRGB primaries: the limb reddens as it dims. */
const LIMB_ALPHA = [0.61, 0.55, 0.46].map((um) => -0.023 + 0.292 / um);
/** Display-referred: at the law's own strength sRGB hides the fall to the limb. */
const LIMB_STRENGTH = 1.5;
/** How much of the law's reddening is kept: all of it turns a hot star's limb grey. */
const LIMB_CHROMA = 0.3;
/** A chromaticity near white is all a black body has, so a row of them reads
 *  grey without this. */
const SATURATION = 1.5;
/** A photograph's response, on luminance alone: per channel it turns orange yellow. */
const EXPOSURE = 3;
/** How far the centre of the disc washes toward white. */
const CORE_WASH = 0.3;

/** Above this a star's envelope is radiative: no convection cells to show. */
const CONVECTIVE_TEFF: [number, number] = [5000, 6500];
const CELL_CONTRAST = 0.22;
/** Convection cells across a Sun-sized radius. They grow with the star, to a
 *  few across a supergiant's disc (Schwarzschild 1975). */
const SOLAR_CELLS = 80;
/** On screen, cells under this many pixels are not drawn: they would alias. */
const CELL_MIN_PX: [number, number] = [2.5, 6];

/** The Sun's effective temperature, K (IAU 2015 Resolution B3). */
export const SUN_TEFF = 5772;
/** Space, in either theme: a white-hot disc on the light drawer disappears. */
export const LINEUP_SKY = '#05060b';

/** How far the halo reaches past the limb, in radii and in pixels: the pixels
 *  keep a small star's bloom visible. */
const HALO_REACH = 0.28;
const HALO_REACH_PX = 14;
const HALO_OPACITY = 0.6;

function smoothstep([lo, hi]: [number, number], x: number): number {
	const t = Math.min(Math.max((x - lo) / (hi - lo), 0), 1);
	return t * t * (3 - 2 * t);
}

function cellsPerRadius(radiusKm: number): number {
	return SOLAR_CELLS / Math.sqrt(radiusKm / SOLAR_RADIUS_KM);
}

function limbAlpha(): Vector3 {
	const mid = LIMB_ALPHA[1];
	const [r, g, b] = LIMB_ALPHA.map((a) => LIMB_STRENGTH * (mid + LIMB_CHROMA * (a - mid)));
	return new Vector3(r, g, b);
}

/** An unlit photosphere. The camera is orthographic, so μ is the view-space
 *  normal's z. Drawn outside the row's tone mapping, which greys a star. */
export function makeLineupStarMaterial(
	p: Photosphere,
	radiusKm: number,
	seed: number
): ShaderMaterial {
	const rgb = planckianRgb(p.teff, [0, 0, 0]);
	return new ShaderMaterial({
		toneMapped: false,
		uniforms: {
			uColour: { value: new Vector3(...rgb) },
			uAlpha: { value: limbAlpha() },
			uCells: { value: cellsPerRadius(radiusKm) },
			uContrast: { value: 0 },
			uSeed: { value: seed % 97 }
		},
		vertexShader: `
			varying vec3 vNormalView;
			varying vec3 vPosition;
			void main() {
				vNormalView = normalize(normalMatrix * normal);
				vPosition = position;
				gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0);
			}
		`,
		fragmentShader: `
			uniform vec3 uColour;
			uniform vec3 uAlpha;
			uniform float uCells;
			uniform float uContrast;
			uniform float uSeed;
			varying vec3 vNormalView;
			varying vec3 vPosition;
			float hash(vec3 p) {
				p = fract(p * 0.3183099 + 0.1);
				p *= 17.0;
				return fract(p.x * p.y * p.z * (p.x + p.y + p.z));
			}
			float noise(vec3 x) {
				vec3 i = floor(x);
				vec3 f = fract(x);
				f = f * f * (3.0 - 2.0 * f);
				return mix(
					mix(mix(hash(i), hash(i + vec3(1, 0, 0)), f.x),
						mix(hash(i + vec3(0, 1, 0)), hash(i + vec3(1, 1, 0)), f.x), f.y),
					mix(mix(hash(i + vec3(0, 0, 1)), hash(i + vec3(1, 0, 1)), f.x),
						mix(hash(i + vec3(0, 1, 1)), hash(i + vec3(1, 1, 1)), f.x), f.y),
					f.z);
			}
			void main() {
				float mu = max(normalize(vNormalView).z, 1e-3);
				float cells = 0.0;
				if (uContrast > 0.0) {
					vec3 p = normalize(vPosition) * uCells + uSeed;
					// Bright cells parted by dark lanes.
					float n = noise(p + 1.5 * noise(p * 0.7));
					cells = (n - 0.5) * uContrast;
				}
				vec3 light = uColour * pow(vec3(mu), uAlpha);
				float luma = dot(light, vec3(0.2126, 0.7152, 0.0722));
				light = max(mix(vec3(luma), light, ${SATURATION.toFixed(2)}), vec3(0.0));
				light *= (1.0 - exp(-${EXPOSURE.toFixed(2)} * luma)) / luma;
				light /= max(max(light.r, max(light.g, light.b)), 1.0);
				light = mix(light, vec3(1.0), ${CORE_WASH.toFixed(2)} * mu * mu * mu);
				light *= 1.0 + cells;
				gl_FragColor = vec4(light, 1.0);
				#include <colorspace_fragment>
			}
		`
	});
}

/** The row's camera sees this layer and the hover glow's mask camera does not:
 *  an override material turns a sprite into a flat square that spins with its
 *  star, and the mask would trace that. */
export const HALO_LAYER = 1;

let haloTexture: CanvasTexture | undefined;

/** The falloff past the limb; the disc hides everything inside it. */
function makeHaloTexture(size = 512): CanvasTexture {
	const canvas = document.createElement('canvas');
	canvas.width = canvas.height = size;
	const ctx = canvas.getContext('2d')!;
	const half = size / 2;
	const gradient = ctx.createRadialGradient(half, half, 0, half, half, half);
	for (let i = 0; i <= 24; i++) {
		const t = i / 24;
		gradient.addColorStop(t, `rgba(255, 255, 255, ${(1 - t) ** 2.4})`);
	}
	ctx.fillStyle = gradient;
	ctx.fillRect(0, 0, size, size);
	return new CanvasTexture(canvas);
}

/** A star's bloom. A child of its disc, so it follows the row's moves; a sprite,
 *  so it faces the camera whatever the tilt and no fit of the row counts it. */
export function addLineupStarHalo(disc: Mesh, p: Photosphere): void {
	const halo = new Sprite(
		new SpriteMaterial({
			map: (haloTexture ??= makeHaloTexture()),
			color: new Color(...planckianRgb(p.teff, [0, 0, 0])),
			opacity: HALO_OPACITY,
			blending: AdditiveBlending,
			depthWrite: false,
			toneMapped: false
		})
	);
	halo.layers.set(HALO_LAYER);
	disc.add(halo);
}

/** Fit what depends on the pixels a disc is drawn at: the halo's reach, and
 *  whether its convection cells show at all. */
export function fitLineupStar(disc: Mesh, p: Photosphere, pr: number): void {
	const halo = disc.children[0] as Sprite | undefined;
	// Measured from the centre of a sprite twice its reach across, so the fall
	// reaches zero that far past the limb.
	halo?.scale.setScalar(2 * (1 + HALO_REACH + HALO_REACH_PX / pr));
	const { uCells, uContrast } = (disc.material as ShaderMaterial).uniforms;
	uContrast.value =
		CELL_CONTRAST *
		(1 - smoothstep(CONVECTIVE_TEFF, p.teff)) *
		smoothstep(CELL_MIN_PX, pr / uCells.value);
}
