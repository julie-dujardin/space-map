/** 3-vector helpers for trajectory math; tuples match the orbit/position code's convention. */

export type Vec3 = readonly [number, number, number];

export function add(a: Vec3, b: Vec3): Vec3 {
	return [a[0] + b[0], a[1] + b[1], a[2] + b[2]];
}

export function sub(a: Vec3, b: Vec3): Vec3 {
	return [a[0] - b[0], a[1] - b[1], a[2] - b[2]];
}

export function scale(a: Vec3, k: number): Vec3 {
	return [a[0] * k, a[1] * k, a[2] * k];
}

export function dot(a: Vec3, b: Vec3): number {
	return a[0] * b[0] + a[1] * b[1] + a[2] * b[2];
}

export function cross(a: Vec3, b: Vec3): Vec3 {
	return [a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0]];
}

export function norm(a: Vec3): number {
	return Math.hypot(a[0], a[1], a[2]);
}

/** Returns [0,0,0] for a zero-length input; callers that care must check. */
export function normalize(a: Vec3): Vec3 {
	const n = norm(a);
	return n === 0 ? [0, 0, 0] : [a[0] / n, a[1] / n, a[2] / n];
}

export function isFiniteVec(a: Vec3): boolean {
	return isFinite(a[0]) && isFinite(a[1]) && isFinite(a[2]);
}

/** Any unit vector at right angles to `n`, for a choice that is free. */
export function perpendicularTo(n: Vec3): Vec3 {
	const axis: Vec3 = Math.abs(n[0]) < 0.9 ? [1, 0, 0] : [0, 1, 0];
	return normalize(cross(n, axis));
}
