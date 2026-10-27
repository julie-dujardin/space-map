import { describe, expect, it } from 'vitest';
import {
	errorDecimals,
	fixed,
	formatDeclination,
	formatRightAscension,
	plusMinus,
	withBounds,
	withError
} from './star';
import { ltrIsolate } from './bidi';
import { joinParts } from './quantities';

/** The text without its bidi isolates and with plain spaces. */
const ISOLATES = new RegExp('[\\u2066-\\u2069]', 'g');
const NBSP = String.fromCharCode(0xa0);
const NO_BREAK = new RegExp(NBSP, 'g');
const plain = (s: string) => s.replace(ISOLATES, '').replace(NO_BREAK, ' ');

describe('star value formatting', () => {
	it('keeps two significant figures of the error', () => {
		expect(errorDecimals(1.58)).toBe(1);
		expect(errorDecimals(0.0499)).toBe(3);
		expect(errorDecimals(25.9)).toBe(0);
		expect(errorDecimals(Math.fround(0.01))).toBe(3);
		expect(errorDecimals(0)).toBe(2);
	});

	it('writes a value and its error at that precision', () => {
		expect(plain(plusMinus(379.20999, 1.58, 'mas'))).toBe('379.2 ± 1.6 mas');
		expect(plain(plusMinus(768.0665, 0.04987, 'mas'))).toBe('768.067 ± 0.050 mas');
		expect(plain(plusMinus(3.805, null, '', 3))).toBe('3.805');
		expect(plain(plusMinus(-3781.741, 0.031))).toBe('-3,781.741 ± 0.031');
	});

	it('isolates a value with an error as LTR, and writes a plain value and unit as the panels do', () => {
		expect(plusMinus(379.20999, 1.58, 'mas')).toBe(ltrIsolate(`379.2 ±${NBSP}1.6 mas`));
		expect(plusMinus(0.489, null, 'mas', 3)).toBe(joinParts({ value: '0.489', unit: 'mas' }));
		expect(plusMinus(1.141, 0, 'µm⁻¹', 3)).toBe('1.141 µm⁻¹');
		expect(plusMinus(3.805, null, '', 3)).toBe('3.805');
		expect(withBounds(1.3, null, null, 'pc')).toBe('1.30 pc');
		expect(withBounds(301, 258, 360, 'pc')).toBe(ltrIsolate('301 pc (258–360 pc)'));
	});

	it('puts an error in another unit after a coordinate', () => {
		expect(withError('06ʰ 45ᵐ 09.25ˢ', 1.234, 'mas')).toBe(
			ltrIsolate(`06ʰ 45ᵐ 09.25ˢ ±${NBSP}1.2 mas`)
		);
		expect(withError('06ʰ 45ᵐ 09.25ˢ', null, 'mas')).toBe('06ʰ 45ᵐ 09.25ˢ');
	});

	it('uses the shared spacing around units', () => {
		const text = plusMinus(1.30197, 0.000085, 'pc');
		expect(text).toContain(`±${NBSP}`);
		expect(text).toContain(' pc');
	});

	it('writes near-symmetric bounds as an error, the others as a span', () => {
		expect(plain(withBounds(2.637, 2.626, 2.648, 'pc'))).toBe('2.637 ± 0.011 pc');
		expect(plain(withBounds(301, 258, 360, 'pc'))).toBe('301 pc (258–360 pc)');
		expect(plain(withBounds(-0.1806, -0.1816, -0.1786, 'dex'))).toBe(
			'-0.1806 dex (-0.1816 – -0.1786 dex)'
		);
		expect(plain(withBounds(5.1, null, 5.2))).toBe('5.10');
	});

	it('writes right ascension in time and declination in arc, to their errors', () => {
		expect(plain(formatRightAscension(101.28715533, -16.71611586, 1.2))).toBe('06ʰ 45ᵐ 08.917279ˢ');
		expect(plain(formatDeclination(-16.71611586, 1.0))).toBe('-16° 42′ 58.0171″');
		expect(plain(formatDeclination(-0.25, 1000))).toBe('-00° 15′ 00.0″');
		expect(plain(formatDeclination(45, null))).toBe('+45° 00′ 00.0″');
	});

	it('carries a rounded 60 up to the next field', () => {
		expect(plain(formatRightAscension(15 * (1 + 59 / 60 + 59.9999 / 3600), 0, 15_000))).toBe(
			'02ʰ 00ᵐ 00.0ˢ'
		);
		expect(plain(formatDeclination(10 + 59 / 60 + 59.99 / 3600, 1000))).toBe('+11° 00′ 00.0″');
	});

	it('formats in the reader’s locale', () => {
		expect(fixed(1234.5, 1)).toBe('1,234.5');
	});
});
