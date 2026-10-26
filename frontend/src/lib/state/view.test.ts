import { describe, expect, it } from 'vitest';
import {
	BODY_ROUTE_TYPES,
	FEATURE_ROUTE_TYPES,
	UrlType,
	objectIdOfRoute,
	planetIdOfRoute,
	urlTypeFromId,
	urlTypeToIdPrefix
} from './view';

describe('the x URL type', () => {
	it('maps x to the x- id prefix and back', () => {
		expect(urlTypeToIdPrefix(UrlType.Extrasolar)).toBe('x');
		expect(urlTypeFromId('x-22137869')).toBe(UrlType.Extrasolar);
		expect(urlTypeFromId('extra-1')).toBe(UrlType.Extra);
	});

	it('opens the body route and not the feature route', () => {
		expect(BODY_ROUTE_TYPES.has('x')).toBe(true);
		expect(FEATURE_ROUTE_TYPES.has('x')).toBe(false);
	});

	it('checks the ID before any fetch', () => {
		expect(objectIdOfRoute('x', '22137869')).toBe('x-22137869');
		expect(objectIdOfRoute('x', '022137869')).toBeNull();
		expect(objectIdOfRoute('x', '-22137869')).toBeNull();
		expect(objectIdOfRoute('x', '9007199254740992')).toBeNull();
		expect(objectIdOfRoute('x', String(2 ** 24 + 12 * 4 ** 10))).toBeNull();
		expect(objectIdOfRoute('b', '399')).toBe('naif-399');
	});
});

describe('the planet route', () => {
	it('names the scene id of a planet', () => {
		expect(planetIdOfRoute('27424668', '1')).toBe('x-27424668-b-1');
		expect(planetIdOfRoute('27424668', '12')).toBe('x-27424668-b-12');
		expect(urlTypeFromId('x-27424668-b-1')).toBe(UrlType.Extrasolar);
	});

	it('names none for a segment that is not a plain number, or not an ID', () => {
		for (const [host, n] of [
			['27424668', '0'],
			['27424668', '01'],
			['27424668', '-1'],
			['27424668', '1.0'],
			['27424668', 'b'],
			['27424668', '123456'],
			['027424668', '1'],
			['abc', '1'],
			['0', '1'],
			['1-b-2', '3']
		]) {
			expect(planetIdOfRoute(host, n), `${host}/b/${n}`).toBeNull();
		}
	});
});
