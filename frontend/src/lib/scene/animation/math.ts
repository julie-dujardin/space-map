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

/**
 * Interpolate from `origin` to `target` along a great-circle arc around `center`:
 * slerp the direction, lerp the radius. Keeps the path at (near-)constant distance
 * from `center` so it never cuts the chord through it. Falls back to a straight lerp
 * when either endpoint is at the center or the two directions are ~collinear.
 */
export function f64slerpArc(origin: Vec3, target: Vec3, center: Vec3, t: number): Vec3 {
	const ox = origin[0] - center[0],
		oy = origin[1] - center[1],
		oz = origin[2] - center[2];
	const tx = target[0] - center[0],
		ty = target[1] - center[1],
		tz = target[2] - center[2];
	const ro = Math.sqrt(ox * ox + oy * oy + oz * oz);
	const rt = Math.sqrt(tx * tx + ty * ty + tz * tz);
	if (ro < 1e-9 || rt < 1e-9) return f64lerp(origin, target, t);
	const oux = ox / ro,
		ouy = oy / ro,
		ouz = oz / ro;
	const tux = tx / rt,
		tuy = ty / rt,
		tuz = tz / rt;
	const dot = Math.max(-1, Math.min(1, oux * tux + ouy * tuy + ouz * tuz));
	const omega = Math.acos(dot);
	const r = ro + (rt - ro) * t; // radius lerps (equal radii → constant distance)
	// Near-collinear (same or opposite direction): slerp axis is unstable, lerp.
	if (omega < 1e-4 || Math.PI - omega < 1e-4) return f64lerp(origin, target, t);
	const sinOmega = Math.sin(omega);
	const a = Math.sin((1 - t) * omega) / sinOmega;
	const b = Math.sin(t * omega) / sinOmega;
	// a*ou + b*tu is unit-length (slerp of unit vectors); scale by the lerped radius.
	const dx = a * oux + b * tux,
		dy = a * ouy + b * tuy,
		dz = a * ouz + b * tuz;
	return [center[0] + dx * r, center[1] + dy * r, center[2] + dz * r];
}
