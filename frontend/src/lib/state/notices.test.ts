/**
 * The out-of-range notice clears the arrival toast that says the focused object
 * has no place at this date, once the date gives it one.
 */

import { beforeEach, describe, expect, it, vi } from 'vitest';

const { toast } = vi.hoisted(() => ({
	toast: { warning: vi.fn(), info: vi.fn(), dismiss: vi.fn() }
}));
vi.mock('svelte-sonner', () => ({ toast }));

import { UNPLACED_TOAST, dismissNotice, showNotice } from './notices';
import type { UncoveredBodies } from '$lib/scene/notice';

const quiet = {
	topic: 'out-of-range' as const,
	satellites: null,
	majorBodies: null,
	bodies: [] as UncoveredBodies[]
};

describe('unplaced arrival toast', () => {
	beforeEach(() => vi.clearAllMocks());

	it('stays while the focused object is out of range', () => {
		showNotice({ ...quiet, focusedOutOfRange: true });
		expect(toast.dismiss).not.toHaveBeenCalledWith(UNPLACED_TOAST);
	});

	it('goes when only other groups are out of range', () => {
		showNotice({ ...quiet, focusedOutOfRange: false, majorBodies: { side: 'after', jd: 2470000 } });
		expect(toast.dismiss).toHaveBeenCalledWith(UNPLACED_TOAST);
	});

	it('goes when the out-of-range notice is dismissed', () => {
		dismissNotice('out-of-range');
		expect(toast.dismiss).toHaveBeenCalledWith(UNPLACED_TOAST);
	});

	it('is left alone by the coverage pause', () => {
		dismissNotice('coverage-pause');
		expect(toast.dismiss).not.toHaveBeenCalledWith(UNPLACED_TOAST);
	});
});

/** The lines name the bodies whose own kernels end, and stay short. */
describe('out-of-range lines', () => {
	beforeEach(() => vi.clearAllMocks());
	// Noon UTC, Jan 1, 2050: the day printed stays put across most time zones.
	const jd = 2469808;
	const shown = (): string => toast.warning.mock.calls[0][1].description;

	it('names the bodies past their kernels, by edge', () => {
		showNotice({
			...quiet,
			focusedOutOfRange: false,
			bodies: [{ side: 'after', jd, ids: ['naif-715', 'naif-999'], names: ['Puck', 'Pluto'] }]
		});
		expect(shown()).toBe('Puck and Pluto: no data after Jan 1, 2050');
	});

	it('counts the names past the first three', () => {
		const names = ['Pan', 'Daphnis', 'Atlas', 'Prometheus', 'Pandora'];
		showNotice({
			...quiet,
			focusedOutOfRange: false,
			bodies: [{ side: 'outside', ids: names, names }]
		});
		expect(shown()).toBe('Pan, Daphnis, Atlas, and 2 more: no data at this time');
	});

	it('says the whole ephemeris ends before the bodies with edges of their own', () => {
		showNotice({
			...quiet,
			focusedOutOfRange: false,
			majorBodies: { side: 'before', jd },
			bodies: [{ side: 'after', jd, ids: ['naif-999'], names: ['Pluto'] }]
		});
		expect(shown().split('\n')).toEqual([
			'Planets and moons: no data before Jan 1, 2050',
			'Pluto: no data after Jan 1, 2050'
		]);
	});
});
