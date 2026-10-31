import { describe, expect, it, vi } from 'vitest';
import { ObjectType, type BodyData, type PositionedBody } from '$lib/types/objects';
import { OrbitalSource } from '$lib/fetch/position/format';
import { AU_SCALE } from '$lib/math/units';
import { BodyIndex } from '$lib/scene/state/bodies.svelte';
import { VisibilityController } from './controller.svelte';
import { VISIBILITY } from './thresholds';

/** A star on a drawn orbit takes the ratio tiers of a planet of another star,
 *  by the `a` of the pair it is drawn on. */

const PAIR = 'x-1';
const STAR = 'x-11';

function star(a: number, parentId = PAIR): PositionedBody {
	const data: BodyData = {
		id: STAR,
		name: 'Star',
		objectType: ObjectType.EXTRASOLAR,
		parentId,
		a,
		e: 0,
		i: 0,
		om: 0,
		w: 0,
		ma: 0,
		n: 1,
		epoch: 2451545,
		radiusKm: NaN,
		hasLocalized: false,
		validityStart: -Infinity,
		validityEnd: Infinity,
		orbitalSource: OrbitalSource.UNKNOWN
	};
	return { data, position: [0, 0, 0] };
}

function controller(share = 1): VisibilityController {
	const visibility = new VisibilityController(new BodyIndex());
	visibility.updateViewport(1503);
	visibility.systemShares = new Map([[STAR, share]]);
	return visibility;
}

const atRatio = (ratio: number, a: number) => ratio * a * AU_SCALE;

describe('a star on a drawn orbit', () => {
	it('takes the tiers of a planet of another star, by its orbit about its pair', () => {
		const visibility = controller();
		const body = star(2);
		expect(visibility.getPlanetVisibility(body, atRatio(19, 2))).toBe(VISIBILITY.FULL);
		expect(visibility.getPlanetVisibility(body, atRatio(21, 2))).toBe(VISIBILITY.FAR);
		expect(visibility.getPlanetVisibility(body, atRatio(101, 2))).toBe(VISIBILITY.HIDE);
	});

	it('takes the same tiers on a nested pair', () => {
		const visibility = controller();
		const body = star(0.1, 'x-5');
		expect(visibility.getPlanetVisibility(body, atRatio(19, 0.1))).toBe(VISIBILITY.FULL);
		expect(visibility.getPlanetVisibility(body, atRatio(21, 0.1))).toBe(VISIBILITY.FAR);
	});

	it('takes the tiers of its pair, so the heavier member keeps up with the other', () => {
		const visibility = controller();
		const heavy = star(0.5);
		heavy.extrasolar = { pairAxis: 2 } as PositionedBody['extrasolar'];
		expect(visibility.getPlanetVisibility(heavy, atRatio(19, 2))).toBe(VISIBILITY.FULL);
		expect(visibility.getPlanetVisibility(star(0.5), atRatio(19, 2))).toBe(VISIBILITY.FAR);
	});

	it('keeps its halo up close, where the disc takes over by size on screen', () => {
		const visibility = controller();
		expect(visibility.getPlanetVisibility(star(2), atRatio(0.001, 2))).toBe(VISIBILITY.FULL);
	});

	it('keeps its halo further out while it is focused', () => {
		const visibility = controller();
		const body = star(2);
		visibility.setFocused(body);
		expect(visibility.getPlanetVisibility(body, atRatio(999, 2))).toBe(VISIBILITY.FULL);
		expect(visibility.getPlanetVisibility(body, atRatio(1001, 2))).toBe(VISIBILITY.HIDE);
	});

	it('hides with no share of its system, focused or not', () => {
		const visibility = controller(0);
		visibility.systemShares = new Map();
		const body = star(2);
		visibility.setFocused(body);
		expect(visibility.getPlanetVisibility(body, atRatio(1, 2))).toBe(VISIBILITY.HIDE);
	});

	it('does not read as a body with no semi-major axis', () => {
		const warn = vi.spyOn(console, 'warn');
		controller().getPlanetVisibility(star(2), atRatio(1, 2));
		expect(warn).not.toHaveBeenCalled();
		warn.mockRestore();
	});
});
