import { describe, it, expect, vi } from 'vitest';
import { rockName } from './interior-layers';

describe('layer rock names', () => {
	it('has a name for every rock the export ships', () => {
		const warn = vi.spyOn(console, 'warn').mockImplementation(() => {});
		for (const rock of ['basalt', 'andesite', 'anorthosite', 'peridotite']) {
			expect(rockName(rock)).toBeTruthy();
		}
		expect(warn).not.toHaveBeenCalled();
		warn.mockRestore();
	});

	// The vocabulary grows with the curation, so a bundle can carry a rock this
	// build has no message for. Null lets the card fall back to "solid rock"
	// rather than printing the key at a reader.
	it('returns null for a rock it has no name for', () => {
		const warn = vi.spyOn(console, 'warn').mockImplementation(() => {});
		expect(rockName('komatiite')).toBeNull();
		expect(warn).toHaveBeenCalled();
		warn.mockRestore();
	});
});
