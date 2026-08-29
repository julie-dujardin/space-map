import { describe, it, expect, vi } from 'vitest';
import { evidenceName, rockName, standingName } from './interior-layers';

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

describe('layer evidence and standing names', () => {
	// The pipeline's closed vocabularies, from constants/interior/schema.py. A
	// key with no message here is a blank clause on the card, which is worse
	// than the slug: the reader is told nothing and cannot tell they were.
	it('has a name for every evidence the export ships', () => {
		const warn = vi.spyOn(console, 'warn').mockImplementation(() => {});
		for (const evidence of [
			'sampled',
			'sounding',
			'seismic',
			'induction',
			'libration',
			'tidal',
			'gravity',
			'thermal_model',
			'bulk_density'
		]) {
			expect(evidenceName(evidence)).toBeTruthy();
		}
		expect(warn).not.toHaveBeenCalled();
		warn.mockRestore();
	});

	it('has a name for every standing the export ships', () => {
		const warn = vi.spyOn(console, 'warn').mockImplementation(() => {});
		for (const standing of ['probable', 'disputed', 'hypothetical']) {
			expect(standingName(standing)).toBeTruthy();
		}
		expect(warn).not.toHaveBeenCalled();
		warn.mockRestore();
	});

	// `established` is the pipeline's default and never ships, so a card that
	// asked for its name would be drawing a caveat on a layer that has none.
	it('has no name for the standing that is never shipped', () => {
		const warn = vi.spyOn(console, 'warn').mockImplementation(() => {});
		expect(standingName('established')).toBeNull();
		expect(evidenceName('vibes')).toBeNull();
		warn.mockRestore();
	});
});
