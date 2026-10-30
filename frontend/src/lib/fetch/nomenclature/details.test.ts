/**
 * Locks the feature bucket-key shape so it stays in sync with
 * `feature_bucket_key` in `data/src/space_map_data/export/nomenclature/writer.py`.
 */

import { describe, expect, it } from 'vitest';
import { featureBucketKey, localizeFeatures } from './details';

describe('featureBucketKey', () => {
	it('joins bodyId and featureId with a colon', () => {
		expect(featureBucketKey('naif-301', 1234)).toBe('naif-301:1234');
	});

	it('distinguishes different bodies', () => {
		expect(featureBucketKey('naif-301', 1)).not.toBe(featureBucketKey('naif-499', 1));
	});
});

describe('localizeFeatures', () => {
	const ref = (id: number, name: string) => ({
		name,
		primary_type: 'naif',
		primary_id: '301',
		secondary_type: 'feature',
		secondary_id: String(id)
	});

	it('names a feature by its name in the language, else by its global one', () => {
		const refs = localizeFeatures([ref(1, 'Aitken'), ref(2, 'Abel')], {
			feature_names: { '1': 'エイトケン' }
		});
		expect(refs.map((r) => r.name)).toEqual(['エイトケン', 'Abel']);
		expect(refs[0].secondary_id).toBe('1');
	});
});
