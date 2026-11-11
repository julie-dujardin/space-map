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
		expect([...start.data.array]).toEqual([...points]);
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
		expect(mesh.geometry.drawRange.count).toBe(6);
		expect((mesh.geometry as InstancedBufferGeometry).instanceCount).toBe(2);
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
