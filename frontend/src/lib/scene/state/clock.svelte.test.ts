import { describe, it, expect } from 'vitest';
import { FIRST_DATE_JD, LAST_DATE_JD } from '$lib/time/jd';
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

describe('SimClock past the range of Date', () => {
	it('holds every date a Date holds, and asks for the same one', () => {
		const clock = new SimClock(BASE);
		clock.setJD(BASE + 1e6);
		expect(clock.jd).toBe(BASE + 1e6);
		expect(clock.askedJd).toBe(BASE + 1e6);
		clock.sweepTo(BASE - 5);
		expect(clock.askedJd).toBe(clock.jd);
	});

	it('stops at the last date a Date holds, and keeps the date asked for', () => {
		const clock = new SimClock(BASE);
		const far = LAST_DATE_JD + 3e8;
		clock.setJD(far);
		expect(clock.jd).toBe(LAST_DATE_JD);
		expect(clock.askedJd).toBe(far);
		expect(Number.isFinite(clock.date.getTime())).toBe(true);
		clock.sweepTo(FIRST_DATE_JD - 1);
		expect(clock.jd).toBe(FIRST_DATE_JD);
		expect(Number.isFinite(clock.date.getTime())).toBe(true);
	});

	it('pauses a running clock at the end of the range', () => {
		const clock = new SimClock(LAST_DATE_JD - 1);
		clock.setTimeScale(86400 * 10);
		clock.tick(performance.now() + 1000);
		expect(clock.jd).toBe(LAST_DATE_JD);
		expect(clock.askedJd).toBe(LAST_DATE_JD);
		expect(clock.playing).toBe(false);
	});

	it('keeps the date asked for when played on past the range', () => {
		const clock = new SimClock(BASE);
		const far = LAST_DATE_JD + 3e8;
		clock.setJD(far);
		clock.setTimeScale(86400 * 365);
		clock.tick(performance.now() + 1000);
		expect(clock.askedJd).toBe(far);
		expect(clock.jd).toBe(LAST_DATE_JD);
		expect(clock.playing).toBe(false);
		// The clock did not move: a trip that leaves "now" keeps its date.
		expect(clock.settledJd).toBe(BASE);
	});

	it('runs back toward the range from past its last date', () => {
		const clock = new SimClock(BASE);
		clock.setJD(LAST_DATE_JD + 1000);
		clock.toggleDirection();
		clock.setTimeScale(86400 * 30);
		clock.tick(performance.now() + 1000);
		expect(clock.askedJd).toBeCloseTo(LAST_DATE_JD + 970, 1);
		expect(clock.jd).toBe(LAST_DATE_JD);
		expect(clock.playing).toBe(true);
	});

	it('runs forward toward the range from before its first date', () => {
		const clock = new SimClock(BASE);
		clock.setJD(FIRST_DATE_JD - 1000);
		clock.setTimeScale(86400 * 30);
		clock.tick(performance.now() + 1000);
		expect(clock.askedJd).toBeCloseTo(FIRST_DATE_JD - 970, 1);
		expect(clock.jd).toBe(FIRST_DATE_JD);
		expect(clock.playing).toBe(true);
	});

	it('runs back into the range from the date asked for', () => {
		const clock = new SimClock(BASE);
		clock.setJD(LAST_DATE_JD + 10);
		clock.toggleDirection();
		clock.setTimeScale(86400 * 30);
		clock.tick(performance.now() + 1000);
		expect(clock.askedJd).toBeCloseTo(LAST_DATE_JD - 20, 1);
		expect(clock.jd).toBe(clock.askedJd);
		expect(clock.playing).toBe(true);
	});
});

describe('SimClock.hold', () => {
	it('pauses, and leaves the settled date where it was', () => {
		const clock = new SimClock(BASE);
		clock.hold();
		clock.sweepTo(BASE + 40);
		expect(clock.playing).toBe(false);
		expect(clock.settledJd).toBe(BASE);
		clock.pause();
		expect(clock.settledJd).toBe(BASE + 40);
	});
});
