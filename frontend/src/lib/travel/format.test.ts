import { afterEach, describe, it, expect } from 'vitest';
import { ltrIsolate } from '$lib/format/bidi';
import { formatJulianDate } from '$lib/format/date';
import { G0_M_S2 } from '$lib/math/travel/constants';
import { LIGHT_YEAR_KM, SPEED_OF_LIGHT_KM_S } from '$lib/math/units';
import { getLocale, overwriteGetLocale } from '$lib/paraglide/runtime.js';
import { getSettings } from '$lib/state/settings.svelte';
import { DAYS_PER_YEAR, J2000_JD } from '$lib/time/jd';
import {
	dvParts,
	formatAcceleration,
	formatDv,
	formatDvBrief,
	formatGray,
	formatLorentzFactor,
	formatSievert,
	formatSpeed,
	formatTripDate,
	isPastLight,
	lightPercent,
	lightYearParts,
	shipDuration
} from './format';

describe('formatAcceleration', () => {
	it('quotes a drive you could stand up in as a fraction of a gravity', () => {
		expect(formatAcceleration(G0_M_S2 / 3)).toBe('0.33 g');
		expect(formatAcceleration(G0_M_S2 * 1.5)).toBe('1.5 g');
	});

	// A hundredth of a gravity is where the fraction stops saying anything.
	it('drops to m/s² for a drive you would never feel', () => {
		expect(formatAcceleration(0.002)).toBe('0.002 m/s²');
	});

	it('refuses to render an acceleration that is not one', () => {
		expect(formatAcceleration(0)).toBe('—');
		expect(formatAcceleration(NaN)).toBe('—');
	});
});

describe('formatDv', () => {
	it('stays in km/s below ten thousand of them', () => {
		expect(formatDv(9999.99)).toBe('9,999.99 km/s');
		expect(formatDvBrief(7586.04)).toBe('7,586.0 km/s');
		expect(dvParts(7586.04)).toEqual({ value: '7,586.0', unit: 'km/s' });
	});

	it('climbs to Mm/s where six figures of km/s would not fit', () => {
		expect(formatDv(62500)).toBe('62.5 Mm/s');
		expect(formatDvBrief(125_000)).toBe('125 Mm/s');
		expect(formatDv(299_000)).toBe('299 Mm/s');
	});

	it('counts multiples of c from the speed of light up', () => {
		expect(isPastLight(SPEED_OF_LIGHT_KM_S)).toBe(true);
		expect(isPastLight(299_000)).toBe(false);
		expect(formatDvBrief(SPEED_OF_LIGHT_KM_S)).toBe('1 c');
		expect(dvParts(1_250_000)).toEqual({ value: '4.17', unit: 'c' });
	});
});

describe('formatSpeed', () => {
	it('stays in km/s below a hundredth of c', () => {
		expect(formatSpeed(993)).toBe('993.00 km/s');
		expect(lightPercent(993)).toBeNull();
	});

	it('flips to a percentage of c from 1% up', () => {
		expect(formatSpeed(2997.92458)).toBe('1% c');
		expect(formatSpeed(6500)).toBe('2.2% c');
	});

	// Newtonian arithmetic on a fictional drive can pass c; the figure is the
	// model's honest output, so it is shown rather than capped.
	it('does not cap a superluminal figure', () => {
		expect(formatSpeed(449688.687)).toBe('150% c');
	});

	it('refuses to render a nonsense speed', () => {
		expect(formatSpeed(NaN)).toBe('—');
	});

	it('never rounds a speed under c up to 100% c', () => {
		expect(lightPercent(0.9495 * SPEED_OF_LIGHT_KM_S)).toBe('95');
		expect(lightPercent(0.9952 * SPEED_OF_LIGHT_KM_S)).toBe('99.5');
		expect(lightPercent(0.999991 * SPEED_OF_LIGHT_KM_S)).toBe('99.999');
	});
});

