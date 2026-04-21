const { PI, sin, cos, asin, atan2, sqrt } = Math;
const DEG = 180 / PI;
const RAD = PI / 180;

/**
 * Rotate a 3-vector by a quaternion [x, y, z, w] (or its inverse).
 * Matches three.js convention so callers can pass `mesh.quaternion.toArray()`.
 */
function applyQuat(
	v: [number, number, number],
	q: [number, number, number, number],
	inverse: boolean
): [number, number, number] {
	const [x, y, z] = v;
	const [qx, qy, qz, qw] = inverse ? [-q[0], -q[1], -q[2], q[3]] : q;
	const ix = qw * x + qy * z - qz * y;
	const iy = qw * y + qz * x - qx * z;
	const iz = qw * z + qx * y - qy * x;
	const iw = -qx * x - qy * y - qz * z;
	return [
		ix * qw + iw * -qx + iy * -qz - iz * -qy,
		iy * qw + iw * -qy + iz * -qx - ix * -qz,
		iz * qw + iw * -qz + ix * -qy - iy * -qx
	];
}

/**
 * Camera-relative-to-target → spherical degrees.
 * When `bodyQuat` is given, lat/lon are body-fixed (lat=0, lon=0 ↔ prime meridian
 * on the equator, lon increases east). When omitted, they're scene-frame (Y-up).
 */
export function cartesianToSpherical(
	cam: [number, number, number],
	target: [number, number, number],
	bodyQuat?: [number, number, number, number]
): { latitude: number; longitude: number; distance: number } {
	let dx = cam[0] - target[0];
	let dy = cam[1] - target[1];
	let dz = cam[2] - target[2];
	const distance = sqrt(dx * dx + dy * dy + dz * dz);
	if (bodyQuat) {
		[dx, dy, dz] = applyQuat([dx, dy, dz], bodyQuat, true);
	}
	return {
		latitude: asin(dy / distance) * DEG,
		longitude: bodyQuat
			? atan2(-dz, dx) * DEG // body frame: +X = prime meridian, -Z = east
			: atan2(dx, dz) * DEG,
		distance
	};
}

/**
 * Spherical degrees → world-space camera position.
 * When `bodyQuat` is given, lat/lon are interpreted as body-fixed.
 */
export function sphericalToCartesian(
	target: [number, number, number],
	lat: number,
	lon: number,
	distance: number,
	bodyQuat?: [number, number, number, number]
): [number, number, number] {
	const latR = lat * RAD;
	const lonR = lon * RAD;
	let ox: number;
	let oy: number;
	let oz: number;
	if (bodyQuat) {
		const local: [number, number, number] = [
			distance * cos(latR) * cos(lonR),
			distance * sin(latR),
			-distance * cos(latR) * sin(lonR)
		];
		[ox, oy, oz] = applyQuat(local, bodyQuat, false);
	} else {
		ox = distance * cos(latR) * sin(lonR);
		oy = distance * sin(latR);
		oz = distance * cos(latR) * cos(lonR);
	}
	return [target[0] + ox, target[1] + oy, target[2] + oz];
}
