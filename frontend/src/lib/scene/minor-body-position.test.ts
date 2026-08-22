import { describe, it, expect } from 'vitest';
import { ObjectType, type BodyData, type PositionedBody } from '$lib/types/objects';
import { OrbitalSource } from '$lib/fetch/position/format';
import type { ContextManager } from '$lib/scene/state/context-manager.svelte';
import { refreshMinorBodyPosition } from './minor-body-position';

/**
 * Point-cloud bodies materialize at the scene origin, so a refresh that fails
 * silently leaves them sitting on the barycentre — and the camera flies there.
 * `positionUnknown` is what keeps framing off such a body, so every exit of
 * the refresh must set it truthfully.
 */

const EARTH = 'naif-399';

function mkBody(data: Partial<BodyData> & Pick<BodyData, 'id'>): PositionedBody {
	return {
		data: {
			name: null,
			objectType: ObjectType.SPACECRAFT,
			parentId: EARTH,
			a: 1e-5,
			e: 0,
			i: 0,
			om: 0,
			w: 0,
			ma: 0,
			n: 1,
			epoch: 2451545,
			radiusKm: 0,
			hasLocalized: false,
			validityStart: -Infinity,
			validityEnd: Infinity,
			orbitalSource: OrbitalSource.SPICE,
			...data
		},
		position: [0, 0, 0],
		positionUnknown: true
	};
}

/** Only `getBody` is reached; `known` lists the bodies that have a position. */
function mkCtx(known: Record<string, [number, number, number]>): ContextManager {
	return {
		getBody: (id: string) => (known[id] ? { position: known[id] } : undefined)
	} as unknown as ContextManager;
}

describe('refreshMinorBodyPosition', () => {
	it('places the body against its parent and clears the flag', () => {
		const body = mkBody({ id: 'sbdb-1' });
		refreshMinorBodyPosition(body, 2451545, mkCtx({ [EARTH]: [10, 0, 0] }));
		expect(body.positionUnknown).toBe(false);
		expect(body.position[0]).toBeGreaterThan(9);
	});

	it('leaves the body unplaced when the parent has no position', () => {
		const body = mkBody({ id: 'sbdb-2' });
		refreshMinorBodyPosition(body, 2451545, mkCtx({}));
		expect(body.positionUnknown).toBe(true);
		expect(body.position).toEqual([0, 0, 0]);
	});

	it('leaves the body unplaced outside its chunk validity', () => {
		const body = mkBody({ id: 'sbdb-3', validityStart: 2451545, validityEnd: 2451555 });
		refreshMinorBodyPosition(body, 2460000, mkCtx({ [EARTH]: [10, 0, 0] }));
		expect(body.positionUnknown).toBe(true);
		expect(body.position).toEqual([0, 0, 0]);
	});

	it('seats a parent-coincident body on the parent rather than the origin', () => {
		const body = mkBody({ id: 'sbdb-4', a: 0, n: 0 });
		refreshMinorBodyPosition(body, 2451545, mkCtx({ [EARTH]: [10, 2, 3] }));
		expect(body.positionUnknown).toBe(false);
		expect(body.position).toEqual([10, 2, 3]);
	});
});
