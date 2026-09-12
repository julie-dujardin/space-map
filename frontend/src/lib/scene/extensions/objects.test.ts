import { describe, expect, it } from 'vitest';
import { Mesh, MeshBasicMaterial, PerspectiveCamera, SphereGeometry } from 'three';
import { AU_KM, AU_SCALE } from '$lib/math/units';
import { MapObjectExtension } from './objects';
import { samples } from './trajectory';
import type { ExtensionFrame } from './registry';
import type { ContextManager } from '$lib/scene/state/context-manager.svelte';
import type { PositionedBody } from '$lib/types/objects';

/** A stand-in data layer with one body, so an object's own offset is what it
 *  is drawn at. */
function fakeCtx(position: [number, number, number]): ContextManager {
	const body = { data: { id: 'test', radiusKm: 1000 }, position } as unknown as PositionedBody;
	return {
		getBody: (id: string) => (id === 'test' ? body : undefined)
	} as unknown as ContextManager;
}

function frame(ctx: ContextManager, basis: [number, number, number], jd = 2460000): ExtensionFrame {
	const camera = new PerspectiveCamera(60, 16 / 9, 0.01, 100);
	return { jd, basis, camera, viewportPx: 900, ctx };
}

/** A metre-wide ball, so the drawn scale is the model's scale outright. */
function ball(): Mesh {
	return new Mesh(new SphereGeometry(0.5, 8, 8), new MeshBasicMaterial());
}

const CANVAS = null as unknown as HTMLCanvasElement;

describe('MapObjectExtension', () => {
	it('draws the model where the trajectory puts it, relative to the origin', () => {
		const model = ball();
		const object = new MapObjectExtension(
			{
				position: { body: 'test', offsetKm: () => [AU_KM, 0, 0] as const },
				model: { object3d: model }
			},
			'a',
			CANVAS
		);
		object.update(frame(fakeCtx([0, 0, 0]), [0, 0, 0]));
		expect(model.visible).toBe(true);
		expect(model.position.x).toBeCloseTo(AU_SCALE, 6);
		// The origin the scene is drawn around comes off every place alike.
		object.update(frame(fakeCtx([0, 0, 0]), [AU_SCALE, 0, 0]));
		expect(model.position.x).toBeCloseTo(0, 6);
	});

	it('is not drawn where its trajectory says nothing', () => {
		const model = ball();
		const object = new MapObjectExtension(
			{
				position: samples({
					body: 'test',
					samples: [
						{ jd: 2460000, km: [0, 0, 0] },
						{ jd: 2460001, km: [7000, 0, 0] }
					]
				}),
				model: { object3d: model }
			},
			'a',
			CANVAS
		);
		object.update(frame(fakeCtx([0, 0, 0]), [0, 0, 0], 2460000.5));
		expect(model.visible).toBe(true);
		object.update(frame(fakeCtx([0, 0, 0]), [0, 0, 0], 2460002));
		expect(model.visible).toBe(false);
	});

	it('draws a model at the size it was told, in metres', () => {
		const model = ball();
		const object = new MapObjectExtension(
			{ position: { body: 'test' }, model: { object3d: model, scaleM: 100 } },
			'a',
			CANVAS
		);
		object.update(frame(fakeCtx([0, 0, 0]), [0, 0, 0]));
		// A ball a metre across, drawn a hundred metres across.
		expect(model.scale.x).toBeCloseTo((0.1 / AU_KM) * AU_SCALE, 12);
	});

	it('holds a model to its pixel floor, and lets it grow past it', () => {
		const model = ball();
		const object = new MapObjectExtension(
			{ position: { body: 'test' }, model: { object3d: model, scaleM: 12, minPx: 20 } },
			'a',
			CANVAS
		);
		const trueScale = (0.012 / AU_KM) * AU_SCALE;
		// The camera sits at the origin, the object an astronomical unit out: at
		// true size the ball is far under a pixel.
		const far = frame(fakeCtx([AU_SCALE, 0, 0]), [0, 0, 0]);
		object.update(far);
		expect(model.scale.x).toBeGreaterThan(trueScale * 1000);
		const drawnPx =
			((model.scale.x * 1) / far.camera.position.distanceTo(model.position)) *
			(far.viewportPx / (2 * Math.tan((60 * Math.PI) / 360)));
		expect(drawnPx).toBeCloseTo(20, 6);

		// Close enough for its true size to be bigger than the floor.
		const near = frame(fakeCtx([(12 / 1000 / AU_KM) * AU_SCALE * 20, 0, 0]), [0, 0, 0]);
		object.update(near);
		expect(model.scale.x).toBeCloseTo(trueScale, 15);
	});

	it('takes the model back out of the scene without disposing it', () => {
		const model = ball();
		const object = new MapObjectExtension(
			{ position: { body: 'test' }, model: { object3d: model } },
			'a',
			CANVAS
		);
		expect(model.parent).toBe(object.object);
		object.dispose();
		expect(model.parent).toBeNull();
		expect(model.geometry.attributes.position).toBeDefined();
	});
});
