import { describe, it, expect } from 'vitest';
import { axisTicks, buildTimeline, entryIndexAt, stepEntryIndex } from './timeline';
import { legSeconds } from './playback.svelte';
import {
	buildAssistRoute,
	buildConstantThrustRoute,
	buildRoute,
	hohmannTransferDays,
	nextTransferWindows
} from '$lib/math/travel';
import { EARTH, J2000, JUPITER, MARS, VENUS } from '$lib/math/travel/test-fixtures';
import { dateToJD } from '$lib/format/date';

const MARS_WINDOW = nextTransferWindows(EARTH, MARS, J2000, 1)[0];
const MARS_TOF = hohmannTransferDays(EARTH, MARS)!;

/** The name of anything is its id here — the labels are the component's job. */
const idAsName = (id: string) => id;

describe('buildTimeline', () => {
	it('lists every leg of the route, in flight order', () => {
		const route = buildRoute(EARTH, MARS, MARS_WINDOW, MARS_TOF, { arrivalMode: 'landing' })!;
		const entries = buildTimeline(route, idAsName);
		expect(entries.map((e) => e.kind)).toEqual(route.legs.map((l) => l.kind));
		for (let i = 1; i < entries.length; i++) {
			expect(entries[i].startJd).toBeGreaterThanOrEqual(entries[i - 1].endJd - 1e-9);
		}
	});

	it('runs from the departure to the arrival without being told either', () => {
		const route = buildRoute(EARTH, MARS, MARS_WINDOW, MARS_TOF)!;
		const entries = buildTimeline(route, idAsName);
		// The dates are the legs' own durations accumulated, so the crossing ending
		// on the arrival date is what says the two agree.
		expect(entries[0].startJd).toBeCloseTo(route.departJd, 9);
		expect(entries.find((e) => e.kind === 'cruise')!.endJd).toBeCloseTo(route.arriveJd, 9);
	});

	it('carries on past the arrival date when the orbit has to be walked down', () => {
		const route = buildRoute(EARTH, MARS, MARS_WINDOW, MARS_TOF, {
			arrivalMode: 'low-orbit',
			aero: 'aerobraking'
		})!;
		const entries = buildTimeline(route, idAsName);
		const campaign = entries.find((e) => e.kind === 'aerobrake');
		expect(campaign).toBeDefined();
		// Months of passes, and the only leg that costs time without a burn or a
		// crossing — so the trip really does outlast the transfer it was priced on.
		expect(campaign!.isPhase).toBe(true);
		expect(campaign!.startJd).toBeCloseTo(route.arriveJd, 9);
		expect(entries[entries.length - 1].endJd).toBeGreaterThan(route.arriveJd);
		// It happens at the destination, so there is something to look at.
		expect(campaign!.bodyId).toBe(MARS.id);
	});

	it('calls a leg that takes time a phase and one that does not an event', () => {
		const route = buildRoute(EARTH, MARS, MARS_WINDOW, MARS_TOF)!;
		const entries = buildTimeline(route, idAsName);
		const cruise = entries.find((e) => e.kind === 'cruise')!;
		expect(cruise.isPhase).toBe(true);
		expect(cruise.endJd - cruise.startJd).toBeCloseTo(route.tofDays, 9);
		// A burn happens at a point, so it has no width on the bar.
		for (const entry of entries.filter((e) => e.kind !== 'cruise')) {
			expect(entry.isPhase).toBe(false);
			expect(entry.endJd).toBe(entry.startJd);
		}
	});

	it('puts each leg at the end of the trip it happens at', () => {
		const route = buildRoute(EARTH, MARS, MARS_WINDOW, MARS_TOF, { arrivalMode: 'landing' })!;
		const entries = buildTimeline(route, idAsName);
		const at = (kind: string) => entries.find((e) => e.kind === kind)!.bodyId;
		expect(at('ascent')).toBe(EARTH.id);
		expect(at('injection')).toBe(EARTH.id);
		expect(at('capture')).toBe(MARS.id);
		expect(at('descent')).toBe(MARS.id);
		// A coast is at neither end — that is the whole of what a cruise is.
		expect(at('cruise')).toBeNull();
	});

	it('carries every leg its Δv, so the bar and the ladder cannot disagree', () => {
		const route = buildRoute(EARTH, MARS, MARS_WINDOW, MARS_TOF, { arrivalMode: 'landing' })!;
		const entries = buildTimeline(route, idAsName);
		const total = entries.reduce((sum, e) => sum + e.dvKms, 0);
		expect(total).toBeCloseTo(route.totalDvKms, 9);
	});

	it('names the bodies through the resolver it is given', () => {
		const route = buildRoute(EARTH, MARS, MARS_WINDOW, MARS_TOF)!;
		const entries = buildTimeline(route, (id) => (id === MARS.id ? 'Mars' : 'Earth'));
		expect(entries[0].bodyName).toBe('Earth');
		expect(entries[entries.length - 1].bodyName).toBe('Mars');
	});

	it('sits a swing-by between two cruises, at the body it passes', () => {
		const route = buildAssistRoute(EARTH, VENUS, JUPITER, J2000, 150, 400)!;
		const entries = buildTimeline(route, idAsName);
		const assist = entries.find((e) => e.kind === 'assist')!;
		expect(assist.bodyId).toBe(VENUS.id);
		expect(assist.altitudeKm).toBe(route.flybys![0].altitudeKm);
		expect(assist.isPhase).toBe(false);
		// One cruise each side, and the pass falls between them.
		const cruises = entries.filter((e) => e.kind === 'cruise');
		expect(cruises).toHaveLength(2);
		expect(cruises[0].endJd).toBeCloseTo(assist.startJd, 9);
		expect(cruises[1].startJd).toBeCloseTo(assist.startJd, 9);
		expect(assist.startJd).toBeCloseTo(route.flybys![0].jd, 9);
	});

	it('splits a held drive into the two phases it is flown in', () => {
		const route = buildConstantThrustRoute(EARTH, MARS, J2000, 0.1)!;
		const entries = buildTimeline(route, idAsName);
		const boost = entries.find((e) => e.kind === 'boost')!;
		const brake = entries.find((e) => e.kind === 'brake')!;
		expect(boost.isPhase).toBe(true);
		expect(brake.isPhase).toBe(true);
		// The flip is where one ends and the other starts; there is no third thing.
		expect(boost.endJd).toBeCloseTo(brake.startJd, 9);
		expect(boost.endJd).toBeCloseTo(route.departJd + route.tofDays / 2, 6);
	});

	describe('the orbits at either end', () => {
		const ENDS = { departure: EARTH, target: MARS };

		it('brackets the legs with the orbit the trip leaves and the one it ends in', () => {
			const route = buildRoute(EARTH, MARS, MARS_WINDOW, MARS_TOF, {
				departureMode: 'orbit',
				arrivalMode: 'low-orbit'
			})!;
			const entries = buildTimeline(route, idAsName, ENDS);
			expect(entries[0].kind).toBe('start-orbit');
			expect(entries[entries.length - 1].kind).toBe('final-orbit');
			// Neither is anything that happens: nothing is spent and no time passes.
			for (const entry of [entries[0], entries[entries.length - 1]]) {
				expect(entry.dvKms).toBe(0);
				expect(entry.days).toBe(0);
				expect(entry.isPhase).toBe(false);
			}
			// The starting orbit sits half a revolution before the injection — in
			// the orbit, not yet leaving — so it and the burn are different moments.
			expect(entries[0].startJd).toBeLessThan(route.departJd);
			expect(entries[0].startJd).toBeGreaterThan(route.departJd - 1);
			expect(entries[0].bodyId).toBe(EARTH.id);
			expect(entries[entries.length - 1].bodyId).toBe(MARS.id);
			// The legs in between are untouched.
			expect(entries.slice(1, -1).map((e) => e.kind)).toEqual(route.legs.map((l) => l.kind));
		});

		it('leaves a launch and a landing to say so themselves', () => {
			const route = buildRoute(EARTH, MARS, MARS_WINDOW, MARS_TOF, {
				departureMode: 'surface',
				arrivalMode: 'landing'
			})!;
			const entries = buildTimeline(route, idAsName, ENDS);
			expect(entries.map((e) => e.kind)).toEqual(route.legs.map((l) => l.kind));
		});

		it('waits for the campaign that walks the orbit down before saying it is in one', () => {
			const route = buildRoute(EARTH, MARS, MARS_WINDOW, MARS_TOF, {
				arrivalMode: 'low-orbit',
				aero: 'aerobraking'
			})!;
			const entries = buildTimeline(route, idAsName, ENDS);
			const final = entries[entries.length - 1];
			expect(final.kind).toBe('final-orbit');
			// Half a revolution past the campaign's end: settled in the orbit.
			expect(final.startJd).toBeGreaterThan(route.arriveJd);
			expect(final.startJd).toBeGreaterThan(entries[entries.length - 2].endJd);
			expect(final.startJd).toBeLessThan(entries[entries.length - 2].endJd + 1);
		});

		it('spreads coincidently priced arrival instants along the drawn dates', () => {
			const route = buildRoute(EARTH, MARS, MARS_WINDOW, MARS_TOF, {
				departureMode: 'surface',
				arrivalMode: 'low-orbit',
				aero: 'aerocapture'
			})!;
			// The drawn geometry's dates: liftoff before the injection, the crossing
			// from the handover, the pass at its real periapsis, the raise at the
			// apoapsis after it.
			const drawn = {
				liftoffJd: route.departJd - 0.1,
				cruiseJd: route.departJd + 2.5,
				captureJd: route.arriveJd - 0.1,
				raiseJd: route.arriveJd + 0.05
			};
			const entries = buildTimeline(route, idAsName, ENDS, drawn);
			const at = (kind: string) => entries.find((e) => e.kind === kind)!;
			expect(at('ascent').startJd).toBe(drawn.liftoffJd);
			expect(at('cruise').startJd).toBe(drawn.cruiseJd);
			// The cruise's far end stays priced: a re-dated start pushes nothing.
			expect(at('cruise').endJd).toBeCloseTo(route.arriveJd, 9);
			expect(at('aero-pass').startJd).toBe(drawn.captureJd);
			expect(at('raise').startJd).toBe(drawn.raiseJd);
			expect(at('final-orbit').startJd).toBeGreaterThan(drawn.raiseJd);
			// Every clickable instant is its own moment now.
			const dates = entries.map((e) => e.startJd);
			expect(new Set(dates).size).toBe(dates.length);
		});

		it('carries the shape of the orbit and the body it goes round', () => {
			const route = buildRoute(EARTH, MARS, MARS_WINDOW, MARS_TOF, {
				departureMode: 'orbit',
				arrivalMode: 'capture'
			})!;
			const entries = buildTimeline(route, idAsName, ENDS);
			const start = entries[0].orbit!;
			expect(start.bodyRadiusKm).toBe(EARTH.radiusKm);
			expect(start.shape.rApoKm).toBe(start.shape.rPeriKm);
			// The capture ellipse is the loose one an orbiter really enters first.
			const final = entries[entries.length - 1].orbit!;
			expect(final.bodyRadiusKm).toBe(MARS.radiusKm);
			expect(final.shape.rApoKm).toBeGreaterThan(final.shape.rPeriKm * 10);
		});

		it('has no ends to draw before the bodies are known', () => {
			const route = buildRoute(EARTH, MARS, MARS_WINDOW, MARS_TOF, {
				departureMode: 'orbit',
				arrivalMode: 'low-orbit'
			})!;
			expect(buildTimeline(route, idAsName).map((e) => e.kind)).toEqual(
				route.legs.map((l) => l.kind)
			);
		});
	});
});

