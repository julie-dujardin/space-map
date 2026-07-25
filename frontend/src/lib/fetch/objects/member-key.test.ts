/**
 * Keeps `memberEntryKey` in sync with `feature_member_key` in
 * `data/src/space_map_data/export/notable.py`. Feature members carry their
 * host body's id, so keying on `id` alone crashes a `{#each}` on any body with
 * two named features (`each_key_duplicate`).
 */

import { describe, expect, it } from 'vitest';
import { memberEntryKey, type NotableMemberEntry } from './object-data';

function entry(e: Partial<NotableMemberEntry>): NotableMemberEntry {
	return { name: 'x', ...e } as NotableMemberEntry;
}

describe('memberEntryKey', () => {
	it('pairs body id with feature id for surface features', () => {
		expect(memberEntryKey(entry({ id: 'naif-301', feature_id: 1234 }))).toBe('naif-301:1234');
	});

	it('distinguishes two features on the same body', () => {
		const a = memberEntryKey(entry({ id: 'naif-499', feature_id: 1 }));
		const b = memberEntryKey(entry({ id: 'naif-499', feature_id: 2 }));
		expect(a).not.toBe(b);
	});

	it('falls back to the object id for ordinary members', () => {
		expect(memberEntryKey(entry({ id: 'naif-301' }))).toBe('naif-301');
	});

	it('prefers the group slug for group members', () => {
		expect(memberEntryKey(entry({ group: 'const-starlink', id: undefined }))).toBe(
			'const-starlink'
		);
	});

	it('never keys a feature by its host id alone', () => {
		expect(memberEntryKey(entry({ id: 'naif-301', feature_id: 7 }))).not.toBe('naif-301');
	});
});
