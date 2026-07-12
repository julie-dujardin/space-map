import { BufferAttribute, BufferGeometry, Matrix4, type PerspectiveCamera, Vector3 } from 'three';
import { kmToScene } from '$lib/math/units';
import { effectiveRadiusKm } from '$lib/types/objects';
import type { BodyObjects } from '$lib/scene/types';

/**
 * Zoom-dependent terrain LOD for displacement-mapped bodies. Below a threshold
 * altitude the focused body's uniform sphere is swapped for a single watertight
 * lat/lon grid: coarse globally, densified inside a window around the camera's
 * sub-surface point — sized to the visible horizon cap, down to one cell per
 * DEM texel when fully zoomed in (e.g. onto a landed probe). One non-uniform
 * grid instead of an overlay patch: no seams, no z-fighting, and raycasting /
 * probe seating keep working off `mesh.geometry`.
 */
export interface TerrainWindowState {
	/** Grid row angles (θ from the +Y pole, ascending 0..π) and column angles
	 *  (φ ascending 0..2π, seam duplicated) — the probe-seating interpolation
	 *  reads these to land on the exact rendered triangle. */
	thetas: Float64Array;
	phis: Float64Array;
	centerTheta: number;
	centerPhi: number;
	/** Window angular half-size; also the recenter-rebuild yardstick. */
	angRadius: number;
	/** Fine step = texel angle × 2^stepLevel; 0 ⇒ texel-perfect (full DEM data). */
	stepLevel: number;
	texWidth: number;
	/** performance.now() of the build — drives the rebuild rate cap. */
	builtAt: number;
}

/** Global grid density outside the window (matches the top sphere-LOD tier). */
const COARSE_SEGS = 128;
/** Fine cells across the window diameter. Bounds the grid to roughly
 *  (128+257)² ≈ 148k vertices worst-case, and fixes the rebuild cost. */
const CELL_BUDGET = 256;
/** Altitude (fraction of radius) below which the window activates. Higher up,
 *  the budget spread over the visible cap barely beats the coarse grid. */
const ENTER_ALT = 0.25;
const EXIT_ALT = 0.32;
/** Rebuild when the sub-camera point drifts this fraction of the window. */
const RECENTER_FRAC = 0.35;
/** Rebuild rate cap. Fast time-speeds spin the body under the camera, so the
 *  body-fixed sub-point can cross the drift threshold every frame — unthrottled
 *  that's a fresh ~100k-vertex grid per frame, gigabytes/min of GC churn. */
const REBUILD_MIN_MS = 300;
/** Window reach past the horizon: covers peaks visible from beyond it. */
const MARGIN = 1.25;
/** sin(lat) floor for the longitude half-width; keeps polar windows bounded. */
const SIN_FLOOR = 0.05;
/** Bail-out: a grid this big means a sizing bug, not a legitimate window. */
const MAX_VERTS = 400_000;

const _inv = new Matrix4();
const _camLocal = new Vector3();

/**
 * Union of the coarse grid and step-aligned fine points inside `intervals`,
 * ascending over [0, max]. Coarse points strictly inside a fine interval are
 * dropped so cell widths stay clean; endpoints always survive. Fine points sit
 * at absolute multiples of `step`, so a recentered rebuild at the same level
 * reproduces identical vertices (no swimming, and probe-seat caching stays
 * valid across pans).
 */
function mergeAxis(max: number, intervals: [number, number][], step: number): Float64Array {
	const inFine = (p: number) => intervals.some(([lo, hi]) => p > lo + 1e-9 && p < hi - 1e-9);
	const coarseStep = max / COARSE_SEGS;
	const pts: number[] = [];
	for (let j = 0; j <= COARSE_SEGS; j++) {
		const p = j === COARSE_SEGS ? max : j * coarseStep;
		if (j === 0 || j === COARSE_SEGS || !inFine(p)) pts.push(p);
	}
	for (const [lo, hi] of intervals) {
		const n0 = Math.ceil(Math.max(lo, 0) / step - 1e-9);
		const n1 = Math.floor(Math.min(hi, max) / step + 1e-9);
		for (let n = n0; n <= n1; n++) pts.push(n * step);
	}
	pts.sort((a, b) => a - b);
	const tol = step * 0.25;
	const out: number[] = [];
	for (const p of pts) {
		if (out.length && p - out[out.length - 1] < tol) continue;
		out.push(p);
	}
	// A fine point within `tol` of an endpoint swallows it in the dedupe — snap back.
	out[0] = 0;
	out[out.length - 1] = max;
	return Float64Array.from(out);
}