describe('entryIndexAt', () => {
	const entries = buildTimeline(buildRoute(EARTH, MARS, MARS_WINDOW, MARS_TOF)!, idAsName);

	it('answers with the leg last reached', () => {
		const cruise = entries.findIndex((e) => e.kind === 'cruise');
		expect(entryIndexAt(entries, entries[cruise].startJd + 10)).toBe(cruise);
		expect(entryIndexAt(entries, entries[entries.length - 1].startJd + 1000)).toBe(
			entries.length - 1
		);
	});

	it('reads a clock set before the trip as the first leg', () => {
		// "Not left yet" is the launch's own state, not a thing of its own to draw.
		expect(entryIndexAt(entries, entries[0].startJd - 500)).toBe(0);
	});

	it('has nothing to answer with for no entries', () => {
		expect(entryIndexAt([], J2000)).toBe(-1);
	});
});

describe('stepEntryIndex', () => {
	const entries = buildTimeline(buildRoute(EARTH, MARS, MARS_WINDOW, MARS_TOF)!, idAsName);
	const cruise = entries.findIndex((e) => e.kind === 'cruise');

	it('steps back to the start of the phase it is inside, not past it', () => {
		const mid = entries[cruise].startJd + entries[cruise].days / 2;
		// Mid-crossing, "back" means the start of the crossing; from there, the
		// entry before it.
		expect(stepEntryIndex(entries, mid, -1)).toBe(cruise);
		expect(stepEntryIndex(entries, entries[cruise].startJd, -1)).toBe(cruise - 1);
	});

	it('clamps at both ends of the trip', () => {
		expect(stepEntryIndex(entries, entries[0].startJd - 500, -1)).toBe(0);
		const lastJd = entries[entries.length - 1].startJd;
		expect(stepEntryIndex(entries, lastJd + 1000, 1)).toBe(entries.length - 1);
	});
});

