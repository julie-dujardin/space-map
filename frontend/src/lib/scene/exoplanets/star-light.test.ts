import { Group, PointLight } from 'three';
import { describe, expect, it } from 'vitest';
import { SUN_ID } from '$lib/constants';
import type { BodyObjects } from '$lib/scene/types';
import { ObjectType, type PositionedBody } from '$lib/types/objects';
import { photosphereColour } from '$lib/scene/starfield/colour';
import { StarLight } from './star-light';

/** The scene's one light sits on the star of the drawn planets, in its colour. */

const body = (id: string, objectType: ObjectType, teff?: number): PositionedBody =>
	({
		data: { id, objectType, parentId: SUN_ID },
		position: [0, 0, 0],
		...(teff ? { extrasolar: { teff, colour: null } } : {})
	}) as unknown as PositionedBody;
const bo = (b: PositionedBody) => ({ body: b, root: new Group() }) as unknown as BodyObjects;

describe('StarLight', () => {
	it('moves the Sun light to the star and back, in their colours', () => {
		const sun = bo(body(SUN_ID, ObjectType.STAR));
		const light = new PointLight(0xffffff);
		sun.root.add(light);
		const star = bo(body('x-1', ObjectType.EXTRASOLAR, 2566));
		const objects = new Map([
			[SUN_ID, sun],
			['x-1', star]
		]);
		const seat = new StarLight();
		expect(seat.seat(objects, 'x-1')).toBe(light);
		expect(light.parent).toBe(star.root);
		expect(seat.starId).toBe('x-1');
		expect(light.color.toArray()).toEqual(photosphereColour(2566, null));
		expect(light.color.b).toBeLessThan(0.5);
		seat.seat(objects, SUN_ID);
		expect(light.parent).toBe(sun.root);
		expect(light.color.getHex()).toBe(0xffffff);
	});

	it('keeps the light on the Sun while the star has no body', () => {
		const sun = bo(body(SUN_ID, ObjectType.STAR));
		const light = new PointLight();
		sun.root.add(light);
		const seat = new StarLight();
		seat.seat(new Map([[SUN_ID, sun]]), 'x-9');
		expect(light.parent).toBe(sun.root);
		expect(seat.starId).toBe(SUN_ID);
	});
});
