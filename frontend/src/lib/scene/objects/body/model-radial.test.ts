import { describe, it, expect } from 'vitest';
import { BufferAttribute, Group, IcosahedronGeometry, Mesh, Raycaster, Vector3 } from 'three';
import { buildRadialIndex, radialIndexDistance } from './model-radial';

/** A sphere-ish mesh under a root, positioned and scaled the way
 *  `fitToUnitRadius` leaves a loaded model. */
function model(detail = 4, scale = 1): Group {
	const root = new Group();
	root.scale.setScalar(scale);
	root.add(new Mesh(new IcosahedronGeometry(1, detail)));
	return root;
}

function dir(x: number, y: number, z: number): Vector3 {
	return new Vector3(x, y, z).normalize();
}

describe('radial face index', () => {
	it('measures the surface along a direction', () => {
		const index = buildRadialIndex(model())!;
		// An icosphere's faces cut the chords of the unit sphere, so a radial hit
		// lands a little inside 1 — but never outside it.
		for (const d of [dir(1, 0, 0), dir(0, 1, 0), dir(-1, 2, -3), dir(0.2, -0.9, 0.4)]) {
			const r = radialIndexDistance(index, d);
			expect(r).not.toBeNull();
			expect(r!).toBeGreaterThan(0.97);
			expect(r!).toBeLessThanOrEqual(1.0001);
		}
	});

	it('carries the root scale into the measured distance', () => {
		const index = buildRadialIndex(model(4, 3))!;
		expect(radialIndexDistance(index, dir(1, 1, 1))!).toBeGreaterThan(2.9);
	});

	it('answers the poles and the ±180° seam, where the cells degenerate', () => {
		const index = buildRadialIndex(model())!;
		for (const d of [dir(0, 1, 0), dir(0, -1, 0), dir(-1, 0, 0.0001), dir(-1, 0, -0.0001)]) {
			expect(radialIndexDistance(index, d)).toBeGreaterThan(0.97);
		}
	});

	it('takes the outermost hit, so a concavity cannot swallow the surface', () => {
		// Two shells: the index must report the outer one.
		const root = model();
		const inner = new Mesh(new IcosahedronGeometry(0.4, 3));
		root.add(inner);
		const index = buildRadialIndex(root)!;
		expect(radialIndexDistance(index, dir(1, 0.3, -0.2))!).toBeGreaterThan(0.97);
	});

	it('agrees with a raycast over a full sphere of directions', () => {
		// The index is only worth having if it answers exactly what the mesh
		// would: a hole drops the camera wall out to the bounding sphere, and a
		// short read lets the camera into the surface. Lumpy and elongated, so
		// faces span many cells near the poles and straddle the ±180° seam.
		const root = model(5);
		const mesh = root.children[0] as Mesh;
		const pos = mesh.geometry.attributes.position;
		const v = new Vector3();
		for (let i = 0; i < pos.count; i++) {
			v.fromBufferAttribute(pos, i);
			const lump = 1 + 0.3 * Math.sin(4 * v.x) * Math.cos(3 * v.z);
			pos.setXYZ(i, v.x * 2.5 * lump, v.y * lump, v.z * 0.6 * lump);
		}
		mesh.geometry.computeBoundingSphere();
		const index = buildRadialIndex(root)!;
		const caster = new Raycaster();
		root.updateMatrixWorld(true);
		for (let i = 0; i < 4000; i++) {
			// Fibonacci sphere — uniform, and it lands nothing on a grid line.
			const y = 1 - (2 * i) / 3999;
			const r = Math.sqrt(Math.max(0, 1 - y * y));
			const th = i * 2.399963229728653;
			const d = dir(Math.cos(th) * r, y, Math.sin(th) * r);
			caster.set(d.clone().multiplyScalar(20), d.clone().negate());
			const hit = caster.intersectObject(mesh, true)[0];
			expect(radialIndexDistance(index, d)).toBeCloseTo(20 - hit.distance, 6);
		}
	});

	it('reads a quantised attribute at its real scale', () => {
		// Shipped models are meshopt-quantised: positions arrive as normalised
		// int16, which is 32767× the real value until the attribute denormalises
		// it. Reading the raw buffer flung the camera clear of the solar system.
		const root = model();
		const mesh = root.children[0] as Mesh;
		const pos = mesh.geometry.attributes.position;
		const quantised = new Int16Array(pos.count * 3);
		for (let i = 0; i < pos.count * 3; i++) {
			quantised[i] = Math.round(pos.array[i] * 32767);
		}
		mesh.geometry.setAttribute('position', new BufferAttribute(quantised, 3, true));
		const index = buildRadialIndex(root)!;
		expect(radialIndexDistance(index, dir(1, 0.2, -0.3))!).toBeLessThan(1.001);
	});

	it('has no faces to index in an empty model', () => {
		expect(buildRadialIndex(new Group())).toBeNull();
	});
});
