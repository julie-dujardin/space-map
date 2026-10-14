/**
 * The light between a planet and its rings.
 *
 * The planet lights both faces of its rings. A face reflects the light from
 * its own side of the ring plane and passes the light from the other side,
 * by the same profiles as the sunlight. A sum over the surface of the planet
 * gives this light: the day side under the Sun and the ring shadow, and the
 * night side under the light of the rings. The CPU makes the sum in float64
 * and gives it to the ring shader as a small texture, by azimuth from the Sun
 * and by radius.
 *
 * The rings light the planet (ringshine). A fixed set of patches holds the
 * light of the lit annulus: radial bands of equal light as the planet sees
 * it, and sectors of azimuth from the Sun. A patch is at the centroid of its
 * light after the shadow of the planet. The planet's shader adds the patches
 * with the cosine at the fragment. The radiance of a face toward the fragment
 * is Lommel-Seeliger, 2μ0 / (μ0 + μ) times the profile. The profiles are seen
 * from the direction of the Sun, where this factor is 1. The light goes to 0
 * when the Sun is in the ring plane.
 *
 * The frame is the Sun's frame of the ring plane: x points to the azimuth of
 * the Sun, z along the pole. The light is the same at +y and −y. Thus a patch
 * also stands for its mirror, and the texture holds the azimuths 0 to π.
 * Lengths are in scene units. A radiance is in the units of the ring's own
 * colour output, without the solar distance factor.
 */

import {
	ClampToEdgeWrapping,
	Color,
	DataTexture,
	DataUtils,
	HalfFloatType,
	LinearFilter,
	type MeshStandardMaterial,
	RGFormat,
	Vector3,
	Vector4
} from 'three';
import { SUN_LIGHT_INTENSITY } from '$lib/scene/lighting';
import { chainShaderHook } from '$lib/scene/shaders/program-cache-key';

/** Tint of the unlit face, from Björn Jónsson's notes. */
export const UNLIT_TINT: readonly [number, number, number] = [1.0, 0.97075, 0.952];
/** Red bias of forward scatter: the rings get slightly redder at high phase. */
export const FORWARD_TINT_BIAS: readonly [number, number, number] = [1.02, 0.99, 0.97];

const RINGSHINE_BANDS = 3;
const SECTORS = 12;
/** One patch per band and per sector from the Sun to the anti-Sun. */
export const RINGSHINE_PATCHES = RINGSHINE_BANDS * (SECTORS / 2 + 1);
/** Below this sine of the Sun's elevation the rings send no light. The shader
 *  then skips the patches; its Lommel-Seeliger term needs μ0 > 0. */
const RINGSHINE_MIN_MU0 = 1e-4;

/** Radial bins of the profile copy on the CPU. */
const PROFILE_BINS = 256;
/** Azimuth steps per sector, for the shadow and the centroid of a patch. */
const SECTOR_STEPS = 6;

export const PLANET_LIGHT_AZIMUTHS = 19;
export const PLANET_LIGHT_RADII = 8;
/** Cells of the planet in the sum for the ring's planet light. */
const PLANET_ROWS = 24;
const PLANET_COLUMNS = 48;

/** An oblate spheroid about the pole, in scene units. */
export interface Spheroid {
	equatorial: number;
	polar: number;
}

/** A copy of a bundle's profiles in radial bins, for the light on the CPU. */
export interface RingProfile {
	inner: number;
	outer: number;
	/** Luminance of each face per bin: channel × colour × opacity × intensity,
	 *  as the ring shader draws it. */
	back: Float64Array;
	forward: Float64Array;
	unlit: Float64Array;
	/** Fraction of the light that goes through the ring, per bin. */
	transmission: Float64Array;
	/** Hue of the lit face, luminance 1. */
	litTint: Color;
	/** First bin of each band, then the bin count. */
	bands: Int32Array;
}

/** The rows of a ring strip that the light reads. */
export interface ProfileRows {
	color: number;
	backscattered: number;
	forwardscattered: number;
	unlitside: number;
	transparency: number;
}

