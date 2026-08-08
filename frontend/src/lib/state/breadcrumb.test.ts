/**
 * Cross-navigation for surface features: a feature climbs to its type's
 * collection page (host body is a cross-ref tile instead), and a type page
 * climbs to the Surface Features category.
 */

import { describe, expect, it } from 'vitest';
import { parentCrumb } from './breadcrumb';
import { CAT_SURFACE_FEATURES } from '$lib/fetch/groups/registry';
import type { Focusable } from './focusable';

const MOON = { data: { id: 'naif-301', name: 'Moon' } } as never;

function featureFocusable(): Focusable {
	return { kind: 'feature', body: MOON, feature: { featureId: 1 } as never };
}

describe('parentCrumb: surface features', () => {
	it('climbs from a feature to its type page', () => {
		const crumb = parentCrumb(featureFocusable(), undefined, null, null, {
			slug: 'ft-mons',
			label: 'Mons'
		});
		expect(crumb).toEqual({
			label: 'Mons',
			target: { kind: 'group', slug: 'ft-mons', name: 'Mons' }
		});
	});

	it('falls back to the host body while the type slug is still resolving', () => {
		const crumb = parentCrumb(featureFocusable(), undefined, null, null, null);
		expect(crumb?.target).toEqual({ kind: 'focus', id: 'naif-301', name: 'Moon' });
	});

	it('climbs from a type page to the Surface Features category', () => {
		const crumb = parentCrumb({ kind: 'group', slug: 'ft-mons' }, undefined, null, null);
		expect(crumb?.target).toMatchObject({ kind: 'group', slug: CAT_SURFACE_FEATURES });
	});

	it('climbs from the Surface Features category to the Solar System root', () => {
		const crumb = parentCrumb({ kind: 'group', slug: CAT_SURFACE_FEATURES }, undefined, null, null);
		expect(crumb?.target).toMatchObject({ kind: 'group', slug: 'cat-solar-system' });
	});

	it('climbs from a property collection to Structure & Activity, not the root', () => {
		for (const slug of ['cat-atmospheres', 'cat-oceans']) {
			const crumb = parentCrumb({ kind: 'group', slug }, undefined, null, null);
			expect(crumb?.target).toMatchObject({ kind: 'group', slug: 'cat-structure-activity' });
		}
	});
});