/** Non-uniform lat/lon sphere grid mirroring `SphereGeometry`'s parametrization
 *  (positions, UVs, winding, pole handling), so displacement/self-shadow and
 *  the landed-probe triangle interpolation carry over unchanged. */
function buildGridGeometry(
	radius: number,
	thetas: Float64Array,
	phis: Float64Array
): BufferGeometry {
	const rows = thetas.length;
	const cols = phis.length;
	const positions = new Float32Array(rows * cols * 3);
	const normals = new Float32Array(rows * cols * 3);
	const uvs = new Float32Array(rows * cols * 2);
	for (let iy = 0; iy < rows; iy++) {
		const theta = thetas[iy];
		const sinT = Math.sin(theta);
		const cosT = Math.cos(theta);
		for (let ix = 0; ix < cols; ix++) {
			const phi = phis[ix];
			const nx = -Math.cos(phi) * sinT;
			const ny = cosT;
			const nz = Math.sin(phi) * sinT;
			const i3 = (iy * cols + ix) * 3;
			positions[i3] = radius * nx;
			positions[i3 + 1] = radius * ny;
			positions[i3 + 2] = radius * nz;
			normals[i3] = nx;
			normals[i3 + 1] = ny;
			normals[i3 + 2] = nz;
			const i2 = (iy * cols + ix) * 2;
			uvs[i2] = phi / (2 * Math.PI);
			uvs[i2 + 1] = 1 - theta / Math.PI;
		}
	}
	const indices = new Uint32Array((rows - 1) * (cols - 1) * 6);
	let k = 0;
	for (let iy = 0; iy < rows - 1; iy++) {
		const topPole = thetas[iy] <= 0;
		const bottomPole = thetas[iy + 1] >= Math.PI;
		for (let ix = 0; ix < cols - 1; ix++) {
			const a = iy * cols + ix + 1;
			const b = iy * cols + ix;
			const c = (iy + 1) * cols + ix;
			const d = (iy + 1) * cols + ix + 1;
			if (!topPole) {
				indices[k++] = a;
				indices[k++] = b;
				indices[k++] = d;
			}
			if (!bottomPole) {
				indices[k++] = b;
				indices[k++] = c;
				indices[k++] = d;
			}
		}
	}
	const geometry = new BufferGeometry();
	geometry.setAttribute('position', new BufferAttribute(positions, 3));
	geometry.setAttribute('normal', new BufferAttribute(normals, 3));
	geometry.setAttribute('uv', new BufferAttribute(uvs, 2));
	geometry.setIndex(new BufferAttribute(indices.subarray(0, k), 1));
	return geometry;
}

function exitWindow(bo: BodyObjects): void {
	if (!bo.terrainWindow) return;
	bo.terrainWindow = null;
	// Undefined forces the uniform sphere-LOD path to rebuild this same frame.
	bo.currentSegments = undefined;
}

/**
 * Own the focused terrain body's geometry while the camera is close. Returns
 * true when window mode is active (the uniform sphere-LOD swap must skip the
 * body). `eligible` false tears the window down.
 */
