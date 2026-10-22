import { describe, it, expect } from 'vitest';
import { SimClock } from './clock.svelte';

const BASE = 2460000;

/** True when `promise` resolves before the next timer task. */
async function settled(promise: Promise<void>): Promise<boolean> {
	let done = false;
	void promise.then(() => (done = true));
	await new Promise((resolve) => setTimeout(resolve, 0));
	return done;
}

describe('SimClock.jumpTo', () => {
	it('resolves when a frame shows the date of the jump', async () => {
		const clock = new SimClock(BASE);
		const jump = clock.jumpTo(BASE + 10);
		expect(await settled(jump)).toBe(false);
		clock.placed(clock.jumps);
		expect(await settled(jump)).toBe(true);
	});

	it('resolves the jumps before the one a frame shows, and not the ones after', async () => {
		const clock = new SimClock(BASE);
		const first = clock.jumpTo(BASE + 10);
		const firstJumps = clock.jumps;
		const second = clock.setDate(new Date('2035-06-01T00:00:00Z'));
		clock.placed(firstJumps);
		expect(await settled(first)).toBe(true);
		expect(await settled(second)).toBe(false);
		clock.placed(clock.jumps);
		expect(await settled(second)).toBe(true);
	});
});
