import { describe, expect, it } from 'vitest';
import type { PositionedBody } from '$lib/types/objects';
import { kmToScene } from '$lib/math/units';
import { featureSeat } from './feature-seat';

const host = { data: { id: 'naif-499', radiusKm: 3389 } } as unknown as PositionedBody;
const at = [10, 20, 30] as const;

describe('featureSeat', () => {
	it('stands on the mean-radius sphere before the host has a drawn surface', () => {
		const anchor = { hostId: 'naif-499', featureId: 1, lat: 0, lon: 0, diameterM: 1e5 };
		const seat = featureSeat(anchor, host, at, undefined, 0);
		expect(seat[0]).toBeCloseTo(at[0] + kmToScene(3389), 12);
		expect(seat[1]).toBeCloseTo(at[1], 12);
		expect(seat[2]).toBeCloseTo(at[2], 12);
	});

	it('lifts a feature at the pole straight up the host axis', () => {
		const anchor = { hostId: 'naif-499', featureId: 2, lat: 90, lon: 123, diameterM: 1e5 };
		const seat = featureSeat(anchor, host, at, undefined, 0);
		expect(seat[0]).toBeCloseTo(at[0], 12);
		expect(seat[1]).toBeCloseTo(at[1] + kmToScene(3389), 12);
		expect(seat[2]).toBeCloseTo(at[2], 12);
	});
});
