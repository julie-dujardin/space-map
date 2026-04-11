export type Vec3 = [number, number, number];

export function f64lerp(a: Vec3, b: Vec3, t: number): Vec3 {
	return [a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t, a[2] + (b[2] - a[2]) * t];
}

export function f64dist(a: Vec3, b: Vec3): number {
	const dx = a[0] - b[0],
		dy = a[1] - b[1],
		dz = a[2] - b[2];
	return Math.sqrt(dx * dx + dy * dy + dz * dz);
}
