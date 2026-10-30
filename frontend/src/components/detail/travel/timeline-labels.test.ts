import { describe, it, expect } from 'vitest';
import { SPEED_OF_LIGHT_KM_S } from '$lib/math/units';
import type { TimelineEntry } from '$lib/travel/timeline';
import { entryDetail } from './timeline-labels';

/** The first burn of a flat-out trip to Proxima at 1 g. */
const BOOST: TimelineEntry = {
	id: '1:boost',
	kind: 'boost',
	startJd: 0,
	endJd: 1071,
	days: 1071,
	isPhase: true,
	bodyId: null,
	bodyName: '',
	dvKms: 1.83 * SPEED_OF_LIGHT_KM_S
};

describe('entryDetail', () => {
	it('gives the Δv of a burn past c in multiples of c', () => {
		expect(entryDetail(BOOST)).toContain('1.83 c');
	});

	it('adds the ship clock where it reads differently from the Earth one', () => {
		expect(entryDetail({ ...BOOST, shipDays: 646 })).toContain('aboard');
		expect(entryDetail({ ...BOOST, shipDays: 1071 - 1e-6 })).not.toContain('aboard');
		expect(entryDetail(BOOST)).not.toContain('aboard');
	});
});
