import { Matrix4, Mesh, Vector3, type Object3D } from 'three';

/**
 * Angular index over a shape model's faces, for radii measured outward from
 * the model's own origin. Scan meshes run to 400k faces, which three's
 * raycaster walks in full — far too slow for a per-frame camera clamp — while
 * a radial ray can only ever hit the faces that cover its own direction.
 *
 * Faces are bucketed by the lat/lon box of their vertices, so a query tests
 * ~a hundred candidates instead of the whole mesh.
 */

/** Grid size: a 400k-face mesh leaves ~90 candidates per cell. */
const LAT_CELLS = 48;
const LON_CELLS = 96;
const CELLS = LAT_CELLS * LON_CELLS;
/** Face slots per mesh, so one int can carry both mesh and face index. */
const MESH_STRIDE = 1 << 24;

interface IndexedMesh {
	/** Vertices in the post-fit model frame, origin at the model's own origin.
	 *  Materialised at build: the source attribute may be quantised (meshopt
	 *  ships normalised int16), and baking the transform keeps queries to plain
	 *  float reads. */
	verts: Float32Array;
	idx: ArrayLike<number> | null;
	faces: number;
}

export interface RadialIndex {
	meshes: IndexedMesh[];
	/** CSR offsets into `slots`, one per cell plus the end. */
	start: Int32Array;
	slots: Int32Array;
}

const TWO_PI = Math.PI * 2;

/** Bands of equal `y` rather than equal latitude: equal area, so cells hold
 *  similar face counts, and no arcsine in the build's inner loop. */
function latCell(y: number): number {
	const i = Math.floor(((y + 1) / 2) * LAT_CELLS);
	return Math.min(LAT_CELLS - 1, Math.max(0, i));
}

/** Longitude runs the body-fixed convention: +x at 0, −z at +90°. */
function lonCell(x: number, z: number): number {
	const lon = Math.atan2(-z, x);
	const i = Math.floor(((lon + Math.PI) / TWO_PI) * LON_CELLS);
	return ((i % LON_CELLS) + LON_CELLS) % LON_CELLS;
}

const _v = new Vector3();

/** Per-vertex cell ids (packed `lat * LON_CELLS + lon`) and unit directions,
 *  which the widening below needs for faces too big for their vertex box. */
function vertexCells(m: IndexedMesh): { cells: Int32Array; dirs: Float32Array } {
	const n = m.verts.length / 3;
	const cells = new Int32Array(n);
	const dirs = new Float32Array(n * 3);
	for (let i = 0; i < n; i++) {
		_v.set(m.verts[i * 3], m.verts[i * 3 + 1], m.verts[i * 3 + 2]).normalize();
		dirs[i * 3] = _v.x;
		dirs[i * 3 + 1] = _v.y;
		dirs[i * 3 + 2] = _v.z;
		cells[i] = latCell(_v.y) * LON_CELLS + lonCell(_v.x, _v.z);
	}
	return { cells, dirs };
}

/** Vertices in the model frame. `getX/getY/getZ` (not the raw array) is what
 *  denormalises a quantised attribute. */
function meshVerts(mesh: Mesh, toModel: Matrix4): Float32Array {
	const pos = mesh.geometry.attributes.position;
	const m = new Matrix4().multiplyMatrices(toModel, mesh.matrixWorld);
	const verts = new Float32Array(pos.count * 3);
	for (let i = 0; i < pos.count; i++) {
		_v.set(pos.getX(i), pos.getY(i), pos.getZ(i)).applyMatrix4(m);
		verts[i * 3] = _v.x;
		verts[i * 3 + 1] = _v.y;
		verts[i * 3 + 2] = _v.z;
	}
	return verts;
}

const _a = new Vector3();
const _b = new Vector3();
const _c = new Vector3();
const _n = new Vector3();
const _m = new Vector3();
const _t = new Vector3();

function readDir(dirs: Float32Array, i: number, out: Vector3): Vector3 {
	return out.set(dirs[i * 3], dirs[i * 3 + 1], dirs[i * 3 + 2]);
}

/** Is `p` on the short arc a→b of the great circle with normal `n = a × b`? */
function onArc(a: Vector3, b: Vector3, p: Vector3, n: Vector3): boolean {
	return _t.crossVectors(a, p).dot(n) >= 0 && _t.crossVectors(p, b).dot(n) >= 0;
}

/** Widest latitude the short arc a→b reaches, as a pair of cell rows. A
 *  great-circle edge bows poleward of both its endpoints, by degrees on a
 *  coarse model — file it by its endpoints alone and the cell a ray actually
 *  passes through holds no face at all. */
function arcLatCells(a: Vector3, b: Vector3, out: { lo: number; hi: number }): void {
	_n.crossVectors(a, b);
	const len2 = _n.lengthSq();
	if (len2 < 1e-18) return; // degenerate edge: endpoints already cover it
	// Extreme latitudes of the full circle sit where the pole projects onto it.
	_m.set(0, 1, 0)
		.addScaledVector(_n, -_n.y / len2)
		.normalize();
	if (onArc(a, b, _m, _n)) out.hi = Math.max(out.hi, latCell(_m.y));
	_m.negate();
	if (onArc(a, b, _m, _n)) out.lo = Math.min(out.lo, latCell(_m.y));
}

