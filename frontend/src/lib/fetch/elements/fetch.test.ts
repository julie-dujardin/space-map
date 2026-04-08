import { describe, it, expect } from 'vitest';
import { parseLabels } from './fetch';

const US = '\x1f';

describe('parseLabels', () => {
	it('parses lines with flag separator', () => {
		const text = `1${US}Mars\n2${US}Jupiter`;
		const { labels, flags } = parseLabels(text);

		expect(labels.get(0)).toBe('Mars');
		expect(labels.get(1)).toBe('Jupiter');
		expect(flags.get(0)).toBe(1);
		expect(flags.get(1)).toBe(2);
	});

	it('treats lines without separator as flag=0', () => {
		const { labels, flags } = parseLabels('Unnamed Object');

		expect(labels.get(0)).toBe('Unnamed Object');
		expect(flags.get(0)).toBe(0);
	});

	it('handles mixed lines', () => {
		const text = `1${US}Ceres\nUnknown\n2${US}Vesta`;
		const { labels, flags } = parseLabels(text);

		expect(labels.get(0)).toBe('Ceres');
		expect(flags.get(0)).toBe(1);
		expect(labels.get(1)).toBe('Unknown');
		expect(flags.get(1)).toBe(0);
		expect(labels.get(2)).toBe('Vesta');
		expect(flags.get(2)).toBe(2);
	});

	it('handles trailing newline', () => {
		const text = `1${US}Mars\n`;
		const { labels, flags } = parseLabels(text);

		expect(labels.size).toBe(2); // "Mars" + empty string after trailing newline
		expect(labels.get(0)).toBe('Mars');
		expect(labels.get(1)).toBe('');
		expect(flags.get(1)).toBe(0);
	});

	it('handles empty input', () => {
		const { labels, flags } = parseLabels('');

		expect(labels.size).toBe(1); // split('') produces ['']
		expect(labels.get(0)).toBe('');
		expect(flags.get(0)).toBe(0);
	});
});
