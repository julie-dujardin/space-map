import { describe, expect, it } from 'vitest';
import {
	CELL_COUNT,
	cellOf,
	decodeId,
	extrasolarIdOf,
	extrasolarObjectId,
	isExtrasolarObjectId,
	parseExtrasolarId,
	tableOf
} from './ids';

const SIRIUS = 22137869;

describe('extrasolar IDs', () => {
	it('decodes the three fields by division', () => {
		expect(decodeId(SIRIUS)).toEqual({ serial: 0, table: 1, cell: SIRIUS - 2 ** 24 });
		const id = 900 * 2 ** 29 + SIRIUS;
		expect(decodeId(id)).toEqual({ serial: 900, table: 1, cell: SIRIUS - 2 ** 24 });
		expect(cellOf(id)).toBe(SIRIUS - 2 ** 24);
		expect(tableOf(id)).toBe(1);
	});

	it('takes a bare decimal under 2^53 with a cell and a table that can be given', () => {
		expect(parseExtrasolarId('22137869')).toBe(SIRIUS);
		expect(parseExtrasolarId('9007199254740991')).toBeNull(); // table 31, kept
		expect(parseExtrasolarId(String(2 ** 53 - 2 ** 29 + 2 ** 24 + 5))).toBe(
			2 ** 53 - 2 ** 29 + 2 ** 24 + 5
		);
	});

	it.each([
		['0'],
		['022137869'],
		['+22137869'],
		['-22137869'],
		['22137869.0'],
		['2.2e7'],
		['0x1511f0d'],
		[' 22137869'],
		[''],
		['9007199254740992'],
		['9007199254740993'],
		['12345678901234567'],
		[String(2 ** 24 + CELL_COUNT)], // cell out of range
		[String(5)] // table 0 is never given
	])('refuses %j', (text) => {
		expect(parseExtrasolarId(text)).toBeNull();
	});

	it('checks the table against the numbers the export lists', () => {
		const listed = new Set([1]);
		expect(parseExtrasolarId('22137869', listed)).toBe(SIRIUS);
		expect(parseExtrasolarId(String(2 * 2 ** 24 + 5), listed)).toBeNull();
		expect(parseExtrasolarId(String(2 * 2 ** 24 + 5))).toBe(2 * 2 ** 24 + 5);
	});

	it('maps a scene id and back', () => {
		expect(extrasolarObjectId(SIRIUS)).toBe('x-22137869');
		expect(isExtrasolarObjectId('x-22137869')).toBe(true);
		expect(isExtrasolarObjectId('extra-1')).toBe(false);
		expect(extrasolarIdOf('x-22137869')).toBe(SIRIUS);
		expect(extrasolarIdOf('x-022137869')).toBeNull();
		expect(extrasolarIdOf('naif-399')).toBeNull();
	});
});
