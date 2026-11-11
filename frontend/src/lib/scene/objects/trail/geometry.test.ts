import { describe, expect, it } from 'vitest';
import type { InstancedBufferGeometry, InterleavedBufferAttribute } from 'three';
import {
	buildFatLineFromThin,
	commitTrail,
	writeFatTrailVertices,
	writeLineDistances
} from './geometry';

const points = new Float32Array([0, 0, 0, 1, 0, 0, 1, 1, 0, 2, 1, 0]);
const trail = new Float32Array([1, 0.75, 0.5, 0.25]);
const full = new Float32Array([1, 1, 1, 1]);

function attribute(geometry: InstancedBufferGeometry, name: string): InterleavedBufferAttribute {
	return geometry.getAttribute(name) as InterleavedBufferAttribute;
}

describe('fat line geometry', () => {
	it('draws a segment between each pair of neighbouring points', () => {
		const mesh = buildFatLineFromThin(4, points, trail, full, 4, '#fff', 2);
		const geometry = mesh.geometry as InstancedBufferGeometry;
		expect(geometry.instanceCount).toBe(3);
		const start = attribute(geometry, 'segStart');
		const end = attribute(geometry, 'segEnd');
		expect(end.data).toBe(start.data);
		expect(end.offset - start.offset).toBe(3);
		expect(start.offset - attribute(geometry, 'segPrev').offset).toBe(3);
		expect(attribute(geometry, 'segNext').offset - end.offset).toBe(3);
		// Each end has itself for a neighbour: no turn to join.
		expect([...start.data.array]).toEqual([0, 0, 0, ...points, 2, 1, 0]);
		const alphaStart = attribute(geometry, 'alphaStart');
		expect(attribute(geometry, 'alphaEnd').offset - alphaStart.offset).toBe(2);
		expect([...alphaStart.data.array.slice(0, 4)]).toEqual([1, 1, 0.75, 1]);
	});

	it('draws nothing past the points it was given', () => {
		const mesh = buildFatLineFromThin(4, points, trail, full, 2, '#fff', 2);
		expect((mesh.geometry as InstancedBufferGeometry).instanceCount).toBe(1);
	});

	it('draws again after a refresh too short to draw', () => {
		const mesh = buildFatLineFromThin(4, points, trail, full, 4, '#fff', 2);
		mesh.userData.isFatLine = true;
		commitTrail(mesh, points, trail, full, 1, true, true);
		expect(mesh.geometry.drawRange.count).toBe(0);
		writeFatTrailVertices(mesh.geometry, points, trail, full, 3);
		expect(mesh.geometry.drawRange.count).toBe(9);
		expect((mesh.geometry as InstancedBufferGeometry).instanceCount).toBe(2);
	});

	const square = new Float32Array([0, 0, 0, 1, 0, 0, 1, 1, 0, 0, 1, 0, 0, 0, 0]);
	const solid = new Float32Array(5).fill(1);
	/** The points a line of `m` points reads past its first and its last. */
	function pads(mesh: { geometry: unknown }, m: number): number[][] {
		const array = attribute(mesh.geometry as InstancedBufferGeometry, 'segStart').data.array;
		return [[...array.slice(0, 3)], [...array.slice((m + 1) * 3, (m + 2) * 3)]];
	}

	it('joins a closed line across its seam', () => {
		const mesh = buildFatLineFromThin(5, square, solid, solid, 5, '#fff', 2);
		expect(pads(mesh, 5)).toEqual([
			[0, 1, 0],
			[1, 0, 0]
		]);
	});

	it('moves the ends on when a line is drawn shorter or opened', () => {
		const mesh = buildFatLineFromThin(5, square, solid, solid, 5, '#fff', 2);
		writeFatTrailVertices(mesh.geometry, square, solid, solid, 4);
		expect(pads(mesh, 4)).toEqual([
			[0, 0, 0],
			[0, 1, 0]
		]);
		writeFatTrailVertices(mesh.geometry, points, trail, full, 3);
		expect(pads(mesh, 3)).toEqual([
			[0, 0, 0],
			[1, 1, 0]
		]);
	});

	it('does not wrap a line of two points on one spot', () => {
		const spot = new Float32Array([1, 2, 3, 1, 2, 3]);
		const mesh = buildFatLineFromThin(4, spot, trail, full, 2, '#fff', 2);
		expect(pads(mesh, 2)).toEqual([
			[1, 2, 3],
			[1, 2, 3]
		]);
	});

	it('holds a dashed line its length to each point', () => {
		const mesh = buildFatLineFromThin(4, points, trail, full, 4, '#fff', 2, 1, [4, 3]);
		writeLineDistances(mesh.geometry, new Float32Array([0, 10, 20, 30]), 4);
		const geometry = mesh.geometry as InstancedBufferGeometry;
		const start = attribute(geometry, 'distStart');
		expect(attribute(geometry, 'distEnd').offset).toBe(1);
		expect([...start.data.array]).toEqual([0, 10, 20, 30]);
	});
});
