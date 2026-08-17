import { describe, expect, it } from 'vitest';
import { cancerRiskPerYear, formatDoseRate, formatSieverts, timeToLethalDose } from './radiation';

/**
 * The figures these are asked to render span fifteen orders of magnitude, and
 * the two ends are not the same quantity — so what is pinned here is that each
 * end reads as itself rather than as scientific notation or as a percentage
 * nobody can picture.
 */
describe('dose rates', () => {
	it('prefixes each body into its own readable range', () => {
		// Europa's surface, Chang'e-4 on the Moon, UNSCEAR's Earth ground, and
		// Venus's surface: the whole table, in order.
		expect(formatSieverts(1e3)).toBe('1,000 Sv');
		expect(formatSieverts(1.369e-3)).toBe('1.37 mSv');
		expect(formatSieverts(1.07e-6)).toBe('1.07 µSv');
		expect(formatSieverts(2.4e-12)).toBe('2.4 pSv');
	});

	it('says nothing rather than zero for a missing figure', () => {
		expect(formatSieverts(0)).toBe('');
		expect(formatSieverts(Number.NaN)).toBe('');
		expect(formatDoseRate(0)).toBe('');
	});

	it('reads as a rate', () => {
		expect(formatDoseRate(1.369e-3)).toBe('1.37 mSv per day');
	});
});

describe('what it does to a person', () => {
	it('turns a surface rate into a year of added cancer risk', () => {
		// A year on the Moon at Chang'e-4's reading: 0.5 Sv against ICRP's
		// 4.1% per sievert.
		expect(cancerRiskPerYear(1.369e-3)).toBe('2.1%');
		// Earth's own ground, which has to stay legible at four decimal places
		// rather than rounding to zero.
		expect(cancerRiskPerYear(1.07e-6)).toMatch(/^0\.0/);
	});

	it('gives up on decimals before they outrun the digits', () => {
		// Venus's surface. Written plainly it is "0.0000000036%", which reads as
		// a typo rather than as a size.
		expect(cancerRiskPerYear(2.4e-12)).toBe('3.6×10⁻⁹%');
	});

	it('turns a trapped rate into how long it takes to kill', () => {
		// Europa's surface: 4.5 Gy at a thousand a day is under seven minutes,
		// and a percentage of a lethal dose would read as two million percent.
		expect(timeToLethalDose(1e3)).toMatch(/minute/);
	});

	it('reads Io as its own dose rather than as Europa rescaled', () => {
		// The two are level at matched shielding, but Io is published behind
		// 100 mils and Europa behind 0.11 g/cm², so the panel figures differ.
		expect(formatDoseRate(3.57e2)).toBe('357 Sv per day');
		expect(timeToLethalDose(3.57e2)).toMatch(/minute/);
	});
});