describe('axisTicks', () => {
	/** Every tick, as the local calendar has it. */
	function dates(startJd: number, endJd: number, maxTicks = 6) {
		return axisTicks(startJd, endJd, maxTicks).map((tick) => tick.date);
	}

	it('walks whole years across a long trip', () => {
		const start = dateToJD(new Date(2030, 5, 15));
		const ticks = axisTicks(start, start + 365.25 * 24, 6);
		expect(ticks.length).toBeGreaterThan(2);
		expect(ticks.length).toBeLessThanOrEqual(6);
		for (const tick of ticks) {
			expect(tick.unit).toBe('year');
			// On New Year, or the label lies about where it sits.
			expect([tick.date.getMonth(), tick.date.getDate()]).toEqual([0, 1]);
			expect(tick.date.getFullYear() % 5).toBe(0);
		}
	});

	it('walks months across an interplanetary transfer', () => {
		const start = dateToJD(new Date(2031, 2, 3));
		const ticks = axisTicks(start, start + 260, 6);
		expect(ticks.length).toBeGreaterThan(2);
		for (const tick of ticks) {
			expect(tick.unit).toBe('month');
			expect(tick.date.getDate()).toBe(1);
		}
	});

	it('carries the boundary as a date, since a round-trip through a JD drifts off it', () => {
		// `new Date(fractionalMs)` truncates, so a boundary that went out through a
		// Julian Date can come back a millisecond short — and a millisecond short of
		// New Year is labelled with the wrong year.
		const start = dateToJD(new Date(2030, 5, 15));
		for (const tick of axisTicks(start, start + 365.25 * 24, 6)) {
			expect(tick.date.getTime()).toBe(new Date(tick.date.getFullYear(), 0, 1).getTime());
			// Still the instant it is drawn at, to well under a millisecond.
			expect(Math.abs(dateToJD(tick.date) - tick.jd) * 86_400_000).toBeLessThan(1);
		}
	});

	it('walks days across a lunar hop, and hours across a shorter one', () => {
		const start = dateToJD(new Date(2031, 2, 3, 7, 30));
		expect(axisTicks(start, start + 8, 6).every((t) => t.unit === 'day')).toBe(true);
		const hours = axisTicks(start, start + 1.5, 6);
		expect(hours.length).toBeGreaterThan(1);
		expect(hours.every((t) => t.unit === 'hour')).toBe(true);
	});

	it('never runs past the ends it was given', () => {
		const start = dateToJD(new Date(2031, 2, 3, 7, 30));
		for (const span of [0.4, 3, 40, 260, 4000, 300_000]) {
			const ticks = axisTicks(start, start + span, 6);
			expect(ticks.length).toBeLessThanOrEqual(6);
			for (const tick of ticks) {
				expect(tick.jd).toBeGreaterThanOrEqual(start);
				expect(tick.jd).toBeLessThanOrEqual(start + span);
			}
		}
	});

	it('draws nothing for a span there is no room in', () => {
		expect(axisTicks(J2000, J2000)).toEqual([]);
		expect(axisTicks(J2000, J2000 - 10)).toEqual([]);
		expect(axisTicks(J2000, Number.NaN)).toEqual([]);
	});

	it('holds its ticks in order', () => {
		const start = dateToJD(new Date(2031, 2, 3));
		const walked = dates(start, start + 900);
		for (let i = 1; i < walked.length; i++) {
			expect(walked[i].getTime()).toBeGreaterThan(walked[i - 1].getTime());
		}
	});
});

describe('legSeconds', () => {
	it('splits the trip in proportion to how long each phase takes', () => {
		expect(legSeconds(300, 600)).toBeCloseTo(legSeconds(600, 600) / 2, 9);
	});

	it('holds a floor, so a short phase between two long ones is still watchable', () => {
		expect(legSeconds(1, 10_000)).toBeGreaterThan(1);
		expect(legSeconds(5, 0)).toBeGreaterThan(0);
	});

	it('gives a burn no time at all, since nothing moves while it happens', () => {
		expect(legSeconds(0, 600)).toBe(0);
	});
});
