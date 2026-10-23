import { describe, expect, it } from 'vitest';
import {
	BODY_ROUTE_TYPES,
	FEATURE_ROUTE_TYPES,
	UrlType,
	objectIdOfRoute,
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
