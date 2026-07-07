/**
 * Tests for `geometryFromMember`'s texture-flag plumbing.
 *
 * The lineup skips its speculative `low.webp` fetch only on an explicit
 * `texture: false`; dropping the field here (e.g. in a refactor that rebuilds
 * the geometry object) would silently revert every untextured member to a
 * guaranteed-404 probe.
 */

import { describe, expect, it } from 'vitest';
import { geometryFromMember } from './lineup';

describe('geometryFromMember', () => {
	it('carries the texture flag through, including explicit false', () => {
		const base = { name: 'Pallas', id: 'spkid-20000002', diameter_km: 513 };
		expect(geometryFromMember({ ...base, texture: false })?.texture).toBe(false);
		expect(geometryFromMember({ ...base, texture: true })?.texture).toBe(true);
		// Pre-flag bundles omit the field — must stay undefined (probe as before).
		expect(geometryFromMember(base)?.texture).toBeUndefined();
	});
});