export function updateTerrainWindow(
	bo: BodyObjects,
	camera: PerspectiveCamera,
	eligible: boolean
): boolean {
	const mesh = bo.mesh;
	const tex = bo.displacementMap;
	if (!eligible || !mesh || !tex) {
		exitWindow(bo);
		return false;
	}

	// Camera in geometry space (mesh-local: body-fixed, pre-triaxial-scale),
	// where the grid is a sphere of the base radius.
	mesh.updateMatrixWorld();
	_inv.copy(mesh.matrixWorld).invert();
	_camLocal.copy(camera.position).applyMatrix4(_inv);
	const geomRadius = kmToScene(effectiveRadiusKm(bo.body.data));
	const dist = _camLocal.length();
	// Altitude over the *mean* radius can go negative on low-lying terrain
	// (Elysium/Gale sit km below it) — floor it instead of bailing, else the
	// window tears down right at a landed probe's ground level.
	const alt = Math.max(dist / geomRadius - 1, 1e-6);
	if (alt > (bo.terrainWindow ? EXIT_ALT : ENTER_ALT)) {
		exitWindow(bo);
		return false;
	}

	const image = tex.image as { width?: number } | undefined;
	const texWidth = image?.width ?? 2048;
	const texelAng = (2 * Math.PI) / texWidth;
	const horizon = Math.acos(1 / (1 + alt));
	const rawStep = Math.max(texelAng, (2 * horizon * MARGIN) / CELL_BUDGET);
	const rawLevel = Math.log2(rawStep / texelAng);
	let stepLevel = Math.max(0, Math.ceil(rawLevel - 1e-9));

	const w = bo.terrainWindow;
	// Level hysteresis: hovering at a power-of-two boundary must not flip-flop
	// rebuilds. Slightly over-shooting the current level only shaves the margin.
	if (
		w &&
		w.texWidth === texWidth &&
		rawLevel > w.stepLevel - 0.85 &&
		rawLevel < w.stepLevel + 0.15
	) {
		stepLevel = w.stepLevel;
	}
	const step = texelAng * 2 ** stepLevel;
	const angRadius = (step * CELL_BUDGET) / 2;

	const centerTheta = Math.acos(Math.min(1, Math.max(-1, _camLocal.y / dist)));
	let centerPhi = Math.atan2(_camLocal.z, -_camLocal.x);
	if (centerPhi < 0) centerPhi += 2 * Math.PI;

	if (w && w.texWidth === texWidth) {
		if (w.stepLevel === stepLevel) {
			// Great-circle drift of the sub-camera point since the last rebuild.
			const cosDrift =
				Math.sin(centerTheta) * Math.sin(w.centerTheta) * Math.cos(centerPhi - w.centerPhi) +
				Math.cos(centerTheta) * Math.cos(w.centerTheta);
			if (Math.acos(Math.min(1, Math.max(-1, cosDrift))) < RECENTER_FRAC * w.angRadius) return true;
		}
		// Rate cap: lagging a spinning body briefly beats rebuilding every frame.
		if (performance.now() - w.builtAt < REBUILD_MIN_MS) return true;
	}

	const thetaLo = Math.max(0, centerTheta - angRadius);
	const thetaHi = Math.min(Math.PI, centerTheta + angRadius);
	const thetas = mergeAxis(Math.PI, [[thetaLo, thetaHi]], step);

	// Longitude half-width grows by 1/sin(lat) so ground coverage holds at the
	// window's latitude; the sin floor keeps polar windows from wrapping the
	// full 2π at fine density. The column step re-quantizes against the budget
	// (near poles equirect columns oversample the ground anyway).
	const halfWidth = Math.min(Math.PI, angRadius / Math.max(Math.sin(centerTheta), SIN_FLOOR));
	const phiLevel = Math.max(
		stepLevel,
		Math.ceil(Math.log2((2 * halfWidth) / CELL_BUDGET / texelAng) - 1e-9)
	);
	const phiStep = texelAng * 2 ** Math.max(0, phiLevel);
	const lo = centerPhi - halfWidth;
	const hi = centerPhi + halfWidth;
	const phiIntervals: [number, number][] =
		halfWidth >= Math.PI
			? [[0, 2 * Math.PI]]
			: lo < 0
				? [
						[0, hi],
						[lo + 2 * Math.PI, 2 * Math.PI]
					]
				: hi > 2 * Math.PI
					? [
							[0, hi - 2 * Math.PI],
							[lo, 2 * Math.PI]
						]
					: [[lo, hi]];
	const phis = mergeAxis(2 * Math.PI, phiIntervals, phiStep);

	if (thetas.length * phis.length > MAX_VERTS) {
		console.warn(
			`terrain window for ${bo.body.data.id} would need ${thetas.length}×${phis.length} vertices — keeping the uniform sphere`
		);
		exitWindow(bo);
		return false;
	}

	const old = mesh.geometry;
	mesh.geometry = buildGridGeometry(geomRadius, thetas, phis);
	old.dispose();
	console.debug(
		`terrain window ${bo.body.data.id}: ${thetas.length}×${phis.length} grid, level ${stepLevel} (tex ${texWidth})`
	);
	bo.terrainWindow = {
		thetas,
		phis,
		centerTheta,
		centerPhi,
		angRadius,
		stepLevel,
		texWidth,
		builtAt: performance.now()
	};
	bo.currentSegments = COARSE_SEGS;
	return true;
}