function luminance(r: number, g: number, b: number): number {
	return 0.2126 * r + 0.7152 * g + 0.0722 * b;
}

const SRGB_TO_LINEAR = Float64Array.from({ length: 256 }, (_, i) => {
	const c = i / 255;
	return c <= 0.04045 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4;
});

/**
 * Bin the strip's RGBA `pixels` (`width` samples per row) into a
 * {@link RingProfile}. A bin holds the mean of the product, so a narrow dense
 * ring keeps its light in a wide bin.
 */
export function ringProfile(
	pixels: Uint8ClampedArray,
	width: number,
	rows: ProfileRows,
	inner: number,
	outer: number,
	intensity: number
): RingProfile {
	const back = new Float64Array(PROFILE_BINS);
	const forward = new Float64Array(PROFILE_BINS);
	const unlit = new Float64Array(PROFILE_BINS);
	const transmission = new Float64Array(PROFILE_BINS);
	const unlitLuminance = luminance(...UNLIT_TINT);
	const [br, bg, bb] = FORWARD_TINT_BIAS;
	const tint = [0, 0, 0];
	const at = (row: number, i: number) => (row * width + i) * 4;
	for (let k = 0; k < PROFILE_BINS; k++) {
		const from = Math.floor((k * width) / PROFILE_BINS);
		const to = Math.max(from + 1, Math.floor(((k + 1) * width) / PROFILE_BINS));
		const r = inner + ((k + 0.5) / PROFILE_BINS) * (outer - inner);
		for (let i = from; i < to; i++) {
			const c = at(rows.color, i);
			const red = SRGB_TO_LINEAR[pixels[c]];
			const green = SRGB_TO_LINEAR[pixels[c + 1]];
			const blue = SRGB_TO_LINEAR[pixels[c + 2]];
			const opacity = Math.min(1, (1 - pixels[at(rows.transparency, i)] / 255) * intensity);
			const weight = opacity * intensity;
			const backscatter = (pixels[at(rows.backscattered, i)] / 255) * weight;
			back[k] += backscatter * luminance(red, green, blue);
			forward[k] +=
				(pixels[at(rows.forwardscattered, i)] / 255) *
				weight *
				luminance(red * br, green * bg, blue * bb);
			unlit[k] += (pixels[at(rows.unlitside, i)] / 255) * weight * unlitLuminance;
			transmission[k] += 1 - opacity;
			tint[0] += backscatter * red * r;
			tint[1] += backscatter * green * r;
			tint[2] += backscatter * blue * r;
		}
		const n = to - from;
		back[k] /= n;
		forward[k] /= n;
		unlit[k] /= n;
		transmission[k] /= n;
	}
	const tintLuminance = luminance(tint[0], tint[1], tint[2]);
	const litTint =
		tintLuminance > 0
			? new Color(tint[0], tint[1], tint[2]).multiplyScalar(1 / tintLuminance)
			: new Color(1, 1, 1);
	return {
		inner,
		outer,
		back,
		forward,
		unlit,
		transmission,
		litTint,
		bands: equalLightBands(back, unlit, inner, outer)
	};
}

/** Band edges that split the light of both faces in equal parts, as the
 *  planet sees it: light per unit of radius over the radius. */
function equalLightBands(
	back: Float64Array,
	unlit: Float64Array,
	inner: number,
	outer: number
): Int32Array {
	const cumulative = new Float64Array(PROFILE_BINS + 1);
	for (let k = 0; k < PROFILE_BINS; k++) {
		const r = inner + ((k + 0.5) / PROFILE_BINS) * (outer - inner);
		cumulative[k + 1] = cumulative[k] + (back[k] + unlit[k]) / r;
	}
	const total = cumulative[PROFILE_BINS];
	const edges = new Int32Array(RINGSHINE_BANDS + 1);
	edges[RINGSHINE_BANDS] = PROFILE_BINS;
	for (let b = 1; b < RINGSHINE_BANDS; b++) {
		let k = edges[b - 1] + 1;
		while (
			k < PROFILE_BINS - (RINGSHINE_BANDS - b) &&
			cumulative[k] < (total * b) / RINGSHINE_BANDS
		)
			k++;
		edges[b] = k;
	}
	return edges;
}

