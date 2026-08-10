import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { TripPlayback } from './playback.svelte';
import type { SimClock } from '$lib/scene/state/clock.svelte';
import type { LegKind } from '$lib/math/travel';
import type { TimelineEntry } from './timeline';

const BASE = 2460000;
const CRUISE_DAYS = 100;

function entry(kind: LegKind, startJd: number, endJd: number): TimelineEntry {
	return {
		id: `${kind}:${startJd}`,
		kind,
		startJd,
		endJd,
		days: endJd - startJd,
		isPhase: endJd > startJd,
		bodyId: null,
		bodyName: '',
		dvKms: 0
	};
}

/** Launch, departure burn, the crossing, arrival — three of them instants. */
const ENTRIES: TimelineEntry[] = [
	entry('ascent', BASE, BASE),
	entry('injection', BASE, BASE),
	entry('cruise', BASE, BASE + CRUISE_DAYS),
	entry('capture', BASE + CRUISE_DAYS, BASE + CRUISE_DAYS)
];

/** Only the three calls playback makes; the rest of SimClock is not its business. */
function fakeClock() {
	return {
		jd: BASE - 50,
		paused: 0,
		setJD(jd: number) {
			this.jd = jd;
		},
		sweepTo(jd: number) {
			this.jd = jd;
		},
		pause() {
			this.paused++;
		}
	};
}

describe('TripPlayback', () => {
	let now = 0;
	let pending: FrameRequestCallback[] = [];
	let clock: ReturnType<typeof fakeClock>;
	let focused: string[];
	let player: TripPlayback;

	/** Run every frame queued so far, `ms` later. */
	function frame(ms = 16) {
		now += ms;
		const due = pending;
		pending = [];
		for (const cb of due) cb(now);
	}

	/** Run `ms` of wall clock, a frame at a time. */
	function run(ms: number, step = 50) {
		for (let elapsed = 0; elapsed < ms; elapsed += step) frame(step);
	}

	beforeEach(() => {
		now = 0;
		pending = [];
		focused = [];
		clock = fakeClock();
		vi.stubGlobal('requestAnimationFrame', (cb: FrameRequestCallback) => pending.push(cb));
		vi.stubGlobal('cancelAnimationFrame', () => {});
		vi.spyOn(performance, 'now').mockImplementation(() => now);
		player = new TripPlayback({
			clock: clock as unknown as SimClock,
			entries: () => ENTRIES,
			focus: (e) => focused.push(e.kind)
		});
	});

	afterEach(() => {
		player.dispose();
		vi.unstubAllGlobals();
		vi.restoreAllMocks();
	});

	it('takes the clock over, leaving it paused so its own ticking cannot fight', () => {
		player.start();
		expect(player.playing).toBe(true);
		expect(clock.paused).toBeGreaterThan(0);
		// Starts at the first entry, wherever the clock happened to be before.
		expect(clock.jd).toBe(BASE);
	});

	it('steps past the burns without spending flight time on them', () => {
		player.start();
		run(1000);
		// Three moments pass before the crossing begins and none of them moves the
		// clock — there is no time between a launch and the burn after it.
		expect(focused).toEqual(['ascent', 'injection', 'cruise']);
		expect(clock.jd).toBe(BASE);
	});

	it('sweeps the clock across a phase and lands exactly on its end', () => {
		player.start();
		run(1000); // through the burns, up to the crossing
		run(6000);
		// Somewhere in the middle of the crossing, not at either end of it.
		expect(clock.jd).toBeGreaterThan(BASE);
		expect(clock.jd).toBeLessThan(BASE + CRUISE_DAYS);

		run(20_000);
		expect(clock.jd).toBe(BASE + CRUISE_DAYS);
	});

	it('stops itself at the last entry, having looked at every one', () => {
		player.start();
		run(30_000);
		expect(player.playing).toBe(false);
		expect(focused).toEqual(['ascent', 'injection', 'cruise', 'capture']);
		expect(clock.jd).toBe(BASE + CRUISE_DAYS);
	});

	it('starts again from the top once the trip is over', () => {
		player.start();
		run(30_000);
		player.start();
		expect(clock.jd).toBe(BASE);
		expect(player.playing).toBe(true);
	});

	it('gives up when the route changes under it', () => {
		const entries = [...ENTRIES];
		const moving = new TripPlayback({
			clock: clock as unknown as SimClock,
			entries: () => entries,
			focus: () => {}
		});
		moving.start();
		run(2000);
		// A different trip's dates under the leg being flown: carrying on would fly
		// one route's crossing into another's arrival.
		entries[3] = entry('capture', BASE + 5 + CRUISE_DAYS, BASE + 5 + CRUISE_DAYS);
		frame();
		expect(moving.playing).toBe(false);
		moving.dispose();
	});

	it('steps back to the start of the phase it is inside, not past it', () => {
		clock.jd = BASE + CRUISE_DAYS / 2;
		player.step(-1);
		// Mid-crossing, "back" means the start of the crossing.
		expect(clock.jd).toBe(BASE);
		// And again from there, the burn before it.
		player.step(-1);
		expect(clock.jd).toBe(BASE);
	});

	it('stops playing the moment it is stepped', () => {
		player.start();
		run(2000);
		player.step(1);
		expect(player.playing).toBe(false);
	});

	// A trip can end on a phase rather than a burn — a flyby ends on the cruise,
	// a torch route on its braking half, an aerobrake arrival on the campaign —
	// and that phase's own span is a leg like any other.
	describe('with a trip that ends on a phase', () => {
		/** A flyby: two burns and the crossing, with nothing after it. */
		const FLYBY: TimelineEntry[] = [
			entry('ascent', BASE, BASE),
			entry('injection', BASE, BASE),
			entry('cruise', BASE, BASE + CRUISE_DAYS)
		];
		let flyer: TripPlayback;

		beforeEach(() => {
			flyer = new TripPlayback({
				clock: clock as unknown as SimClock,
				entries: () => FLYBY,
				focus: (e) => focused.push(e.kind)
			});
		});

		afterEach(() => {
			flyer.dispose();
		});

		it('flies the final phase to its end instead of stopping at its start', () => {
			flyer.start();
			run(30_000);
			expect(flyer.playing).toBe(false);
			expect(clock.jd).toBe(BASE + CRUISE_DAYS);
		});

		it('resumes from inside the final phase rather than starting over', () => {
			clock.jd = BASE + CRUISE_DAYS / 2;
			flyer.start();
			// Not yet over: play means finishing this phase, from its start.
			expect(clock.jd).toBe(BASE);
			run(30_000);
			expect(clock.jd).toBe(BASE + CRUISE_DAYS);
		});

		it('starts again from the top once the whole span is flown', () => {
			flyer.start();
			run(30_000);
			flyer.start();
			expect(clock.jd).toBe(BASE);
			expect(flyer.playing).toBe(true);
		});
	});
});
