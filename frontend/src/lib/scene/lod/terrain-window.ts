import {
	BufferAttribute,
	BufferGeometry,
	Matrix4,
	type Mesh,
	type MeshStandardMaterial,
	type PerspectiveCamera,
	Vector3
} from 'three';
import { tileRoot } from '$lib/fetch/data-base';
import { kmToScene } from '$lib/math/units';
import { setDisplacementScale } from '$lib/scene/objects/surface/displacement';
import { reliefTilesAvailable } from '$lib/scene/objects/surface/relief-tiles';
import { buildTerrainGrid } from '$lib/scene/relief/client';
import { currentRenderTier } from '$lib/scene/render-tier';
import { effectiveRadiusKm } from '$lib/types/objects';
import type { BodyObjects, TilesBlock } from '$lib/scene/types';
import {
	COARSE_SEGS,
	type GridArrays,
	MARGIN,
	SIN_FLOOR,
	buildGridArrays,
	nestedStepLevel,
	planNestedGrid
} from './terrain-grid';

/**
 * Zoom-dependent terrain LOD: swaps the focused body's uniform sphere for a
 * non-uniform lat/lon grid, densified around the camera's sub-surface point.
 * One grid (not an overlay patch) avoids seams and z-fighting, and keeps
 * raycasting/probe seating on `mesh.geometry`.
 *
 * Where the body has height tiles, the grid is built in the relief worker
 * with its heights in its vertices, from the pyramid at 16 bits (see
 * `terrain-grid.ts`). Elsewhere the vertex shader displaces a grid whose
 * finest cells are a texel of the whole-globe height map wide.
 */
export interface TerrainWindowState {
	/** Row angles θ (0..π from +Y pole); column angles φ (0..2π, seam duplicated).
	 *  Probe seating interpolates against these to land on the exact triangle. */
	thetas: Float64Array;
	phis: Float64Array;
	centerTheta: number;
	centerPhi: number;
	/** Window angular half-size, or the finest band's on a grid with its own
	 *  heights; also the recenter-rebuild yardstick. */
	angRadius: number;
	/** Fine step = texel angle × 2^stepLevel; 0 ⇒ texel-perfect (full DEM data). */
	stepLevel: number;
	texWidth: number;
	/** performance.now() of the build — drives the rebuild rate cap. */
	builtAt: number;
	/** Height of each vertex above the sphere, in km, row by row: set on a
	 *  grid that carries its own heights, which the shader then leaves alone. */
	riseKm?: Float32Array;
}

/** Fine cells across the window diameter. Bounds the grid to roughly
 *  (128+257)² ≈ 148k vertices worst-case, and fixes the rebuild cost. */
const CELL_BUDGET = 256;
/** Altitude (fraction of radius) below which the window activates. Higher up,
 *  the budget spread over the visible cap barely beats the coarse grid. */
const ENTER_ALT = 0.25;
const EXIT_ALT = 0.32;
/** Rebuild when the sub-camera point drifts this fraction of the window. */
const RECENTER_FRAC = 0.35;
/** Rebuild rate cap — unthrottled, fast time-speeds can cross the drift
 *  threshold every frame: gigabytes/min of GC churn from fresh grids. */
const REBUILD_MIN_MS = 300;
/** Bail-out: a grid this big means a sizing bug, not a legitimate window. */
const MAX_VERTS = 400_000;

const _inv = new Matrix4();
const _camLocal = new Vector3();

/**
 * Merges the coarse grid with step-aligned fine points inside `intervals`.
 * Fine points sit at absolute multiples of `step`, so a recentered rebuild
 * at the same level reproduces identical vertices — no swimming, and
 * probe-seat caching stays valid across pans.
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

function gridGeometry(grid: GridArrays): BufferGeometry {
	const geometry = new BufferGeometry();
	geometry.setAttribute('position', new BufferAttribute(grid.positions, 3));
	geometry.setAttribute('normal', new BufferAttribute(grid.normals, 3));
	geometry.setAttribute('uv', new BufferAttribute(grid.uvs, 2));
	geometry.setIndex(new BufferAttribute(grid.indices, 1));
	return geometry;
}

/** A grid on its way from the relief worker, per body. */
interface TiledState {
	abort?: AbortController;
	failures: number;
	/** The worker could not build this body's grid; the shader displaces instead. */
	dead: boolean;
}

const tiledStates = new WeakMap<BodyObjects, TiledState>();

/** Failed builds after which the body's grid is left to the shader. */
const MAX_BUILD_FAILURES = 2;