/** Weight of the forward-scatter profile at the cosine of the phase angle.
 *  CPU port of the blend in the ring shader. */
export function forwardWeight(cosPhase: number): number {
	const t = Math.min(Math.max((cosPhase + 1) / 2, 0), 1);
	return 1 - t * t * (3 - 2 * t);
}

/** True where the planet hides the Sun from the point (`x`, `y`) of the ring plane. */
function inPlanetShadow(
	x: number,
	y: number,
	cosB: number,
	sinB: number,
	planet: Spheroid
): boolean {
	const ox = x / planet.equatorial;
	const oy = y / planet.equatorial;
	const dx = cosB / planet.equatorial;
	const dz = sinB / planet.polar;
	const b = ox * dx;
	if (b >= 0) return false;
	return ox * ox + oy * oy - (b * b) / (dx * dx + dz * dz) < 1;
}

/**
 * Fill `out` (4 values per patch: x, y, the light of the +z face, the light of
 * the −z face) with the ringshine patches of `profile` for the Sun at
 * elevation asin(`sinB`). A light is the radiance of the face toward the
 * planet times the area of the patch. A patch on the x axis is its own
 * mirror and holds half its light.
 */
export function ringshinePatches(
	out: Float64Array,
	profile: RingProfile,
	sinB: number,
	planet: Spheroid
): void {
	const cosB = Math.sqrt(Math.max(0, 1 - sinB * sinB));
	const sunAbove = sinB >= 0;
	const { inner, outer, back, forward, unlit, bands } = profile;
	const dr = (outer - inner) / PROFILE_BINS;
	const sector = (2 * Math.PI) / SECTORS;
	const dPhi = sector / SECTOR_STEPS;
	let p = 0;
	for (let band = 0; band < RINGSHINE_BANDS; band++) {
		for (let k = 0; k <= SECTORS / 2; k++, p++) {
			let above = 0;
			let below = 0;
			let weight = 0;
			let wx = 0;
			let wy = 0;
			for (let s = 0; s < SECTOR_STEPS; s++) {
				const phi = (k - 0.5) * sector + (s + 0.5) * dPhi;
				const c = Math.cos(phi);
				const sn = Math.sin(phi);
				// The phase at the patch, from the Sun to the planet's centre.
				const w = forwardWeight(-cosB * c);
				for (let i = bands[band]; i < bands[band + 1]; i++) {
					const r = inner + (i + 0.5) * dr;
					if (inPlanetShadow(r * c, r * sn, cosB, sinB, planet)) continue;
					const area = r * dr * dPhi;
					const lit = (back[i] + (forward[i] - back[i]) * w) * area;
					const through = unlit[i] * area;
					above += sunAbove ? lit : through;
					below += sunAbove ? through : lit;
					const light = lit + through;
					weight += light;
					wx += light * r * c;
					wy += light * r * Math.abs(sn);
				}
			}
			const share = k === 0 || k === SECTORS / 2 ? 0.5 : 1;
			if (weight > 0) {
				out[4 * p] = wx / weight;
				out[4 * p + 1] = wy / weight;
			} else {
				const r = inner + ((bands[band] + bands[band + 1]) / 2) * dr;
				out[4 * p] = r * Math.cos(k * sector);
				out[4 * p + 1] = r * Math.abs(Math.sin(k * sector));
			}
			out[4 * p + 2] = above * share;
			out[4 * p + 3] = below * share;
		}
	}
}

/**
 * Irradiance of the patches at the point `q` with the unit normal `n`, both in
 * the Sun's frame and from the planet's centre, in the units of the patch
 * light. `mu0` is the sine of the Sun's elevation over the ring plane.
 *
 * CPU port of {@link RINGSHINE_LIGHT}. A change to one must be made in the
 * other. `ring-light.test.ts` is the contract.
 */
