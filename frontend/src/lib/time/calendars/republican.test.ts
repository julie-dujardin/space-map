import { afterEach, describe, expect, it, vi } from 'vitest';

import { gregorianToJdn } from './day-number';
import {
	formatRepublican,
	jdnToRepublican,
	republicanToJdn,
	septemberEquinoxJde,
	toRoman
} from './republican';

const on = (y: number, m: number, d: number) => jdnToRepublican(gregorianToJdn(y, m, d));

describe('jdnToRepublican', () => {
	// Dates as the Republic itself kept them. The equinox rule has to land
	// each of these; an arithmetic rule gets some of them wrong.
	it.each([
		{ event: 'proclamation, 1 vendémiaire I', at: [1792, 9, 22], is: [1, 1, 1] },
		{ event: 'execution of Louis XVI', at: [1793, 1, 21], is: [1, 5, 2] },
		{ event: '1 vendémiaire II', at: [1793, 9, 22], is: [2, 1, 1] },
		{ event: '9 thermidor II', at: [1794, 7, 27], is: [2, 11, 9] },
		{ event: '13 vendémiaire IV, after the sextile year III', at: [1795, 10, 5], is: [4, 1, 13] },
		{ event: '18 fructidor V', at: [1797, 9, 4], is: [5, 12, 18] },
		{ event: '18 brumaire VIII', at: [1799, 11, 9], is: [8, 2, 18] },
		{ event: '1 vendémiaire XII, after the sextile year XI', at: [1803, 9, 24], is: [12, 1, 1] },
		{ event: '1 vendémiaire XIV', at: [1805, 9, 23], is: [14, 1, 1] },
		{ event: 'the last day it was kept, 10 nivôse XIV', at: [1805, 12, 31], is: [14, 4, 10] }
	])('$event', ({ at: [y, m, d], is: [year, month, day] }) => {
		expect(on(y, m, d)).toMatchObject({ year, month, day });
	});

	it('closes the sextile years with a sixth complementary day', () => {
		// Year III ran 22 Sept 1794 to 22 Sept 1795: the Fête de la Révolution.
		expect(on(1795, 9, 22)).toMatchObject({ year: 3, month: 13, day: 6, complementaryDays: 6 });
		expect(on(1794, 9, 21)).toMatchObject({ year: 2, month: 13, day: 5, complementaryDays: 5 });
	});

	it('starts each year on the day of the equinox in Paris, not in Greenwich', () => {
		// The 2026 equinox falls at 00:05 UT on 23 September, already 23
		// September in Paris: an CCXXXV opens then, not on the 22nd.
		expect(on(2026, 9, 22)).toMatchObject({ year: 234, month: 13 });
		expect(on(2026, 9, 23)).toMatchObject({ year: 235, month: 1, day: 1 });
	});

	it('keeps every year 365 or 366 days, far from the years it was kept', () => {
		for (const gYear of [-3000, -500, 0, 1000, 2500, 4000, 9000]) {
			const start = republicanToJdn(gYear - 1791, 1, 1);
			const length = republicanToJdn(gYear - 1790, 1, 1) - start;
			expect([365, 366]).toContain(length);
		}
	});

	it('round-trips through republicanToJdn', () => {
		for (let jdn = gregorianToJdn(1790, 1, 1); jdn < gregorianToJdn(1810, 1, 1); jdn += 7) {
			const r = jdnToRepublican(jdn);
			expect(republicanToJdn(r.year, r.month, r.day)).toBe(jdn);
		}
	});

	it('counts the décade', () => {
		expect(on(1799, 11, 9).dayOfDecade).toBe(8); // octidi 18 brumaire
		expect(on(1794, 7, 27).dayOfDecade).toBe(9); // nonidi 9 thermidor
	});
});

describe('septemberEquinoxJde', () => {
	it('lands the 2000 equinox within minutes of 22 September 17:28 TT', () => {
		expect(septemberEquinoxJde(2000)).toBeCloseTo(2451810.228, 2);
	});
});

describe('toRoman', () => {
	it.each([
		[1, 'I'],
		[4, 'IV'],
		[14, 'XIV'],
		[79, 'LXXIX'],
		[235, 'CCXXXV'],
		[1999, 'MCMXCIX']
	])('%i is %s', (n, roman) => expect(toRoman(n)).toBe(roman));

	it('has nothing for zero, the negatives or past 3999', () => {
		expect(toRoman(0)).toBeNull();
		expect(toRoman(-5)).toBeNull();
		expect(toRoman(4000)).toBeNull();
	});
});

