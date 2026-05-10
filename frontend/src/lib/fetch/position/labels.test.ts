import { describe, it, expect } from 'vitest';
import { parseLabels } from './labels';

const US = '\x1f';

describe('parseLabels', () => {
	it('parses {id}<US>{name}<US>{flags} lines into a Map', () => {
		const text = `naif-399${US}Earth${US}\nnaif-301${US}Moon${US}`;
		const labels = parseLabels(text);
		expect(labels.get('naif-399')).toEqual({ name: 'Earth', isMinor: false });
		expect(labels.get('naif-301')).toEqual({ name: 'Moon', isMinor: false });
	});

	it('keeps empty-name entries so the id stays in the promoted set', () => {
		// The exporter emits `{id}\x1f\x1f` for curated extras with no Wikidata/DB
		// name; the renderer keys auto-promote on the map's keys.
		const text = `naif--31${US}${US}\nnaif-399${US}Earth${US}`;
		const labels = parseLabels(text);
		expect(labels.get('naif--31')).toEqual({ name: '', isMinor: false });
		expect(labels.get('naif-399')).toEqual({ name: 'Earth', isMinor: false });
	});

	it('flags designation-only moons as minor', () => {
		const text = `naif-65289${US}S2020 S48${US}m\nnaif-301${US}Moon${US}`;
		const labels = parseLabels(text);
		expect(labels.get('naif-65289')).toEqual({ name: 'S2020 S48', isMinor: true });
		expect(labels.get('naif-301')).toEqual({ name: 'Moon', isMinor: false });
	});

	it('drops lines without a separator', () => {
		expect(parseLabels('naif-552').has('naif-552')).toBe(false);
	});

	it('tolerates single-separator lines (no flags column) so an export-deploy mismatch still renders names', () => {
		const text = `naif-301${US}Moon`;
		expect(parseLabels(text).get('naif-301')).toEqual({ name: 'Moon', isMinor: false });
	});

	it('returns an empty map for empty input', () => {
		expect(parseLabels('').size).toBe(0);
	});

	it('handles a trailing newline by emitting an empty entry, ignored by Map size', () => {
		const text = `naif-399${US}Earth${US}\n`;
		const labels = parseLabels(text);
		// Trailing empty line has no id; parseLabels skips it.
		expect(labels.size).toBe(1);
		expect(labels.get('naif-399')).toEqual({ name: 'Earth', isMinor: false });
	});
});