export function ringshineAt(
	patches: ArrayLike<number>,
	mu0: number,
	qx: number,
	qy: number,
	qz: number,
	nx: number,
	ny: number,
	nz: number
): number {
	const above = qz >= 0;
	const height = Math.abs(qz);
	const qq = qx * qx + qy * qy + qz * qz;
	const nq = nx * qx + ny * qy + nz * qz;
	let sum = 0;
	for (let i = 0; i < RINGSHINE_PATCHES; i++) {
		const px = patches[4 * i];
		const py = patches[4 * i + 1];
		const light = above ? patches[4 * i + 2] : patches[4 * i + 3];
		const base = qq + px * px + py * py - 2 * px * qx;
		const across = 2 * py * qy;
		const facingBase = px * nx - nq;
		const facingAcross = py * ny;
		for (const sign of [1, -1]) {
			const d2 = base - sign * across;
			const d = Math.sqrt(d2);
			const facing = Math.max(facingBase + sign * facingAcross, 0);
			sum += (light * facing) / (d2 * d * (mu0 * d + height));
		}
	}
	return 2 * mu0 * height * sum;
}

/** Transmission of the ring along the Sun's ray from the point `x`. CPU port
 *  of `ringShadowAt` in rings.ts, without its penumbra. */
function ringTransmission(
	profile: RingProfile,
	x: number,
	y: number,
	z: number,
	cosB: number,
	sinB: number
): number {
	if (Math.abs(sinB) < 1e-6) return 1;
	const t = -z / sinB;
	if (t < 0) return 1;
	const r = Math.hypot(x + t * cosB, y);
	const u = (r - profile.inner) / (profile.outer - profile.inner);
	if (u < 0 || u > 1) return 1;
	const bin = Math.min(Math.floor(u * PROFILE_BINS), PROFILE_BINS - 1);
	return Math.max(profile.transmission[bin], 1e-4) ** (1 / Math.max(Math.abs(sinB), 0.02));
}

const _cells = {
	x: new Float64Array(PLANET_ROWS * PLANET_COLUMNS),
	y: new Float64Array(PLANET_ROWS * PLANET_COLUMNS),
	z: new Float64Array(PLANET_ROWS * PLANET_COLUMNS),
	nx: new Float64Array(PLANET_ROWS * PLANET_COLUMNS),
	ny: new Float64Array(PLANET_ROWS * PLANET_COLUMNS),
	nz: new Float64Array(PLANET_ROWS * PLANET_COLUMNS),
	/** Radiance over the Sun's irradiance, times the area. */
	light: new Float64Array(PLANET_ROWS * PLANET_COLUMNS)
};

/**
 * Fill `out` with the light of the planet on a bundle from `inner` to `outer`,
 * over the Sun's irradiance and per unit of the planet's Lambert albedo. Two
 * values per node, the +z face then the −z face. Nodes go by the cosine of the
 * azimuth from the Sun (1 to −1 in {@link PLANET_LIGHT_AZIMUTHS} steps), then
 * by radius. Even steps in the cosine are fine where the light changes fast.
 * A face takes the light from its own side of the ring plane, from every
 * direction alike, as the rings take the sunlight in the ring shader.
 *
 * The planet's radiance is the Lambert law under the Sun and the shadow of
 * `caster`, plus the ringshine of `patches` on the night side.
 */