/** Does the spherical triangle cover the pole at `poleY` (+1 or −1)? Its edges
 *  then wind consistently around it, and every longitude is inside. */
function coversPole(a: Vector3, b: Vector3, c: Vector3, poleY: number): boolean {
	const s0 = (a.z * b.x - a.x * b.z) * poleY;
	const s1 = (b.z * c.x - b.x * c.z) * poleY;
	const s2 = (c.z * a.x - c.x * a.z) * poleY;
	return (s0 > 0 && s1 > 0 && s2 > 0) || (s0 < 0 && s1 < 0 && s2 < 0);
}

/**
 * The cell box each face occupies, `[lat0, lat1, lon0, lon1]` per face, with
 * `lon1` running past `LON_CELLS` where the box wraps the ±180° seam. Held
 * between the index's counting and filling passes so the spherical geometry is
 * worked out once.
 */
function faceBoxes(
	meshes: IndexedMesh[],
	vertsPerMesh: { cells: Int32Array; dirs: Float32Array }[]
): Int32Array[] {
	const span = { lo: 0, hi: 0 };
	const boxes: Int32Array[] = [];
	for (let mi = 0; mi < meshes.length; mi++) {
		const m = meshes[mi];
		const { cells, dirs } = vertsPerMesh[mi];
		const box = new Int32Array(m.faces * 4);
		boxes.push(box);
		for (let f = 0; f < m.faces; f++) {
			const a = m.idx ? m.idx[f * 3] : f * 3;
			const b = m.idx ? m.idx[f * 3 + 1] : f * 3 + 1;
			const c = m.idx ? m.idx[f * 3 + 2] : f * 3 + 2;
			const ca = cells[a],
				cb = cells[b],
				cc = cells[c];
			const la = (ca / LON_CELLS) | 0,
				lb = (cb / LON_CELLS) | 0,
				lc = (cc / LON_CELLS) | 0;
			const oa = ca % LON_CELLS,
				ob = cb % LON_CELLS,
				oc = cc % LON_CELLS;
			let lat0 = Math.min(la, lb, lc);
			let lat1 = Math.max(la, lb, lc);
			// Longitudes are a circle, so the arc a face covers is the complement
			// of the widest gap between its vertices — reading min..max instead
			// files a seam-straddling face into the arc it does NOT cover, and
			// near the poles, where faces span many cells, into the wrong half.
			const s0 = Math.min(oa, ob, oc);
			const s2 = Math.max(oa, ob, oc);
			const s1 = oa + ob + oc - s0 - s2;
			const gapEnd = s0 + LON_CELLS - s2;
			let lon0 = s0;
			let lon1 = s2;
			if (s1 - s0 >= s2 - s1 && s1 - s0 > gapEnd) {
				lon0 = s1;
				lon1 = s0 + LON_CELLS;
			} else if (s2 - s1 > gapEnd) {
				lon0 = s2;
				lon1 = s1 + LON_CELLS;
			}
			// A face spanning more than its own neighbourhood may bow outside the
			// box its vertices describe; only those pay for the exact widening.
			if (lat1 - lat0 > 1 || lon1 - lon0 > 1) {
				readDir(dirs, a, _a);
				readDir(dirs, b, _b);
				readDir(dirs, c, _c);
				if (coversPole(_a, _b, _c, 1)) {
					lat1 = LAT_CELLS - 1;
					lon0 = 0;
					lon1 = LON_CELLS - 1;
				} else if (coversPole(_a, _b, _c, -1)) {
					lat0 = 0;
					lon0 = 0;
					lon1 = LON_CELLS - 1;
				} else {
					span.lo = lat0;
					span.hi = lat1;
					arcLatCells(_a, _b, span);
					arcLatCells(_b, _c, span);
					arcLatCells(_c, _a, span);
					lat0 = span.lo;
					lat1 = span.hi;
				}
			}
			box[f * 4] = lat0;
			box[f * 4 + 1] = lat1;
			box[f * 4 + 2] = lon0;
			box[f * 4 + 3] = lon1;
		}
	}
	return boxes;
}

/** Walk every (cell, face) pair the boxes describe. */
function forEachPair(boxes: Int32Array[], emit: (cell: number, slot: number) => void): void {
	for (let mi = 0; mi < boxes.length; mi++) {
		const box = boxes[mi];
		for (let f = 0; f * 4 < box.length; f++) {
			const slot = mi * MESH_STRIDE + f;
			for (let lat = box[f * 4]; lat <= box[f * 4 + 1]; lat++) {
				for (let lon = box[f * 4 + 2]; lon <= box[f * 4 + 3]; lon++) {
					emit(lat * LON_CELLS + (lon % LON_CELLS), slot);
				}
			}
		}
	}
}

