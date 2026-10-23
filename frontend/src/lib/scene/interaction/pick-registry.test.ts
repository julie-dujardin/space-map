/**
 * Pick-id ranges: keyed rows resolve to a body id, owner rows to their row,
 * and a released or never-given id to nothing.
 */

import { describe, expect, it } from 'vitest';
import { NO_KEY, objectKey } from '$lib/fetch/position/object-key';
import { PickRegistry } from './pick-registry';

describe('PickRegistry', () => {
	it('resolves keyed rows to body ids and owner rows to their row', () => {
		const registry = new PickRegistry();
		const cloud = registry.allocate('cloud', [objectKey(2, 433), NO_KEY]);
		const stars = registry.allocateRows('star:r0', 10_000);
		expect(cloud).toBe(1);
		expect(stars).toBe(3);
		expect(registry.resolve(cloud)).not.toBeNull();
		expect(registry.resolve(cloud + 1)).toBeNull();
		expect(registry.locate(cloud)).toBeNull();
		expect(registry.locate(stars + 9_999)).toEqual({ groupId: 'star:r0', row: 9_999 });
		expect(registry.resolve(stars)).toBeNull();
		expect(registry.locate(stars + 10_000)).toBeNull();
		expect(registry.locate(0)).toBeNull();
	});

	it('never gives an id twice, so a released range names nothing', () => {
		const registry = new PickRegistry();
		const first = registry.allocateRows('star:r0', 5);
		registry.release('star:r0');
		expect(registry.locate(first)).toBeNull();
		const second = registry.allocateRows('star:r0', 5);
		expect(second).toBe(first + 5);
		expect(registry.locate(second + 2)).toEqual({ groupId: 'star:r0', row: 2 });
	});
});