export function planetLightOnRing(
	out: Float32Array,
	inner: number,
	outer: number,
	sinB: number,
	planet: Spheroid,
	caster: RingProfile,
	patches: ArrayLike<number>
): void {
	const cosB = Math.sqrt(Math.max(0, 1 - sinB * sinB));
	const mu0 = Math.abs(sinB);
	const { equatorial: a, polar: c } = planet;
	const cells = _cells;
	const dBeta = Math.PI / PLANET_ROWS;
	const dLambda = (2 * Math.PI) / PLANET_COLUMNS;
	for (let row = 0; row < PLANET_ROWS; row++) {
		// Parametric latitude: the point is (a cos β cos λ, a cos β sin λ, c sin β).
		const beta = -Math.PI / 2 + (row + 0.5) * dBeta;
		const cb = Math.cos(beta);
		const sb = Math.sin(beta);
		const area = a * cb * Math.sqrt(c * c * cb * cb + a * a * sb * sb) * dBeta * dLambda;
		for (let col = 0; col < PLANET_COLUMNS; col++) {
			const lambda = (col + 0.5) * dLambda;
			const cl = Math.cos(lambda);
			const sl = Math.sin(lambda);
			const i = row * PLANET_COLUMNS + col;
			const x = a * cb * cl;
			const y = a * cb * sl;
			const z = c * sb;
			let nx = (cb * cl) / a;
			let ny = (cb * sl) / a;
			let nz = sb / c;
			const len = Math.hypot(nx, ny, nz);
			nx /= len;
			ny /= len;
			nz /= len;
			const cosSun = nx * cosB + nz * sinB;
			const day = cosSun > 0 ? cosSun * ringTransmission(caster, x, y, z, cosB, sinB) : 0;
			const night =
				mu0 < RINGSHINE_MIN_MU0
					? 0
					: ringshineAt(patches, mu0, x, y, z, nx, ny, nz) / SUN_LIGHT_INTENSITY;
			cells.x[i] = x;
			cells.y[i] = y;
			cells.z[i] = z;
			cells.nx[i] = nx;
			cells.ny[i] = ny;
			cells.nz[i] = nz;
			cells.light[i] = ((day + night) / Math.PI) * area;
		}
	}

	for (let j = 0; j < PLANET_LIGHT_RADII; j++) {
		const r = inner + (j / (PLANET_LIGHT_RADII - 1)) * (outer - inner);
		for (let k = 0; k < PLANET_LIGHT_AZIMUTHS; k++) {
			const cosPhi = 1 - (2 * k) / (PLANET_LIGHT_AZIMUTHS - 1);
			const px = r * cosPhi;
			const py = r * Math.sqrt(1 - cosPhi * cosPhi);
			let above = 0;
			let below = 0;
			for (let i = 0; i < PLANET_ROWS * PLANET_COLUMNS; i++) {
				const vx = px - cells.x[i];
				const vy = py - cells.y[i];
				const vz = -cells.z[i];
				const d2 = vx * vx + vy * vy + vz * vz;
				// A cell that faces the point is in its view: the planet is convex.
				const facing = cells.nx[i] * vx + cells.ny[i] * vy + cells.nz[i] * vz;
				if (facing <= 0) continue;
				const e = (cells.light[i] * facing) / (d2 * Math.sqrt(d2));
				if (cells.z[i] > 0) above += e;
				else below += e;
			}
			const node = 2 * (j * PLANET_LIGHT_AZIMUTHS + k);
			out[node] = above;
			out[node + 1] = below;
		}
	}
}

/** The light state of one bundle, kept on its ring node. */
export interface RingLight {
	profile: RingProfile;
	/** The ring's planet. Set when the bundle attaches to its body. */
	planet: Spheroid;
	/** {@link planetLightOnRing} as a texture: the cosine of the azimuth along
	 *  x, radius along y. */
	planetLight: DataTexture;
	/** sin B that `planetLight` holds. NaN before the first fill. */
	planetLightSinB: number;
	/** {@link ringshinePatches} of this bundle and the sin B they hold. Only
	 *  the bundle that casts the ring shadow uses them. */
	patches: Float64Array;
	patchesSinB: number;
}

const _grid = new Float32Array(2 * PLANET_LIGHT_AZIMUTHS * PLANET_LIGHT_RADII);

