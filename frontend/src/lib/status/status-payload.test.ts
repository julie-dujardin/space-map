import { describe, it, expect, vi } from 'vitest';

vi.mock('$lib/paraglide/messages.js', () => ({
	status_section_orbits: () => 'Orbits and catalogues',
	status_section_ephemerides: () => 'Ephemerides',
	status_section_reference: () => 'Reference data',
	status_section_imagery: () => 'Imagery',
	status_section_models: () => '3D models',
	status_section_science: () => 'Science data'
}));

import { freshness, sections, tally, type Status, type StatusSource } from './status-payload';

const NOW = Date.parse('2026-09-19T13:15:00Z');

function source(overrides: Partial<StatusSource> = {}): StatusSource {
	return {
		id: 'demo',
		label: 'Demo',
		homepage: 'https://example.org/',
		category: 'orbits',
		...overrides
	};
}

describe('freshness', () => {
	it('is never without a download record', () => {
		expect(freshness(source(), NOW)).toBe('never');
	});

	it('is current when the provider sets no refresh window', () => {
		expect(freshness(source({ downloaded_at: '2020-01-01T00:00:00Z' }), NOW)).toBe('current');
	});

	// The provider's own staleness check expires on the exact interval, so a
	// download 7.8 days into a 7-day window is due, not current.
	it.each([
		{ name: 'inside the window', downloaded_at: '2026-09-14T13:15:00Z', expected: 'current' },
		{ name: 'past the window', downloaded_at: '2026-09-11T13:15:00Z', expected: 'due' }
	])('$name → $expected', ({ downloaded_at, expected }) => {
		expect(freshness(source({ downloaded_at, max_age_days: 7 }), NOW)).toBe(expected);
	});

	// SBDB moves `downloaded_at` only when the mirror changed; the sync that
	// verified it is what the window is measured against.
	it('measures against checked_at where a provider reports one', () => {
		const sbdb = source({
			downloaded_at: '2026-08-01T13:15:00Z',
			checked_at: '2026-09-17T13:15:00Z',
			max_age_days: 7
		});
		expect(freshness(sbdb, NOW)).toBe('current');
	});
});

describe('sections', () => {
	const status: Status = {
		generated_at: '2026-09-19T13:15:00Z',
		categories: ['orbits', 'ephemerides', 'imagery'],
		sources: [
			source({ id: 'a', category: 'ephemerides' }),
			source({ id: 'b', category: 'orbits' }),
			source({ id: 'c', category: 'orbits' })
		]
	};

	it('follows the payload order and drops empty categories', () => {
		expect(sections(status).map((s) => s.id)).toEqual(['orbits', 'ephemerides']);
		expect(sections(status)[0].sources.map((s) => s.id)).toEqual(['b', 'c']);
	});

	it('keeps rows whose category the payload never listed', () => {
		const extra = {
			...status,
			sources: [...status.sources, source({ id: 'd', category: 'weather' })]
		};
		const found = sections(extra).find((s) => s.id === 'weather');
		expect(found?.sources.map((s) => s.id)).toEqual(['d']);
	});
});

describe('tally', () => {
	it('counts every source exactly once', () => {
		const status: Status = {
			generated_at: '2026-09-19T13:15:00Z',
			categories: ['orbits'],
			sources: [
				source({ id: 'a', downloaded_at: '2026-09-18T13:15:00Z' }),
				source({ id: 'b', downloaded_at: '2026-08-18T13:15:00Z', max_age_days: 7 }),
				source({ id: 'c' })
			]
		};
		expect(tally(status, NOW)).toEqual({ total: 3, current: 1, due: 1, never: 1 });
	});
});
