import { Mesh, PerspectiveCamera, Vector3 } from 'three';
import { describe, expect, it } from 'vitest';
import type { PanoramaEntry } from '$lib/fetch/objects/object-data';
import { AU_KM, AU_SCALE, kmToScene } from '$lib/math/units';
import { surfaceDirection } from '$lib/scene/extensions/anchor';
import type { ExtensionFrame } from '$lib/scene/extensions/registry';
import { hitOnScreen, TraverseTrace } from './trace';

describe('hitOnScreen', () => {
	const screen = new Float32Array([10, 10, 50, 50, 52, 50]);
	const facing = new Uint8Array([1, 1, 1]);
	const depth = new Float32Array([1, 1, 1]);
	const hit = (at: Float32Array, runs: number[], x: number, y: number, d = depth, f = facing) =>
		hitOnScreen(at, f, d, runs, x, y, 8, 4);

	it('picks the closest place within reach', () => {
		expect(hit(screen, [3], 53, 51)?.index).toBe(2);
		expect(hit(screen, [3], 49, 50)?.index).toBe(1);
	});

	it('answers along the line between two places with the nearer one', () => {
		expect(hit(screen, [3], 22, 18)).toEqual({ index: 0, toward: 1, share: 0.25 });
		expect(hit(screen, [3], 38, 42)).toEqual({ index: 1, toward: 0, share: 0.25 });
	});

	it('follows the segment past a place it shares with the next', () => {
		const ends = new Float32Array([0, 0, 100, 0, 200, 0]);
		const past = hitOnScreen(ends, facing, depth, [3], 120, 0, 30, 4);
		expect(past?.index).toBe(1);
		expect(past?.toward).toBe(2);
		expect(past?.share).toBeCloseTo(0.2, 6);
	});

	it('turns the share on screen into the share on the ground', () => {
		const ends = new Float32Array([0, 0, 100, 0]);
		// The far end is three times as deep: the screen's midpoint is a quarter
		// of the way along the ground.
		const far = hit(ends, [2], 49, 0, new Float32Array([1, 3]));
		expect(far?.index).toBe(0);
		expect(far?.share).toBeCloseTo((0.49 * 1) / (0.51 * 3 + 0.49 * 1), 6);
	});

	it('answers with the end that is nearer on the ground', () => {
		const ends = new Float32Array([0, 0, 100, 0]);
		// Nearer the first end on screen, past halfway on the ground.
		const near = hit(ends, [2], 45, 0, new Float32Array([3, 1]));
		expect(near?.index).toBe(1);
		expect(near?.share).toBeCloseTo(1 - 1.35 / 1.9, 6);
	});

	it('prefers a place under the pointer to a track that crosses it', () => {
		const crossing = new Float32Array([0, 0, 200, 0, 100, 1]);
		expect(hit(crossing, [2, 1], 100, 0)?.index).toBe(2);
	});

	it('prefers the line the pointer is on to one it only reaches', () => {
		expect(hit(new Float32Array([0, 0, 100, 0, 42, 6]), [2, 1], 40, 0)?.index).toBe(0);
		expect(hit(new Float32Array([0, 0, 100, 0, 42, 3]), [2, 1], 40, 0)?.index).toBe(2);
	});

	it('finds nothing out of reach', () => {
		expect(hit(screen, [3], 40, 20)).toBeNull();
	});

	it('draws no line between two runs', () => {
		const ends = new Float32Array([0, 0, 100, 0, 200, 0]);
		expect(hit(ends, [2, 1], 60, 0)?.index).toBe(1);
		expect(hit(ends, [2, 1], 150, 0)).toBeNull();
	});

	it('skips places on the far side', () => {
		expect(hit(screen, [3], 51, 50, depth, new Uint8Array([1, 0, 0]))).toBeNull();
		expect(hit(screen, [3], 30, 30, depth, new Uint8Array([1, 0, 1]))).toBeNull();
	});
});

describe('TraverseTrace', () => {
	it('keeps its vertices within a centimetre a few km from the camera on a planet', () => {
		const radiusKm = 3389.5;
		const entries = [0, 1, 2, 3].map(
			(k): PanoramaEntry => ({
				id: `p${k}`,
				time: '',
				lat: -4.78,
				lon: 137.38 + k * 0.01,
				north_offset_deg: 0
			})
		);
		const trace = new TraverseTrace({
			body: 'mars',
			runs: [entries],
			ground: () => 0,
			widthPx: 15,
			color: '#60a5fa'
		});
		const body = { data: { id: 'mars', radiusKm } };
		const ctx = { getBody: () => body, place: () => [0, 0, 0] };
		const camera = new PerspectiveCamera(60, 2, 1e-12, 1);
		const [x, y, z] = surfaceDirection(entries[0].lat, entries[0].lon);
		camera.position.set(x, y, z).multiplyScalar(kmToScene(radiusKm + 3));
		camera.lookAt(0, 0, 0);
		camera.updateMatrixWorld();
		trace.update({
			jd: 2461000,
			basis: [0, 0, 0],
			camera,
			viewportPx: 800,
			ctx
		} as unknown as ExtensionFrame);

		const mesh = trace.object.children[0] as Mesh;
		const positions = mesh.geometry.getAttribute('position').array;
		const metresPerUnit = (AU_KM / AU_SCALE) * 1000;
		for (let i = 0; i < entries.length; i++) {
			// The strip's two edges meet halfway at the place, lifted off the ground.
			const drawn = new Vector3(
				(positions[i * 6] + positions[i * 6 + 3]) / 2,
				(positions[i * 6 + 1] + positions[i * 6 + 4]) / 2,
				(positions[i * 6 + 2] + positions[i * 6 + 5]) / 2
			).applyMatrix4(mesh.matrixWorld);
			const place = new Vector3(...surfaceDirection(entries[i].lat, entries[i].lon));
			const ground = place.clone().multiplyScalar(kmToScene(radiusKm));
			const lifted = ground.addScaledVector(place, ground.distanceTo(camera.position) * 0.002);
			expect(drawn.distanceTo(lifted) * metresPerUnit).toBeLessThan(0.01);
		}
	});
});
