import { describe, it, expect } from 'vitest';
import { parseLabels } from './fetch';

const US = '\x1f';

describe('parseLabels', () => {
	it('parses {id}<US>{name} lines into a Map', () => {
		const text = `naif-399${US}Earth\nnaif-301${US}Moon`;
		const labels = parseLabels(text);
		expect(labels.get('naif-399')).toBe('Earth');
		expect(labels.get('naif-301')).toBe('Moon');
	});

	it('keeps an empty name when the separator is the last char', () => {
		const text = `naif--31${US}\nnaif-399${US}Earth`;
		const labels = parseLabels(text);
		expect(labels.get('naif--31')).toBe('');
		expect(labels.get('naif-399')).toBe('Earth');
	});

	it('treats lines without a separator as id-only with empty name', () => {
		const labels = parseLabels('naif-552');
		expect(labels.get('naif-552')).toBe('');
	});

	it('returns an empty map for empty input', () => {
		expect(parseLabels('').size).toBe(0);
	});

	it('handles a trailing newline by emitting an empty entry, ignored by Map size', () => {
		const text = `naif-399${US}Earth\n`;
		const labels = parseLabels(text);
		// Trailing empty line has no id; parseLabels skips it.
		expect(labels.size).toBe(1);
		expect(labels.get('naif-399')).toBe('Earth');
	});
});
