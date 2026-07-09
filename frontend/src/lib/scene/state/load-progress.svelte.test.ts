import { describe, it, expect, beforeEach } from 'vitest';
import { loadProgress } from './load-progress.svelte';

describe('loadProgress', () => {
	beforeEach(() => loadProgress.reset());

	it('starts at zero and active after reset', () => {
		expect(loadProgress.value).toBe(0);
		expect(loadProgress.active).toBe(true);
	});

	it('ignores byte reports before a total is announced', () => {
		loadProgress.addBytes(1000);
		expect(loadProgress.value).toBe(0);
	});

	it('fills the gap toward the next milestone as bytes stream in, capped below it', () => {
		// metadata=0.12 → ephemeris=0.55 gap; fill is capped at 90% of it.
		loadProgress.reach('metadata');
		expect(loadProgress.value).toBeCloseTo(0.12, 5);
		loadProgress.announce(1000);
		loadProgress.addBytes(1000); // fully loaded this fetch
		const capped = 0.12 + (0.55 - 0.12) * 0.9;
		expect(loadProgress.value).toBeCloseTo(capped, 5);
		expect(loadProgress.value).toBeLessThan(0.55);
	});

	it('never regresses when a later fetch enlarges the announced total mid-gap', () => {
		loadProgress.reach('metadata');
		loadProgress.announce(1000);
		loadProgress.addBytes(1000);
		const peak = loadProgress.value;
		loadProgress.announce(9000); // a second, bigger fetch appears
		expect(loadProgress.value).toBe(peak); // no dip
		loadProgress.addBytes(9000);
		expect(loadProgress.value).toBeGreaterThanOrEqual(peak);
	});

	it('advances monotonically across the full milestone sequence', () => {
		const seen: number[] = [loadProgress.value];
		for (const stage of ['metadata', 'ephemeris', 'majors', 'labels', 'done'] as const) {
			loadProgress.announce(100);
			loadProgress.addBytes(100);
			seen.push(loadProgress.value);
			loadProgress.reach(stage);
			seen.push(loadProgress.value);
		}
		for (let i = 1; i < seen.length; i++) expect(seen[i]).toBeGreaterThanOrEqual(seen[i - 1]);
		expect(loadProgress.value).toBe(1);
	});

	it('reaches exactly 1 and stops counting once done', () => {
		loadProgress.reach('done');
		expect(loadProgress.value).toBe(1);
		expect(loadProgress.active).toBe(false);
		loadProgress.announce(1000);
		loadProgress.addBytes(1000);
		expect(loadProgress.value).toBe(1); // inert after done
	});

	it('ignores out-of-order / duplicate milestones', () => {
		loadProgress.reach('majors'); // skip ahead
		expect(loadProgress.value).toBeCloseTo(0.8, 5);
		loadProgress.reach('metadata'); // stale, lower target
		expect(loadProgress.value).toBeCloseTo(0.8, 5);
	});
});
