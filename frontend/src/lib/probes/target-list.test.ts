import { describe, expect, it } from 'vitest';
import type { ProbeEvent } from '$lib/fetch/objects/object-data';
import { targetVisits } from './target-list';

let jd = 2450000;
function ev(partial: Partial<ProbeEvent> & { type: ProbeEvent['type']; date: string }): ProbeEvent {
	return { jd: jd++, precision: 'day', ...partial } as ProbeEvent;
}
const earth = { name: 'Earth', primary_type: 'naif', primary_id: '399' };
const bennu = { name: 'Bennu', primary_type: 'spkid', primary_id: '20101955' };

describe('targetVisits', () => {
	it('groups by target, most recent stop first, and keys the object id', () => {
		const visits = targetVisits([
			ev({ type: 'flyby', date: '2017-09-22', target: earth }),
			ev({ type: 'orbit_insertion', date: '2018-12-03', target: bennu })
		]);
		expect(visits.map((v) => v.target.name)).toEqual(['Bennu', 'Earth']);
		expect(visits[0].objectId).toBe('spkid-20101955');
	});

	it('leaves the object id unset on a bare-name target', () => {
		const visits = targetVisits([
			ev({ type: 'flyby', date: '2005-01-01', target: { name: 'MASCOT' } })
		]);
		expect(visits[0].objectId).toBeUndefined();
	});

	it('folds an orbit stay from insertion to departure, hiding the departure', () => {
		const visits = targetVisits([
			ev({ type: 'orbit_insertion', date: '2018-12-03', target: bennu }),
			ev({ type: 'sample_collection', date: '2020-10-20', target: bennu }),
			ev({ type: 'orbit_departure', date: '2021-05-10', target: bennu })
		]);
		expect(visits[0].activities.map((a) => a.label)).toHaveLength(2);
		expect(visits[0].activities[0].dates).toContain('–');
		expect(visits[0].activities[0].dates).toContain('2018');
		expect(visits[0].activities[0].dates).toContain('2021');
	});

	it('keeps a closing re-entry as its own line while it ends the stay', () => {
		const visits = targetVisits([
			ev({ type: 'orbit_insertion', date: '2004-07-01', target: { name: 'Saturn' } }),
			ev({ type: 'reentry', date: '2017-09-15', target: { name: 'Saturn' } })
		]);
		const labels = visits[0].activities;
		expect(labels).toHaveLength(2);
		expect(labels[0].dates).toContain('2017');
	});

	it('does not fold a failed insertion into a stay', () => {
		const visits = targetVisits([
			ev({ type: 'orbit_insertion', date: '2010-12-07', target: { name: 'Venus' }, failed: true }),
			ev({ type: 'orbit_insertion', date: '2015-12-07', target: { name: 'Venus' } })
		]);
		// The failed attempt keeps its own labelled line; the real one is a stay.
		expect(visits[0].activities).toHaveLength(2);
	});

	it('lists years for a repeated activity instead of a range', () => {
		const visits = targetVisits([
			ev({ type: 'flyby', date: '2024-08-20', target: earth, purpose: 'gravity_assist' }),
			ev({ type: 'flyby', date: '2026-09-29', target: earth, purpose: 'gravity_assist' }),
			ev({ type: 'flyby', date: '2029-01-18', target: earth, purpose: 'gravity_assist' })
		]);
		expect(visits[0].activities).toHaveLength(1);
		expect(visits[0].activities[0].dates).toBe('2024, 2026, 2029');
	});
});
