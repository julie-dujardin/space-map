/**
 * Locks the feature bucket-key shape so it stays in sync with
 * `feature_bucket_key` in `data/src/space_map_data/export/nomenclature/writer.py`.
 */

import { describe, expect, it } from 'vitest';
import { featureBucketKey } from './details';

describe('featureBucketKey', () => {
	it('joins bodyId and featureId with a colon', () => {
		expect(featureBucketKey('naif-301', 1234)).toBe('naif-301:1234');
	});

	it('is stable for the same inputs', () => {
		expect(featureBucketKey('naif-499', 42)).toBe(featureBucketKey('naif-499', 42));
	});

	it('distinguishes different bodies', () => {
		expect(featureBucketKey('naif-301', 1)).not.toBe(featureBucketKey('naif-499', 1));
	});
});