/**
 * Index `root`'s faces by direction. Call it where the occluder spheres are
 * built — after the unit-radius fit, before the model takes on an attitude —
 * so the stored matrices land in the post-fit frame the mount scales from.
 * Null when the model carries no faces.
 */
export function buildRadialIndex(root: Object3D): RadialIndex | null {
	root.updateMatrixWorld(true);
	const toModel = new Matrix4().makeTranslation(
		-root.position.x,
		-root.position.y,
		-root.position.z
	);
	const meshes: IndexedMesh[] = [];
	root.traverse((obj) => {
		if (!(obj instanceof Mesh)) return;
		const pos = obj.geometry.attributes.position;
		if (!pos) return;
		const idx = obj.geometry.index;
		const faces = (idx ? idx.count : pos.count) / 3;
		if (faces < 1 || faces >= MESH_STRIDE) return;
		meshes.push({
			verts: meshVerts(obj, toModel),
			idx: idx ? idx.array : null,
			faces: Math.floor(faces)
		});
	});
	if (!meshes.length) return null;

	const boxes = faceBoxes(meshes, meshes.map(vertexCells));
	const start = new Int32Array(CELLS + 1);
	forEachPair(boxes, (cell) => start[cell + 1]++);
	for (let i = 0; i < CELLS; i++) start[i + 1] += start[i];
	const slots = new Int32Array(start[CELLS]);
	const fill = start.slice(0, CELLS);
	forEachPair(boxes, (cell, slot) => {
		slots[fill[cell]++] = slot;
	});
	return { meshes, start, slots };
}

const _v0 = new Vector3();
const _v1 = new Vector3();
const _v2 = new Vector3();
const _e1 = new Vector3();
const _e2 = new Vector3();
const _p = new Vector3();
const _q = new Vector3();

/** Möller–Trumbore against one face, for a ray leaving the model's origin.
 *  Returns the hit distance, or 0 for a miss. */
function faceDistance(m: IndexedMesh, face: number, dir: Vector3): number {
	const a = m.idx ? m.idx[face * 3] : face * 3;
	const b = m.idx ? m.idx[face * 3 + 1] : face * 3 + 1;
	const c = m.idx ? m.idx[face * 3 + 2] : face * 3 + 2;
	_v0.set(m.verts[a * 3], m.verts[a * 3 + 1], m.verts[a * 3 + 2]);
	_v1.set(m.verts[b * 3], m.verts[b * 3 + 1], m.verts[b * 3 + 2]);
	_v2.set(m.verts[c * 3], m.verts[c * 3 + 1], m.verts[c * 3 + 2]);
	_e1.subVectors(_v1, _v0);
	_e2.subVectors(_v2, _v0);
	_p.crossVectors(dir, _e2);
	const det = _e1.dot(_p);
	if (Math.abs(det) < 1e-12) return 0;
	const inv = 1 / det;
	// Ray origin is the model origin, so the origin→v0 vector is just −v0.
	const u = -_v0.dot(_p) * inv;
	if (u < 0 || u > 1) return 0;
	_q.crossVectors(_v0, _e1).negate();
	const v = dir.dot(_q) * inv;
	if (v < 0 || u + v > 1) return 0;
	const t = _e2.dot(_q) * inv;
	return t > 0 ? t : 0;
}

function scanCell(index: RadialIndex, cell: number, dir: Vector3, best: number): number {
	const { start, slots, meshes } = index;
	for (let i = start[cell]; i < start[cell + 1]; i++) {
		const slot = slots[i];
		const t = faceDistance(meshes[(slot / MESH_STRIDE) | 0], slot % MESH_STRIDE, dir);
		if (t > best) best = t;
	}
	return best;
}

/**
 * Surface distance (post-fit model units) from the model's origin along a unit
 * body-fixed direction — the outermost hit, so a concavity can't swallow the
 * result. Null when nothing covers the direction (a hole in the scan).
 *
 * The direction's own cell answers almost every query; a miss widens to the
 * neighbourhood, which covers faces whose great-circle edges bulge outside the
 * lat/lon box they were filed under.
 */
export function radialIndexDistance(index: RadialIndex, dir: Vector3): number | null {
	const lat = latCell(dir.y);
	const lon = lonCell(dir.x, dir.z);
	let best = scanCell(index, lat * LON_CELLS + lon, dir, 0);
	if (best > 0) return best;
	for (let dLat = -1; dLat <= 1; dLat++) {
		const l = lat + dLat;
		if (l < 0 || l >= LAT_CELLS) continue;
		for (let dLon = -1; dLon <= 1; dLon++) {
			best = scanCell(index, l * LON_CELLS + ((lon + dLon + LON_CELLS) % LON_CELLS), dir, best);
		}
	}
	// A pole's cells are slivers a face can straddle entirely; sweep the row.
	if (best === 0 && (lat === 0 || lat === LAT_CELLS - 1)) {
		const row = lat === 0 ? 0 : LAT_CELLS - 2;
		for (let l = row; l < row + 2; l++)
			for (let c = 0; c < LON_CELLS; c++) best = scanCell(index, l * LON_CELLS + c, dir, best);
	}
	return best > 0 ? best : null;
}
