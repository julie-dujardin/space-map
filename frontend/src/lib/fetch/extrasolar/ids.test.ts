import { describe, expect, it } from 'vitest';
import {
	CELL_COUNT,
	cellOf,
	decodeId,
	extrasolarIdOf,
	extrasolarObjectId,
	isExtrasolarObjectId,
	isStarObjectId,
	parseExtrasolarId,
	planetObjectId,
	planetOfObjectId,
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

	it('maps a planet to its scene id and back', () => {
		expect(planetObjectId(27424668, 3)).toBe('x-27424668-b-3');
		expect(planetOfObjectId('x-27424668-b-3')).toEqual({ host: 27424668, n: 3 });
		// A planet is in the x namespace, but it names no star.
		expect(isExtrasolarObjectId('x-27424668-b-3')).toBe(true);
		expect(extrasolarIdOf('x-27424668-b-3')).toBeNull();
	});

	it('tells a star from a planet in the x namespace', () => {
		expect(isStarObjectId('x-22137869')).toBe(true);
		expect(isStarObjectId('x-27424668-b-3')).toBe(false);
		// Malformed ids go to the star lookup, which refuses them.
		expect(isStarObjectId('x-abc')).toBe(true);
		expect(isStarObjectId('x-27424668-b-0')).toBe(true);
		expect(isStarObjectId('naif-399')).toBe(false);
		expect(isStarObjectId('extra-1')).toBe(false);
	});

	it.each([
		['x-27424668'],
		['x-27424668-b-0'],
		['x-27424668-b-01'],
		['x-027424668-b-1'],
		['x-5-b-1'], // table 0
		['x-27424668-c-1'],
		['naif-399'],
		['x-27424668-b-1-b-2']
	])('reads no planet in %j', (id) => {
		expect(planetOfObjectId(id)).toBeNull();
	});
});
