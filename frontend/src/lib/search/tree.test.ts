import { describe, expect, it } from 'vitest';
import { collectionTypeLabel } from '$lib/format/group';
import { COLLECTION_SECTIONS } from './tree';

describe('COLLECTION_SECTIONS', () => {
	const types = COLLECTION_SECTIONS.flatMap((section) => [...section.types]);

	it('lists a type once', () => {
		expect(new Set(types).size).toBe(types.length);
	});

	it('names every type', () => {
		for (const type of types) expect(collectionTypeLabel(type)).toBeTruthy();
	});

	it('splits satellite constellations in two', () => {
		expect(types).toEqual(expect.arrayContaining(['fleet', 'breakup_cloud']));
		expect(types).not.toContain('constellation');
	});
});
