/**
 * Locks the one-name-per-type key scheme: the display strings for an IAU
 * descriptor are keyed by its `ft-` slug stem, matching `feature_type_key` in
 * `data/src/space_map_data/constants/nomenclature/feature_types.py`.
 */

import { describe, expect, it } from 'vitest';
import * as m from '$lib/paraglide/messages.js';
import { featureTypeLabel, featureTypeDescription } from './feature-type';

describe('featureTypeLabel', () => {
	it('resolves the slug stem to its generated message', () => {
		expect(featureTypeLabel('ft-crater')).toBe(m.feature_type_label_crater());
		expect(featureTypeLabel('ft-mons')).toBe(m.feature_type_label_mons());
	});

	it('accepts a bare stem as well as a prefixed slug', () => {
		expect(featureTypeLabel('crater')).toBe(featureTypeLabel('ft-crater'));
	});

	// Paraglide exports hyphenated keys under a string name, not an identifier —
	// the dynamic lookup is what makes multi-word types resolve at all.
	it('handles multi-word stems', () => {
		expect(featureTypeLabel('ft-albedo-feature')).toBe('Albedo feature');
	});

	it('is undefined before the slug resolves, and for unknown types', () => {
		expect(featureTypeLabel(undefined)).toBeUndefined();
		expect(featureTypeLabel('ft-not-a-type')).toBeUndefined();
	});
});

describe('featureTypeDescription', () => {
	it('resolves the IAU definition for a type that has one', () => {
		expect(featureTypeDescription('ft-crater')).toBe(m.feature_type_description_crater());
	});

	it('is undefined for unknown types', () => {
		expect(featureTypeDescription('ft-not-a-type')).toBeUndefined();
	});
});
