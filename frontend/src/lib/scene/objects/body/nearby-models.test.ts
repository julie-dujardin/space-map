import { describe, expect, it } from 'vitest';
import { ObjectType } from '$lib/types/objects';
import type { BodyObjects } from '$lib/scene/types';
import { NEARBY_MAX, NearbyModels } from './nearby-models';

const PX_PER_RAD = 1000;

/** A drawn craft whose radius spans `px` pixels at its distance. */
function craft(id: string, px: number): BodyObjects {
	return {
		body: { data: { id, objectType: ObjectType.SPACECRAFT }, position: [0, 0, 0] },
		radiusScene: px / PX_PER_RAD,
		cachedDist: 1,
		model: null
	} as unknown as BodyObjects;
}

function setup(focusHeld: string[] = []) {
	const loaded: string[] = [];
	const dropped: string[] = [];
	const models = new NearbyModels(
		(bo) => {
			loaded.push(bo.body.data.id);
			bo.model = {} as BodyObjects['model'];
			return Promise.resolve();
		},
		(bo) => {
			dropped.push(bo.body.data.id);
			bo.model = null;
		},
		(id) => focusHeld.includes(id)
	);
	return { models, loaded, dropped };
}

const byId = (...bos: BodyObjects[]) => new Map(bos.map((bo) => [bo.body.data.id, bo]));

describe('NearbyModels', () => {
	it('loads a craft once it spans a few pixels, and drops it when it shrinks', () => {
		const { models, loaded, dropped } = setup();
		const rover = craft('rover', 1);
		models.update(byId(rover), PX_PER_RAD);
		expect(loaded).toEqual([]);
		rover.radiusScene = 5 / PX_PER_RAD;
		models.update(byId(rover), PX_PER_RAD);
		expect(loaded).toEqual(['rover']);
		// Between the two figures it stays.
		rover.radiusScene = 3 / PX_PER_RAD;
		models.update(byId(rover), PX_PER_RAD);
		expect(dropped).toEqual([]);
		rover.radiusScene = 1 / PX_PER_RAD;
		models.update(byId(rover), PX_PER_RAD);
		expect(dropped).toEqual(['rover']);
	});

	it('holds only the nearest few', () => {
		const { models, loaded } = setup();
		const all = Array.from({ length: NEARBY_MAX + 2 }, (_, i) => craft(`c${i}`, 10 + i));
		models.update(byId(...all), PX_PER_RAD);
		expect(loaded.sort()).toEqual(
			all
				.slice(2)
				.map((bo) => bo.body.data.id)
				.sort()
		);
	});

	it('leaves the focus its own models', () => {
		const { models, loaded, dropped } = setup(['probe']);
		const probe = craft('probe', 50);
		models.update(byId(probe), PX_PER_RAD);
		probe.radiusScene = 0;
		models.update(byId(probe), PX_PER_RAD);
		expect(loaded).toEqual([]);
		expect(dropped).toEqual([]);
	});

	it('asks no more for a model that failed to load', async () => {
		const tries: string[] = [];
		const models = new NearbyModels(
			(bo) => {
				tries.push(bo.body.data.id);
				return Promise.reject(new Error('404'));
			},
			() => {},
			() => false
		);
		const broken = craft('broken', 50);
		models.update(byId(broken), PX_PER_RAD);
		await Promise.resolve();
		models.update(byId(broken), PX_PER_RAD);
		expect(tries).toEqual(['broken']);
	});

	it('skips a craft with no model to show', () => {
		const { models, loaded } = setup();
		const bare = craft('bare', 50);
		bare.noPhysical = 'model';
		models.update(byId(bare), PX_PER_RAD);
		expect(loaded).toEqual([]);
	});
});