export function makeRingLight(profile: RingProfile): RingLight {
	const texture = new DataTexture(
		new Uint16Array(2 * PLANET_LIGHT_AZIMUTHS * PLANET_LIGHT_RADII),
		PLANET_LIGHT_AZIMUTHS,
		PLANET_LIGHT_RADII,
		RGFormat,
		HalfFloatType
	);
	texture.minFilter = LinearFilter;
	texture.magFilter = LinearFilter;
	texture.wrapS = ClampToEdgeWrapping;
	texture.wrapT = ClampToEdgeWrapping;
	texture.needsUpdate = true;
	return {
		profile,
		planet: { equatorial: 0, polar: 0 },
		planetLight: texture,
		planetLightSinB: NaN,
		patches: new Float64Array(4 * RINGSHINE_PATCHES),
		patchesSinB: NaN
	};
}

/** Fill the planet-light texture of `light` for `sinB`. The patches of
 *  `caster` must hold the same `sinB`. */
export function fillPlanetLight(light: RingLight, sinB: number, caster: RingLight): void {
	planetLightOnRing(
		_grid,
		light.profile.inner,
		light.profile.outer,
		sinB,
		light.planet,
		caster.profile,
		caster.patches
	);
	const data = light.planetLight.image.data as Uint16Array;
	for (let i = 0; i < _grid.length; i++) data[i] = DataUtils.toHalfFloat(_grid[i]);
	light.planetLight.needsUpdate = true;
	light.planetLightSinB = sinB;
}

/**
 * The strongest ringshine of `profile` on `planet`, over the sunlight: the
 * Sun over the pole, at the brightest latitude. A planet whose rings stay
 * under a floor at this level gets no ringshine hook.
 */
export function peakRingshine(profile: RingProfile, planet: Spheroid): number {
	const patches = new Float64Array(4 * RINGSHINE_PATCHES);
	ringshinePatches(patches, profile, 1, planet);
	let peak = 0;
	for (let deg = 2; deg < 90; deg += 2) {
		const beta = (deg * Math.PI) / 180;
		const cb = Math.cos(beta);
		const sb = Math.sin(beta);
		const nx = cb / planet.equatorial;
		const nz = sb / planet.polar;
		const len = Math.hypot(nx, nz);
		const e = ringshineAt(
			patches,
			1,
			planet.equatorial * cb,
			0,
			planet.polar * sb,
			nx / len,
			0,
			nz / len
		);
		peak = Math.max(peak, e / SUN_LIGHT_INTENSITY);
	}
	return peak;
}

const RINGSHINE_PARS = /* glsl */ `
	#define RINGSHINE_PATCHES ${RINGSHINE_PATCHES}
	uniform vec4 uRingshinePatch[RINGSHINE_PATCHES];
	uniform vec3 uRingshineAxis;
	uniform vec3 uRingshineTint[2];
`;

/** Reads the frame, the centre and the world position of the ring shadow's
 *  hook, which the planet always has first. */
const RINGSHINE_LIGHT = /* glsl */ `
	if (uRingshineTint[0].g + uRingshineTint[1].g > 0.0) {
		vec3 q = vRingShadowWorldPos - uRingShadowCenter;
		vec3 axisY = cross(uRingShadowPoleDir, uRingshineAxis);
		float height = dot(q, uRingShadowPoleDir);
		float mu0 = abs(dot(uRingShadowSunDir, uRingShadowPoleDir));
		vec3 n = inverseTransformDirection(geometryNormal, viewMatrix);
		float qx = dot(q, uRingshineAxis);
		float qy = dot(q, axisY);
		float qq = dot(q, q);
		float nx = dot(n, uRingshineAxis);
		float ny = dot(n, axisY);
		float nq = dot(n, q);
		float above = step(0.0, height);
		float absHeight = abs(height);
		float sum = 0.0;
		for (int i = 0; i < RINGSHINE_PATCHES; i++) {
			vec4 p = uRingshinePatch[i];
			float light = mix(p.w, p.z, above);
			float base = qq + dot(p.xy, p.xy) - 2.0 * p.x * qx;
			float across = 2.0 * p.y * qy;
			float facingBase = p.x * nx - nq;
			float facingAcross = p.y * ny;
			// The patch and its mirror at -y.
			vec2 d2 = vec2(base - across, base + across);
			vec2 d = sqrt(d2);
			vec2 facing = max(vec2(facingBase + facingAcross, facingBase - facingAcross), 0.0);
			sum += light * dot(facing, 1.0 / (d2 * d * (mu0 * d + absHeight)));
		}
		vec3 tint = mix(uRingshineTint[1], uRingshineTint[0], above);
		reflectedLight.indirectDiffuse +=
			tint * (2.0 * mu0 * absHeight * sum) * BRDF_Lambert(material.diffuseContribution);
	}
`;

