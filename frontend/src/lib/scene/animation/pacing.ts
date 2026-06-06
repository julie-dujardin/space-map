/**
 * Distance-aware durations so camera animations feel like constant speed rather
 * than constant time. A 90° rotation should take roughly twice as long as a 45°
 * one; a fly across the system should take longer than a hop between sister
 * moons — but log-scaled and clamped so 1000× the distance isn't 1000× the time.
 */

export interface AngularPacing {
	/** Duration at `refAngleRad`; smaller/larger angles scale linearly. */
	refMs: number;
	refAngleRad: number;
	minMs: number;
	maxMs: number;
}

export interface SpatialPacing {
	/** Duration at `refDist`. */
	refMs: number;
	/** Distance (scene units) anchoring `refMs`. */
	refDist: number;
	/** ms added per decade of distance above `refDist` (subtracted below). */
	msPerDecade: number;
	minMs: number;
	maxMs: number;
}

function clamp(x: number, lo: number, hi: number): number {
	return Math.min(Math.max(x, lo), hi);
}

/** Linear-in-angle (constant angular speed), clamped. */
export function angularDuration(angleRad: number, p: AngularPacing): number {
	const a = Math.max(angleRad, 0);
	return clamp((p.refMs * a) / p.refAngleRad, p.minMs, p.maxMs);
}

/** Log-scaled in distance: each ×10 changes duration by `msPerDecade`, clamped. */
export function spatialDuration(distance: number, p: SpatialPacing): number {
	if (!(distance > 0)) return p.minMs;
	const decades = Math.log10(distance / p.refDist);
	return clamp(p.refMs + decades * p.msPerDecade, p.minMs, p.maxMs);
}

/** Rotation-only focus switch (camera stays near current position). */
export const FOCUS_ROT_PACING: AngularPacing = {
	refMs: 350,
	refAngleRad: Math.PI / 3, // 60°
	minMs: 200,
	maxMs: 700
};

/** Camera-up reference flip (ecliptic ↔ body pole ↔ galactic). */
export const UP_PACING: AngularPacing = {
	refMs: 400,
	refAngleRad: Math.PI / 2, // 90°
	minMs: 200,
	maxMs: 800
};

/** Fly translation. Scene units: 1 AU = 10. refDist ~ Earth–Mars at favourable
 *  geometry; a sister-moon hop ends up at minMs, Mercury→Pluto at maxMs. */
export const FLY_TRANS_PACING: SpatialPacing = {
	refMs: 1600,
	refDist: 2,
	msPerDecade: 400,
	minMs: 600,
	maxMs: 2500
};

/** Fly rotation component — combined with the translation term via `max`. */
export const FLY_ROT_PACING: AngularPacing = {
	refMs: 1600,
	refAngleRad: Math.PI / 2, // 90°
	minMs: 600,
	maxMs: 2500
};