describe('formatTripDate', () => {
	afterEach(() => getSettings().setDateFormat('auto'));

	it('writes a date in the range of Date as a date', () => {
		expect(formatTripDate(J2000_JD, J2000_JD)).toBe(formatJulianDate(J2000_JD));
	});

	it('writes years with five and six digits', () => {
		// Gregorian years, so that the dates fall in the years named.
		const in19500 = J2000_JD + 17_500 * 365.2425;
		const in250000 = J2000_JD + 248_000 * 365.2425;
		expect(formatTripDate(in19500, J2000_JD)).toMatch(/\b19500\b/);
		expect(formatTripDate(in250000, J2000_JD)).toMatch(/\b250000\b/);
		getSettings().setDateFormat('iso');
		expect(formatTripDate(in250000, J2000_JD)).toMatch(/^\+250000-\d\d-\d\d$/);
	});

	it('writes a date past the range of Date as years after departure', () => {
		const departJd = J2000_JD + 9_000 * DAYS_PER_YEAR;
		expect(formatTripDate(departJd + 300_000 * DAYS_PER_YEAR, departJd)).toBe('+300,000 years');
		getSettings().setDateFormat('iso');
		expect(formatTripDate(departJd + 300_000 * DAYS_PER_YEAR, departJd)).toBe('+300,000 years');
	});
});

describe('the clocks of a trip between stars', () => {
	it('gives the ship time only where it reads differently', () => {
		expect(shipDuration(2142, 1293)).toBe('3y 6m');
		expect(shipDuration(7_120_000, 7_119_999.9)).toBeNull();
		expect(shipDuration(100, undefined)).toBeNull();
	});

	it('writes a Lorentz factor with the digits that carry it', () => {
		expect(formatLorentzFactor(1.000000024)).toBe('1.00');
		expect(formatLorentzFactor(3.188)).toBe('3.19');
		expect(formatLorentzFactor(10.24)).toBe('10.2');
	});

	it('writes the distance between stars in light years', () => {
		expect(lightYearParts(4.2465 * LIGHT_YEAR_KM)).toEqual({ value: '4.25', unit: 'ly' });
		expect(lightYearParts(0.0619 * LIGHT_YEAR_KM)).toEqual({ value: '0.0619', unit: 'ly' });
	});
});

describe('figures in the locale of the reader', () => {
	const base = getLocale;
	afterEach(() => overwriteGetLocale(base));

	it.each([
		{ locale: 'en', large: '24,000 Sv', small: '1.2 Sv' },
		{ locale: 'de', large: '24.000 Sv', small: '1,2 Sv' },
		{ locale: 'fr', large: '24\u202f000 Sv', small: '1,2 Sv' },
		{ locale: 'ar', large: '24,000 \u200eSv\u200e', small: '1.2 \u200eSv\u200e' },
		{ locale: 'he', large: '24,000 Sv', small: '1.2 Sv' }
	] as const)('writes a dose with the separators of $locale', ({ locale, large, small }) => {
		overwriteGetLocale(() => locale);
		expect(formatSievert(24_000)).toBe(large);
		expect(formatSievert(1.234)).toBe(small);
	});

	it('writes a dose of a million sieverts and more with an exponent, in one isolate', () => {
		expect(formatSievert(990_000)).toBe('990,000 Sv');
		// It rounds before it picks the form.
		expect(formatSievert(999_999)).toBe(ltrIsolate('1×10⁶\u00a0Sv'));
		expect(formatSievert(7.78e8)).toBe(ltrIsolate('7.8×10⁸\u00a0Sv'));
		expect(formatSievert(2.69e9)).toBe(ltrIsolate('2.7×10⁹\u00a0Sv'));
		overwriteGetLocale(() => 'fr');
		expect(formatSievert(7.78e8)).toBe(ltrIsolate('7,8×10⁸\u00a0Sv'));
		overwriteGetLocale(() => 'ru');
		expect(formatSievert(7.78e8)).toBe(ltrIsolate('7,8×10⁸\u00a0Зв'));
		overwriteGetLocale(() => 'ar');
		expect(formatSievert(7.78e8)).toBe(ltrIsolate('7.8×10⁸\u00a0\u200eSv\u200e'));
	});

	it('keeps two significant figures in every unit of dose', () => {
		expect(formatSievert(0.0456)).toBe('46 mSv');
		expect(formatGray(4567)).toBe('4.6 kGy');
		overwriteGetLocale(() => 'fr');
		expect(formatGray(4567)).toBe('4,6 kGy');
	});

	it('groups the years of a date past the range of Date', () => {
		overwriteGetLocale(() => 'fr');
		const departJd = J2000_JD + 9_000 * DAYS_PER_YEAR;
		expect(formatTripDate(departJd + 300_000 * DAYS_PER_YEAR, departJd)).toBe('+300\u202f000 ans');
	});
});