/** Per-frame uniforms of the ringshine on a planet. */
export interface RingshineUniforms {
	/** x, y in the Sun's frame; z, w the light of the +pole and −pole face. */
	uRingshinePatch: { value: Vector4[] };
	/** World unit vector of the Sun's azimuth in the ring plane. */
	uRingshineAxis: { value: Vector3 };
	/** Hue of the +pole and −pole face times the solar distance factor. Both 0
	 *  switch the light off. */
	uRingshineTint: { value: Vector3[] };
	/** Switch the light off when the rings unload. */
	disable: () => void;
}

interface RingshineCarrier {
	ringshine?: RingshineUniforms;
}

/**
 * Attach ringshine to the planet's material. Call it after
 * `attachRingShadowToPlanet`, whose varying and uniforms it reads. The hook
 * stays for the life of the material, as the ring shadow's does.
 */
export function attachRingshine(material: MeshStandardMaterial): RingshineUniforms {
	const carrier = material.userData as RingshineCarrier;
	if (carrier.ringshine) return carrier.ringshine;
	const uniforms: RingshineUniforms = {
		uRingshinePatch: {
			value: Array.from({ length: RINGSHINE_PATCHES }, () => new Vector4())
		},
		uRingshineAxis: { value: new Vector3(1, 0, 0) },
		uRingshineTint: { value: [new Vector3(), new Vector3()] },
		disable: () => {
			for (const tint of uniforms.uRingshineTint.value) tint.set(0, 0, 0);
		}
	};
	chainShaderHook(material, 'ringshine', (shader) => {
		shader.uniforms.uRingshinePatch = uniforms.uRingshinePatch;
		shader.uniforms.uRingshineAxis = uniforms.uRingshineAxis;
		shader.uniforms.uRingshineTint = uniforms.uRingshineTint;
		shader.fragmentShader = shader.fragmentShader
			.replace('#include <common>', `#include <common>\n${RINGSHINE_PARS}`)
			.replace(
				'#include <lights_fragment_end>',
				`#include <lights_fragment_end>\n${RINGSHINE_LIGHT}`
			);
	});
	carrier.ringshine = uniforms;
	return uniforms;
}

/** Write the patches of `light`, the Sun's axis and the face tints to `uniforms`. */
export function writeRingshine(
	uniforms: RingshineUniforms,
	light: RingLight,
	axis: Vector3,
	sinB: number,
	lightScale: number
): void {
	const patches = uniforms.uRingshinePatch.value;
	for (let i = 0; i < RINGSHINE_PATCHES; i++) {
		patches[i].fromArray(light.patches, 4 * i);
	}
	uniforms.uRingshineAxis.value.copy(axis);
	const [above, below] = uniforms.uRingshineTint.value;
	if (Math.abs(sinB) < RINGSHINE_MIN_MU0) {
		above.set(0, 0, 0);
		below.set(0, 0, 0);
		return;
	}
	const lit = light.profile.litTint;
	const unlitLuminance = luminance(...UNLIT_TINT);
	const [litFace, unlitFace] = sinB >= 0 ? [above, below] : [below, above];
	litFace.set(lit.r, lit.g, lit.b).multiplyScalar(lightScale);
	unlitFace.set(...UNLIT_TINT).multiplyScalar(lightScale / unlitLuminance);
}
