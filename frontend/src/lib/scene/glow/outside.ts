/**
 * The map about the Galaxy, for a camera far outside it. There the octahedral
 * map spends its texels over empty sky: at 30 kpc the disc takes a few percent
 * of them. This map is a square of the sky about the Galactic centre, as seen
 * from its origin, so its texels are about a screen pixel. Its frame is fixed by
 * the origin and the centre, never by the view, so a turn of the view costs no
 * march. The octahedral map keeps the rest of the sky: the halo and the Clouds.
 *
 * The two blend over a range of distance from the centre, so a flight out shows
 * no step.
 */

import type { Vec3 } from '$lib/scene/dust/octahedral';

/** Radius (pc) about the Galactic centre that the map holds whole. */
export const GALAXY_RADIUS_PC = 18_000;
/** Largest half width of the map: past it a texel at the edge is four at the centre. */
const MAX_HALF_ANGLE = Math.PI / 3;
/** Distances (pc) from the centre over which the map takes over from the octahedral one. */
export const GALAXY_FROM_PC = 16_000;
export const GALAXY_FULL_PC = 24_000;

/** Axes of a map about the Galaxy, on nest axes, and how much of the sky it holds. */
export interface GalaxyFrame {
	/** Right, up and toward the centre, as the columns of a GLSL mat3. */
	axes: Float32Array;
	/** Tangent of the half width of the square. */
	tan: number;
	/** Share of the map in the glow at the centre of its square. */
	share: number;
}

const smooth = (from: number, to: number, x: number): number => {
	const t = Math.min(Math.max((x - from) / (to - from), 0), 1);
	return t * t * (3 - 2 * t);
};

const unit = (v: Vec3): Vec3 => {
	const n = Math.hypot(v[0], v[1], v[2]);
	return [v[0] / n, v[1] / n, v[2] / n];
};

const cross = (a: Vec3, b: Vec3): Vec3 => [
	a[1] * b[2] - a[2] * b[1],
	a[2] * b[0] - a[0] * b[2],
	a[0] * b[1] - a[1] * b[0]
];

/** Up of the map: the Galactic north, or the centre's side away from the Sun
 *  where the map looks along the pole. */
function upOf(forward: Vec3): Vec3 {
	for (const ref of [[0, 0, 1] as Vec3, [-1, 0, 0] as Vec3]) {
		const along = ref[0] * forward[0] + ref[1] * forward[1] + ref[2] * forward[2];
		const up: Vec3 = [
			ref[0] - along * forward[0],
			ref[1] - along * forward[1],
			ref[2] - along * forward[2]
		];
		if (Math.hypot(up[0], up[1], up[2]) > 0.2) return unit(up);
	}
	return [0, 1, 0];
}

/** The frame of a map made at `origin` (pc, nest axes), or null where the
 *  octahedral map holds the sky alone. `centre` is the Galactic centre. */
export function galaxyFrame(origin: Vec3, centre: Vec3): GalaxyFrame | null {
	const to: Vec3 = [centre[0] - origin[0], centre[1] - origin[1], centre[2] - origin[2]];
	const distance = Math.hypot(to[0], to[1], to[2]);
	const share = smooth(GALAXY_FROM_PC, GALAXY_FULL_PC, distance);
	if (share <= 0) return null;
	const forward = unit(to);
	const up = upOf(forward);
	const right = cross(up, forward);
	const sin = Math.min(GALAXY_RADIUS_PC / distance, Math.sin(MAX_HALF_ANGLE));
	return {
		axes: new Float32Array([...right, ...up, ...forward]),
		tan: sin / Math.sqrt(1 - sin * sin),
		share
	};
}
