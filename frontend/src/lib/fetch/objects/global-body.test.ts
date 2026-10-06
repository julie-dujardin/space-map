/**
 * The body row a bundle gives: one with elements when its orbit is complete,
 * and a page-only stand-in when the scene still needs something to focus.
 */

import { describe, expect, it } from 'vitest';
import { J2000_JD } from '$lib/time/jd';
import { ObjectType } from '$lib/types/objects';
import { bodyDataFromGlobal, pageOnlyBodyData } from './global-body';
import type { ObjectDetailData } from './object-data';

const KEPLER = {
	epoch_jd: 2460000,
	a: 2.3,
	e: 0.1,
	i: 5,
	om: 20,
	w: 30,
	ma: 40,
	n: 0.2,
	parent_id: 'naif-10',
	source: 'sbdb'
};

/** A comet on a parabola: a perihelion distance and date, and no semi-major axis. */
const PARABOLIC = {
	epoch_jd: 2460000,
	e: 1,
	i: 5,
	om: 20,
	w: 30,
	q: 1.2,
	tp: 2460100,
	parent_id: 'naif-10',
	source: 'sbdb'
};

function detail(global: Record<string, unknown> | null): ObjectDetailData {
	return { global, localized: null } as unknown as ObjectDetailData;
}

/** Coverage of an object the map places at every date. */
const ALWAYS = { windows: [[null, null]] };

describe('bodyDataFromGlobal', () => {
	it('builds a row from a full element set', () => {
		const row = bodyDataFromGlobal(
			'spkid-2000001',
			detail({ name: 'Ceres', type: 'asteroid_main_belt', orbit: KEPLER, coverage: ALWAYS })
		)!;
		expect(row).toMatchObject({
			id: 'spkid-2000001',
			name: 'Ceres',
			objectType: ObjectType.ASTEROID_MAIN_BELT,
			parentId: 'naif-10',
			a: 2.3,
			ma: 40,
			n: 0.2,
			epoch: 2460000
		});
		expect(row.pageOnly).toBeUndefined();
		// Coverage with an open start: nothing gates the date it appears at.
		expect(row.visibleFromDays).toBeUndefined();
	});

	it('builds a row for a parabolic comet, which has no semi-major axis to give', () => {
		const row = bodyDataFromGlobal(
			'spkid-1000598',
			detail({ type: 'comet', orbit: PARABOLIC, coverage: ALWAYS })
		)!;
		expect(row.q).toBe(1.2);
		expect(row.tp).toBe(2460100);
	});

	it('is null for an object the map cannot place, elements or not', () => {
		// A docked module: SATCAT has its elements, and no position file holds it.
		const docked = detail({ type: 'spacecraft', orbit: KEPLER, host_id: 'norad_satcat-25544' });
		expect(bodyDataFromGlobal('norad_satcat-26400', docked)).toBeNull();
	});

	it('is null for a bundle with no orbit', () => {
		expect(bodyDataFromGlobal('norad_satcat-2', detail({ type: 'spacecraft' }))).toBeNull();
	});

	it('is null for a moon published with half an orbit', () => {
		const partial = { ...KEPLER, n: undefined };
		expect(
			bodyDataFromGlobal(
				'spkid-120000045',
				detail({ type: 'moon', orbit: partial, coverage: ALWAYS })
			)
		).toBeNull();
	});

	it('is null for half a parabola', () => {
		const partial = { ...PARABOLIC, tp: undefined };
		expect(
			bodyDataFromGlobal(
				'spkid-1000598',
				detail({ type: 'comet', orbit: partial, coverage: ALWAYS })
			)
		).toBeNull();
	});

	it('is null for an object with no bundle at all', () => {
		expect(bodyDataFromGlobal('spkid-2000001', detail(null))).toBeNull();
	});

	it('takes the date the body appears from the start of its coverage', () => {
		const found = detail({
			type: 'moon',
			orbit: KEPLER,
			coverage: { windows: [[J2000_JD + 100, null]] }
		});
		expect(bodyDataFromGlobal('spkid-120000045', found)!.visibleFromDays).toBe(100);
		// An open start is no gate.
		const always = detail({ type: 'moon', orbit: KEPLER, coverage: { windows: [[null, null]] } });
		expect(bodyDataFromGlobal('spkid-120000045', always)!.visibleFromDays).toBeUndefined();
	});
});

describe('pageOnlyBodyData', () => {
	it('stands in for an object with no orbit: a page and never a place', () => {
		const row = pageOnlyBodyData('spkid-120000243', detail({ name: 'Dactyl', type: 'moon' }))!;
		expect(row).toMatchObject({
			id: 'spkid-120000243',
			name: 'Dactyl',
			objectType: ObjectType.MOON,
			pageOnly: true,
			parentId: ''
		});
		expect(row.a).toBeNaN();
	});

	it('hangs off the host the catalogue names', () => {
		const row = pageOnlyBodyData(
			'spkid-120000243',
			detail({ name: 'Dactyl', type: 'moon', host_id: 'spkid-2000243' })
		)!;
		expect(row.parentId).toBe('spkid-2000243');
	});

	it('is null for an object with no bundle at all', () => {
		expect(pageOnlyBodyData('spkid-120000243', detail(null))).toBeNull();
	});
});
