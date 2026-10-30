/**
 * A feature's bundles read as an object's, so the drawer's links section
 * lists its aliases as "also known as", as it does for a body or a star.
 */

import { describe, expect, it } from 'vitest';
import { featureDetailToObjectData } from './detail-adapters';

describe('featureDetailToObjectData', () => {
	it("keeps the feature's aliases in the language: the label the IAU name replaces", () => {
		const data = featureDetailToObjectData(
			{ global: { wikidata_qid: 'Q1' }, localized: { aliases: ['Tychon'] } },
			{ featureId: 6163, name: 'Tycho' }
		);
		expect(data.global?.name).toBe('Tycho');
		expect(data.localized?.aliases).toEqual(['Tychon']);
	});
});
