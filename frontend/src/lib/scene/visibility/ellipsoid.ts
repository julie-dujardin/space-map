import { Quaternion, Vector3, type Matrix4 } from 'three';
import type { ScreenOccluder } from '../label/culling';

/**
 * Oblate-body silhouette math. A triaxial body is an ellipsoid, not a sphere;
 * normalizing it to a unit sphere with the affine map A = R·diag(a) turns the
 * label-occlusion and anchor problems back into the sphere case we already
 * solve. Both the screen occluder and the label anchor are derived from the
 * body's camera-space principal axes + semi-axes here.
 */

const _e0 = new Vector3();
const _e1 = new Vector3();
const _e2 = new Vector3();
const _axes: [Vector3, Vector3, Vector3] = [_e0, _e1, _e2];

export type EllipsoidAxes = { e: [Vector3, Vector3, Vector3]; a: [number, number, number] };

/**
 * Camera-space principal axes (unit) + semi-axes (scene units) of a body whose
 * mesh carries SPICE triaxial radii. The returned vectors alias module scratch —
 * consume them before the next call. `a` is the mesh-local x/y/z semi-axis order
 * ({@link BodyObjects.semiAxesScene}), matching `e`.
 */
export function ellipsoidCameraAxes(
	meshWorldQuat: Quaternion,
	view: Matrix4,
	semiAxesScene: [number, number, number]
): EllipsoidAxes {
	_e0.set(1, 0, 0).applyQuaternion(meshWorldQuat).transformDirection(view);
	_e1.set(0, 1, 0).applyQuaternion(meshWorldQuat).transformDirection(view);
	_e2.set(0, 0, 1).applyQuaternion(meshWorldQuat).transformDirection(view);
	return { e: _axes, a: semiAxesScene };
}

/** Fill an occluder for an isotropic body — principal axes are the camera axes. */
export function setSphereOccluder(
	occ: ScreenOccluder,
	camX: number,
	camY: number,
	camZ: number,
	r: number,
	projScale: number,
	halfW: number,
	halfH: number,
	id: string,
	dist: number
): void {
	const ir = 1 / r;
	occ.gxx = ir;
	occ.gxy = 0;
	occ.gxz = 0;
	occ.gyx = 0;
	occ.gyy = ir;
	occ.gyz = 0;
	occ.gzx = 0;
	occ.gzy = 0;
	occ.gzz = ir;
	occ.cpx = camX * ir;
	occ.cpy = camY * ir;
	occ.cpz = camZ * ir;
	occ.K = (camX * camX + camY * camY + camZ * camZ) * ir * ir - 1;
	occ.cx0 = halfW;
	occ.cy0 = halfH;
	occ.f = projScale;
	occ.id = id;
	occ.dist = dist;
}

/** Fill an occluder for an ellipsoid — the cone test runs in normalized space
 *  via the scaled principal axes gᵢ = eᵢ/aᵢ and center c' = (c·eᵢ/aᵢ). */
export function setEllipsoidOccluder(
	occ: ScreenOccluder,
	camX: number,
	camY: number,
	camZ: number,
	ax: EllipsoidAxes,
	projScale: number,
	halfW: number,
	halfH: number,
	id: string,
	dist: number
): void {
	const [e0, e1, e2] = ax.e;
	const [a0, a1, a2] = ax.a;
	occ.gxx = e0.x / a0;
	occ.gxy = e0.y / a0;
	occ.gxz = e0.z / a0;
	occ.gyx = e1.x / a1;
	occ.gyy = e1.y / a1;
	occ.gyz = e1.z / a1;
	occ.gzx = e2.x / a2;
	occ.gzy = e2.y / a2;
	occ.gzz = e2.z / a2;
	const cpx = (camX * e0.x + camY * e0.y + camZ * e0.z) / a0;
	const cpy = (camX * e1.x + camY * e1.y + camZ * e1.z) / a1;
	const cpz = (camX * e2.x + camY * e2.y + camZ * e2.z) / a2;
	occ.cpx = cpx;
	occ.cpy = cpy;
	occ.cpz = cpz;
	occ.K = cpx * cpx + cpy * cpy + cpz * cpz - 1;
	occ.cx0 = halfW;
	occ.cy0 = halfH;
	occ.f = projScale;
	occ.id = id;
	occ.dist = dist;
}

/**
 * Camera-space xy offset placing a label at the body's projected silhouette
 * center. The tangent cone T(X) = g·(XᵀMX) − (pᵀX)² (M = Σ aᵢ⁻²eᵢeᵢᵀ, p = Mc,
 * g = cᵀMc − 1) cuts the image plane z = −f in a conic; its center is the
 * silhouette center, back-projected to the body's depth. Reduces exactly to the
 * sphere β-offset when the axes are equal. Returns into `out` (ox, oy).
 */
export function ellipsoidAnchorOffset(
	camX: number,
	camY: number,
	camZ: number,
	ax: EllipsoidAxes,
	projScale: number,
	out: { ox: number; oy: number }
): void {
	const [e0, e1, e2] = ax.e;
	const [a0, a1, a2] = ax.a;
	const w0 = 1 / (a0 * a0);
	const w1 = 1 / (a1 * a1);
	const w2 = 1 / (a2 * a2);
	// M = Σ wᵢ eᵢeᵢᵀ (symmetric: m00,m01,m02,m11,m12,m22).
	const m00 = w0 * e0.x * e0.x + w1 * e1.x * e1.x + w2 * e2.x * e2.x;
	const m01 = w0 * e0.x * e0.y + w1 * e1.x * e1.y + w2 * e2.x * e2.y;
	const m02 = w0 * e0.x * e0.z + w1 * e1.x * e1.z + w2 * e2.x * e2.z;
	const m11 = w0 * e0.y * e0.y + w1 * e1.y * e1.y + w2 * e2.y * e2.y;
	const m12 = w0 * e0.y * e0.z + w1 * e1.y * e1.z + w2 * e2.y * e2.z;
	const m22 = w0 * e0.z * e0.z + w1 * e1.z * e1.z + w2 * e2.z * e2.z;
	const p0 = m00 * camX + m01 * camY + m02 * camZ;
	const p1 = m01 * camX + m11 * camY + m12 * camZ;
	const p2 = m02 * camX + m12 * camY + m22 * camZ;
	const g = camX * p0 + camY * p1 + camZ * p2 - 1;
	const f = projScale;
	// Conic A x² + B xy + C y² + D x + E y + F on plane z = −f.
	const A = g * m00 - p0 * p0;
	const B = 2 * (g * m01 - p0 * p1);
	const C = g * m11 - p1 * p1;
	const D = -2 * f * (g * m02 - p0 * p2);
	const E = -2 * f * (g * m12 - p1 * p2);
	const det = 4 * A * C - B * B;
	const xs = (-2 * C * D + B * E) / det; // plane-x of center
	const ys = (-2 * A * E + B * D) / det; // plane-y (camera y-up)
	// Back-project the on-plane center to the body's depth as a local xy offset.
	const k = -camZ / f;
	out.ox = xs * k - camX;
	out.oy = ys * k - camY;
}
