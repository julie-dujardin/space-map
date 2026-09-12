import { describe, expect, it } from 'vitest';
import { PerspectiveCamera, type BufferGeometry, type Mesh } from 'three';
import { AU_SCALE } from '$lib/math/units';
import { SurfaceShapeExtension } from './surface';
import type { ExtensionFrame } from './registry';
import type { ContextManager } from '$lib/scene/state/context-manager.svelte';
import type { PositionedBody } from '$lib/types/objects';

const AU_KM = 149597870.7;
const RADIUS_KM = 1000;
/** Scene units per kilometre, as {@link kmToScene} works them out. */
const SCENE_PER_KM = AU_SCALE / AU_KM;

/** A body at a known place with a measured radius and no orientation data, so
 *  the shape lands on the unrotated sphere. */
function fakeCtx(position: [number, number, number]): ContextManager {
	const body = {
		data: { id: 'test', radiusKm: RADIUS_KM },
		position
	} as unknown as PositionedBody;
	return {
		getBody: (id: string) => (id === 'test' ? body : undefined)
	} as unknown as ContextManager;
}

function frame(ctx: ContextManager, basis: [number, number, number]): ExtensionFrame {
	return { jd: 2460000, basis, camera: new PerspectiveCamera(), ctx };
}

/** Vertices of one of the shape's meshes, as the side pairs the fat line draws
 *  them in for the outline and as plain triangles for the fill. */
function vertices(shape: SurfaceShapeExtension, at: number): Float32Array {
	const mesh = shape.object.children[at] as Mesh<BufferGeometry>;
	return mesh.geometry.getAttribute('position').array as Float32Array;
}

describe('SurfaceShapeExtension', () => {
	it('puts a place on the surface where its anchor would be', () => {
		const ctx = fakeCtx([0, 0, 0]);
		const shape = new SurfaceShapeExtension({
			body: 'test',
			points: [
				{ lon: 0, lat: 0 },
				{ lon: 10, lat: 0 }
			]
		});
		shape.update(frame(ctx, [0, 0, 0]));
		const out = vertices(shape, 0);
		// The default height is a fraction of the radius, off the ground but on
		// the same ray: longitude 0, latitude 0 is scene +x.
		const lifted = (RADIUS_KM + RADIUS_KM * 0.005) * SCENE_PER_KM;
		expect(out[0]).toBeCloseTo(lifted, 9);
		expect(out[1]).toBeCloseTo(0, 9);
		expect(out[2]).toBeCloseTo(0, 9);
	});

	it('takes a height of its own', () => {
		const ctx = fakeCtx([0, 0, 0]);
		const shape = new SurfaceShapeExtension({
			body: 'test',
			altitudeKm: 500,
			points: [
				{ lon: 0, lat: 90 },
				{ lon: 90, lat: 90 }
			]
		});
		shape.update(frame(ctx, [0, 0, 0]));
		const out = vertices(shape, 0);
		// The north pole is scene +y.
		expect(out[1]).toBeCloseTo((RADIUS_KM + 500) * SCENE_PER_KM, 9);
	});

	it('draws relative to the render origin, wherever that has moved to', () => {
		const ctx = fakeCtx([5, 0, 0]);
		const shape = new SurfaceShapeExtension({
			body: 'test',
			points: [
				{ lon: 0, lat: 0 },
				{ lon: 10, lat: 0 }
			]
		});
		shape.update(frame(ctx, [5, 0, 0]));
		const near = vertices(shape, 0)[0];
		shape.update(frame(ctx, [0, 0, 0]));
		const far = vertices(shape, 0)[0];
		expect(far - near).toBeCloseTo(5, 6);
	});

	it('fills an area on the sphere rather than across it', () => {
		const ctx = fakeCtx([0, 0, 0]);
		const shape = new SurfaceShapeExtension({
			body: 'test',
			closed: true,
			fill: '#ffffff',
			points: [
				{ lon: -20, lat: -20 },
				{ lon: 20, lat: -20 },
				{ lon: 20, lat: 20 },
				{ lon: -20, lat: 20 }
			]
		});
		shape.update(frame(ctx, [0, 0, 0]));
		const out = vertices(shape, 1);
		const lifted = (RADIUS_KM + RADIUS_KM * 0.005) * SCENE_PER_KM;
		for (let i = 0; i < out.length; i += 3) {
			expect(Math.hypot(out[i], out[i + 1], out[i + 2])).toBeCloseTo(lifted, 9);
		}
	});

	it('draws nothing while its body is not loaded', () => {
		const ctx = fakeCtx([0, 0, 0]);
		const shape = new SurfaceShapeExtension({
			body: 'elsewhere',
			points: [
				{ lon: 0, lat: 0 },
				{ lon: 10, lat: 0 }
			]
		});
		shape.update(frame(ctx, [0, 0, 0]));
		expect(shape.object.children[0].visible).toBe(false);
	});

	it('is hidden while the host has it hidden', () => {
		const ctx = fakeCtx([0, 0, 0]);
		const shape = new SurfaceShapeExtension({
			body: 'test',
			points: [
				{ lon: 0, lat: 0 },
				{ lon: 10, lat: 0 }
			]
		});
		shape.setVisible(false);
		shape.update(frame(ctx, [0, 0, 0]));
		expect(shape.object.children[0].visible).toBe(false);
	});
});
