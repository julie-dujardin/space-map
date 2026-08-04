/**
 * The scene and the sources footer must agree on whether a shape model is on
 * screen: Ceres keeps its Dawn DEM sphere, so crediting DAMIT there credits a
 * mesh nothing ever loaded.
 */

import { describe, expect, it, vi } from 'vitest';

const lowEnd = vi.hoisted(() => ({ value: false }));
vi.mock('$lib/device', () => ({ isLowEndDevice: () => lowEnd.value }));

import { shapeModelSkipReason } from './shape-model-policy';
import type { GlobalObjectData } from '$lib/fetch/objects/object-data';

function body(g: Partial<GlobalObjectData>): GlobalObjectData {
	return { id: 'naif-2000001', type: 'asteroid', ...g } as GlobalObjectData;
}

const dem = { id: 'naif-2000001_displacement' } as GlobalObjectData['displacement'];

describe('shapeModelSkipReason', () => {
	it('draws the mesh when the body has no DEM', () => {
		expect(shapeModelSkipReason(body({ model_name: 'damit-5915' }))).toBeNull();
	});

	it('keeps the relief sphere when a DEM exists', () => {
		expect(shapeModelSkipReason(body({ model_name: 'damit-5915', displacement: dem }))).toBe(
			'dem-preferred'
		);
	});

	it('reports no bundle when the body has no model', () => {
		expect(shapeModelSkipReason(body({}))).toBe('no-bundle');
		expect(shapeModelSkipReason(null)).toBe('no-bundle');
	});

	it('skips rough meshes on low-end devices but keeps faithful ones', () => {
		lowEnd.value = true;
		try {
			expect(
				shapeModelSkipReason(body({ model_name: 'damit-5915', render_quality: 'medium' }))
			).toBe('low-end-device');
			expect(shapeModelSkipReason(body({ model_name: 'eros', render_quality: 'high' }))).toBeNull();
		} finally {
			lowEnd.value = false;
		}
	});
});
