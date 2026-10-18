import { describe, expect, it, vi } from 'vitest';

vi.mock('$lib/paraglide/runtime.js', async (original) => ({
	...(await original<object>()),
	getLocale: () => 'en-US'
}));

import * as m from '$lib/paraglide/messages.js';
import { describeLastContact, formatLastContact } from './contact';

describe('formatLastContact', () => {
	// A record that names a day or a year must not gain a time, or slip a day
	// in the reader's zone.
	it.each([
		{ last_contact: '2003-01-23', precision: 'day', expected: 'Jan 23, 2003' },
		{ last_contact: '1982-03', precision: 'month', expected: 'Mar 1982' },
		{ last_contact: '2014', precision: 'year', expected: '2014' }
	] as const)('$precision: $last_contact → $expected', ({ expected, ...entry }) => {
		expect(formatLastContact(entry)).toBe(expected);
	});

	it('counts a recent pass in days', () => {
		const entry = {
			last_contact: '2026-09-15T12:00:00+00:00',
			precision: 'second',
			network: 'dsn',
			seen: {}
		} as const;
		expect(formatLastContact(entry, Date.parse('2026-09-17T12:00:00Z'))).toBe('2 days ago');
	});
});

describe('describeLastContact', () => {
	it('names the record when no network had the craft', () => {
		expect(describeLastContact({ last_contact: '2003-01-23', precision: 'day' })).toBe(
			m.tooltip_last_contact_record({ date: 'January 23, 2003' })
		);
	});
});