/** The height pyramid that this body's grid takes its heights from, if any. */
function heightTilesOf(bo: BodyObjects): TilesBlock | undefined {
	const tiles = bo.displacementMeta?.tiles;
	return reliefTilesAvailable(tiles) && !tiledStates.get(bo)?.dead ? tiles : undefined;
}

/** Hand the heights back to the shader. */
function restoreDisplacement(bo: BodyObjects): void {
	if (!bo.mesh || !bo.displacementMeta) return;
	setDisplacementScale(
		bo.mesh.material as MeshStandardMaterial,
		bo.displacementMeta,
		bo.radiusScene
	);
}

function exitWindow(bo: BodyObjects): void {
	const state = tiledStates.get(bo);
	state?.abort?.abort();
	if (state) state.abort = undefined;
	if (!bo.terrainWindow) return;
	if (bo.terrainWindow.riseKm) restoreDisplacement(bo);
	bo.terrainWindow = null;
	// Undefined forces the uniform sphere-LOD path to rebuild this same frame.
	bo.currentSegments = undefined;
}

/** Great-circle angle between two points given as θ and φ. */
function drift(thetaA: number, phiA: number, thetaB: number, phiB: number): number {
	const cos =
		Math.sin(thetaA) * Math.sin(thetaB) * Math.cos(phiA - phiB) +
		Math.cos(thetaA) * Math.cos(thetaB);
	return Math.acos(Math.min(1, Math.max(-1, cos)));
}

/**
 * The window of a body with height tiles: ask the relief worker for a grid
 * around the camera when the one in place no longer fits, and put it on the
 * mesh when it comes. Returns whether such a grid is on the mesh.
 */
function updateTiledWindow(
	bo: BodyObjects,
	mesh: Mesh,
	tiles: TilesBlock,
	altitude: number,
	centerTheta: number,
	centerPhi: number,
	invalidate: () => void
): boolean {
	const held = bo.terrainWindow?.riseKm ? bo.terrainWindow : undefined;
	const material = mesh.material as MeshStandardMaterial;
	if (held) {
		// Each frame: a height map loaded again sets its own scale.
		material.displacementScale = 0;
		material.displacementBias = 0;
	}
	const state = tiledStates.get(bo) ?? { failures: 0, dead: false };
	tiledStates.set(bo, state);
	if (state.abort) return !!held;

	const meta = bo.displacementMeta;
	if (!meta) return !!held;
	const bandCells = currentRenderTier().terrainBandCells;
	const stepLevel = nestedStepLevel(altitude, tiles.max_level, bandCells, held?.stepLevel);
	if (held) {
		const still = drift(centerTheta, centerPhi, held.centerTheta, held.centerPhi);
		if (held.stepLevel === stepLevel && still < RECENTER_FRAC * held.angRadius) return true;
		// Rate cap: lagging a spinning body briefly beats rebuilding every frame.
		if (performance.now() - held.builtAt < REBUILD_MIN_MS) return true;
	}

	const radiusKm = effectiveRadiusKm(bo.body.data);
	const grid = planNestedGrid(
		centerTheta,
		centerPhi,
		altitude,
		// The map's range is the relief from its lowest to its highest point.
		(0.5 * meta.scale_km) / radiusKm,
		tiles.max_level,
		bandCells,
		stepLevel
	);
	const thetas = grid.rows.at;
	const phis = grid.columns.at;
	if (thetas.length * phis.length > MAX_VERTS) {
		console.warn(
			`terrain grid for ${bo.body.data.id} would need ${thetas.length}×${phis.length} vertices: left to the shader`
		);
		state.dead = true;
		return !!held;
	}

	const abort = new AbortController();
	state.abort = abort;
	const asked = performance.now();
	buildTerrainGrid(
		{
			root: tileRoot(tiles),
			version: tiles.version,
			tileSize: tiles.tile_size,
			scaleKm: tiles.scale_km ?? 0,
			biasKm: (tiles.bias_km ?? 0) - (meta.absolute_radius ? radiusKm : 0),
			radius: kmToScene(radiusKm),
			unitsPerKm: kmToScene(1),
			rows: grid.rows,
			columns: grid.columns
		},
		abort.signal
	)
		.then((built) => {
			if (state.abort !== abort) return;
			state.abort = undefined;
			state.failures = 0;
			// The mesh went, or lost its height map, while the grid was built.
			if (bo.mesh !== mesh || !bo.displacementMap) return;
			const old = mesh.geometry;
			mesh.geometry = gridGeometry(built);
			old.dispose();
			material.displacementScale = 0;
			material.displacementBias = 0;
			bo.terrainWindow = {
				thetas,
				phis,
				centerTheta,
				centerPhi,
				angRadius: grid.innerRadius,
				stepLevel,
				texWidth: 2048 * 2 ** tiles.max_level,
				builtAt: performance.now(),
				riseKm: built.riseKm
			};
			bo.currentSegments = COARSE_SEGS;
			console.debug(
				`terrain grid ${bo.body.data.id}: ${thetas.length}×${phis.length}, level ${stepLevel}, ${Math.round(performance.now() - asked)} ms`
			);
			invalidate();
		})
		.catch(() => {
			if (state.abort !== abort) return;
			state.abort = undefined;
			if (++state.failures >= MAX_BUILD_FAILURES) state.dead = true;
		});
	return !!held;
}

