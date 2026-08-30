import { describe, it, expect } from 'vitest';

// No paraglide mock: the labels come out of the message files, and the point of
// the test is that the right one is picked.

import { coverageGaps, eventStripItems } from './event-timeline';
import type { ProbeEvent } from '$lib/fetch/objects/object-data';

const LAUNCH: ProbeEvent = {
	type: 'launch',
	date: '1989-10-18T16:53:40Z',
	jd: 2447818.203935,
	precision: 'second'
};

const FLYBY: ProbeEvent = {
	type: 'flyby',
	date: '1990-02-10',
	jd: 2447932.5,
	precision: 'day',
	target: { name: 'Venus', primary_type: 'naif', primary_id: '299' },
	purpose: 'gravity_assist'
};

const HIBERNATION: ProbeEvent = {
	type: 'hibernation',
	date: '2014-07-01',
	jd: 2456839.5,
	end_date: '2015-01-01',
	end_jd: 2457023.5,
	precision: 'day'
};

describe('eventStripItems', () => {
	it('draws a dated event as a moment and a span as a stretch', () => {
		const [launch, hibernation] = eventStripItems([LAUNCH, HIBERNATION]);
		expect(launch.isPhase).toBe(false);
		expect(launch.endJd).toBe(launch.startJd);
		expect(hibernation.isPhase).toBe(true);
		expect(hibernation.endJd).toBe(2457023.5);
	});

	it('names the event and hangs its place and purpose underneath', () => {
		const [flyby] = eventStripItems([FLYBY]);
		expect(flyby.label).toBe('Flyby');
		expect(flyby.detail).toBe('Venus · gravity assist');
	});

	it('calls an arrival that destroyed the craft an impact', () => {
		const [impact] = eventStripItems([
			{ ...LAUNCH, type: 'landing', outcome: 'destroyed_at_landing' }
		]);
		expect(impact.label).toBe('Impact');
	});

	it('keys on position, so two events on one date stay two', () => {
		const items = eventStripItems([LAUNCH, { ...LAUNCH, type: 'stage_separation' }]);
		expect(new Set(items.map((i) => i.id)).size).toBe(2);
	});

	it('marks an event the ephemeris does not reach, and moves nothing', () => {
		const coverage = { start_jd: 2447900, end_jd: 2460000 };
		const [launch, flyby] = eventStripItems([LAUNCH, FLYBY], coverage);
		expect(launch.note).toBeTruthy();
		expect(launch.startJd).toBe(LAUNCH.jd);
		expect(flyby.note).toBeUndefined();
	});

	it('leaves every event unmarked when the craft has no coverage at all', () => {
		expect(eventStripItems([LAUNCH]).every((i) => i.note === undefined)).toBe(true);
	});

	it('marks an event that falls in a hole between two windows', () => {
		const coverage = {
			start_jd: 2440000,
			end_jd: 2460000,
			windows: [
				[2440000, 2445000],
				[2455000, 2460000]
			] as [number, number][]
		};
		const [launch] = eventStripItems([LAUNCH], coverage);
		expect(launch.note).toBeTruthy();
	});
});

describe('coverageGaps', () => {
	it('is the run before, between and after the windows', () => {
		const coverage = {
			start_jd: 100,
			end_jd: 400,
			windows: [
				[100, 200],
				[300, 400]
			] as [number, number][]
		};
		expect(coverageGaps(coverage, 50, 450)).toEqual([
			{ startJd: 50, endJd: 100 },
			{ startJd: 200, endJd: 300 },
			{ startJd: 400, endJd: 450 }
		]);
	});

	it('is empty inside one unbroken window, and without coverage', () => {
		expect(coverageGaps({ start_jd: 0, end_jd: 1000 }, 100, 900)).toEqual([]);
		expect(coverageGaps(undefined, 0, 1)).toEqual([]);
	});
});