describe('formatRepublican', () => {
	const brumaire = on(1799, 11, 9);
	const all = { year: true, month: true, day: true };

	afterEach(() => vi.unstubAllGlobals());

	it.each([
		['fr', '18 brumaire an VIII'],
		['en', '18 Brumaire, Year VIII'],
		['de', '18. Brumaire des Jahres VIII'],
		['es', '18 de brumario del año VIII'],
		['ru', '18 брюмера VIII года'],
		['zh', '共和历8年雾月18日'],
		['ja', '共和暦8年霧月18日']
	])('writes the coup of %s as “%s”', (locale, text) => {
		expect(formatRepublican(brumaire, locale, all)).toBe(text);
	});

	it('writes the first of the month as the French do', () => {
		expect(formatRepublican(on(1792, 9, 22), 'fr', all)).toBe('1er vendémiaire an I');
	});

	it('names the complementary days for their feasts', () => {
		expect(formatRepublican(on(1795, 9, 22), 'fr', all)).toBe('jour de la Révolution an III');
		expect(formatRepublican(on(1795, 9, 22), 'en', { month: true })).toBe('Sansculottides');
	});

	it('keeps only the fields asked for', () => {
		expect(formatRepublican(brumaire, 'fr', { year: true, month: false, day: false })).toBe(
			'an VIII'
		);
		expect(formatRepublican(brumaire, 'fr', { year: true, month: true, day: false })).toBe(
			'brumaire an VIII'
		);
		expect(formatRepublican(brumaire, 'fr', { year: false, month: true, day: true })).toBe(
			'18 brumaire'
		);
		expect(formatRepublican(brumaire, 'fr', { ...all, weekday: true })).toBe(
			'octidi 18 brumaire an VIII'
		);
	});

	it('writes a year Roman numerals cannot in figures', () => {
		expect(formatRepublican(on(1700, 1, 1), 'fr', { year: true, month: false, day: false })).toBe(
			'an -92'
		);
	});

	describe('in Britain', () => {
		it('has the months as the British had them', () => {
			vi.stubGlobal('navigator', { languages: ['en-GB', 'en'], language: 'en-GB' });
			const months = Array.from({ length: 12 }, (_, i) =>
				formatRepublican({ ...brumaire, month: i + 1 }, 'en', { month: true, year: false })
			);
			expect(months).toEqual([
				'Wheezy',
				'Sneezy',
				'Freezy',
				'Slippy',
				'Drippy',
				'Nippy',
				'Showery',
				'Flowery',
				'Bowery',
				'Hoppy',
				'Croppy',
				'Poppy'
			]);
		});

		it('goes by the first English the browser asks for', () => {
			vi.stubGlobal('navigator', { languages: ['fr-FR', 'en-US', 'en-GB'], language: 'fr-FR' });
			expect(formatRepublican(brumaire, 'en', all)).toBe('18 Brumaire, Year VIII');
		});

		it('leaves a page in French alone', () => {
			vi.stubGlobal('navigator', { languages: ['en-GB'], language: 'en-GB' });
			expect(formatRepublican(brumaire, 'fr', all)).toBe('18 brumaire an VIII');
		});
	});
});

describe('jdnToRepublican, past where the equinox can be computed', () => {
	it.each([-271_000, -30_000, -5000, 9000, 30_000, 271_000])(
		'still gives a real date in %i',
		(gYear) => {
			for (const month of [1, 6, 9, 12]) {
				const r = on(gYear, month, 15);
				expect(r.month).toBeGreaterThanOrEqual(1);
				expect(r.month).toBeLessThanOrEqual(13);
				expect(r.day).toBeGreaterThanOrEqual(1);
				expect(r.day).toBeLessThanOrEqual(r.month === 13 ? r.complementaryDays : 30);
				expect(formatRepublican(r, 'en', { year: true, month: true, day: true })).not.toMatch(
					/undefined|NaN/
				);
			}
		}
	);

	it('runs on from the equinox years without a gap or an overlap', () => {
		for (const gYear of [-4002, -4001, -4000, 7999, 8000, 8001]) {
			const start = republicanToJdn(gYear - 1791, 1, 1);
			expect([365, 366]).toContain(republicanToJdn(gYear - 1790, 1, 1) - start);
		}
	});
});