/**
 * Owns the focused terrain body's geometry while the camera is close.
 * Returns true when window mode is active (sphere-LOD must skip the body).
 */
export function updateTerrainWindow(
	bo: BodyObjects,
	camera: PerspectiveCamera,
	eligible: boolean,
	invalidate: () => void
): boolean {
	const mesh = bo.mesh;
	const tex = bo.displacementMap;
	if (!eligible || !mesh || !tex) {
		if (bo.terrainWindow)
			console.debug(
				`terrain window exit ${bo.body.data.id}: eligible=${eligible} mesh=${!!mesh} tex=${!!tex}`
			);
		exitWindow(bo);
		return false;
	}

	// Camera in mesh-local space (body-fixed, pre-triaxial-scale) — the grid is a sphere of the base radius.
	mesh.updateMatrixWorld();
	_inv.copy(mesh.matrixWorld).invert();
	_camLocal.copy(camera.position).applyMatrix4(_inv);
	const geomRadius = kmToScene(effectiveRadiusKm(bo.body.data));
	const dist = _camLocal.length();
	// Altitude over the mean radius can go negative on low terrain (Elysium/Gale
	// sit below it) — floored, not bailed, else the window dies at ground level.
	const alt = Math.max(dist / geomRadius - 1, 1e-6);
	if (alt > (bo.terrainWindow ? EXIT_ALT : ENTER_ALT)) {
		if (bo.terrainWindow)
			console.debug(`terrain window exit ${bo.body.data.id}: alt=${alt.toFixed(4)}`);
		exitWindow(bo);
		return false;
	}

	const centerTheta = Math.acos(Math.min(1, Math.max(-1, _camLocal.y / dist)));
	let centerPhi = Math.atan2(_camLocal.z, -_camLocal.x);
	if (centerPhi < 0) centerPhi += 2 * Math.PI;

	const tiles = heightTilesOf(bo);
	if (tiles) return updateTiledWindow(bo, mesh, tiles, alt, centerTheta, centerPhi, invalidate);
	// The worker gave this body up with its grid on the mesh.
	if (bo.terrainWindow?.riseKm) restoreDisplacement(bo);

	const image = tex.image as { width?: number } | undefined;
	const texWidth = image?.width ?? 2048;
	const texelAng = (2 * Math.PI) / texWidth;
	const horizon = Math.acos(1 / (1 + alt));
	const rawStep = Math.max(texelAng, (2 * horizon * MARGIN) / CELL_BUDGET);
	const rawLevel = Math.log2(rawStep / texelAng);
	let stepLevel = Math.max(0, Math.ceil(rawLevel - 1e-9));

	const w = bo.terrainWindow;
	// Hysteresis: avoid flip-flopping rebuilds at a power-of-two boundary.
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

	if (w && w.texWidth === texWidth) {
		if (w.stepLevel === stepLevel) {
			const still = drift(centerTheta, centerPhi, w.centerTheta, w.centerPhi);
			if (still < RECENTER_FRAC * w.angRadius) return true;
		}
		// Rate cap: lagging a spinning body briefly beats rebuilding every frame.
		if (performance.now() - w.builtAt < REBUILD_MIN_MS) return true;
	}

	const thetaLo = Math.max(0, centerTheta - angRadius);
	const thetaHi = Math.min(Math.PI, centerTheta + angRadius);
	const thetas = mergeAxis(Math.PI, [[thetaLo, thetaHi]], step);

	// Half-width grows by 1/sin(lat) to hold ground coverage at latitude; the sin
	// floor bounds polar windows, and the column step re-quantizes against the budget.
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
	mesh.geometry = gridGeometry(buildGridArrays(geomRadius, thetas, phis));
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
