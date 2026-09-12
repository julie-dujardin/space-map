import { describe, it, expect, vi } from 'vitest';

vi.mock('$app/paths', () => ({
	resolve: (route: string, params: Record<string, string | undefined>) =>
		route
			.replace('[type]', params.type ?? '')
			.replace('[id]', params.id ?? '')
			.replace('[featureId]', params.featureId ?? '')
			.replace('/[[name]]', params.name ? `/${params.name}` : '')
}));

vi.mock('$app/state', () => ({
	page: { params: {}, route: { id: null }, url: new URL('http://x/') }
}));

import { targetHref } from './focus-link';
import { DEFAULT_TRIP } from '$lib/travel/trip';
import type { AppState } from './app-state.svelte';
import type { MapViewState } from './view';

const view: MapViewState = {
	type: 'b',
	id: 'naif-10',
	name: 'Sun',
	date: new Date('2026-01-15T12:00:00Z'),
	isNow: false,
	latitude: 45,
	longitude: 0,
	zoom: 42.43,
	imageIndex: null,
	gallery: null,
	featureId: null,
	groupSlug: null,
	tab: null,
	memberPage: null,
	quad: null,
	featureType: null,
	ring: null,
	navFrom: null,
	navTo: null,
	navFromFeature: null,
	navToFeature: null,
	navFromPlace: null,
	navToPlace: null,
	trip: DEFAULT_TRIP
};

const appState = { view } as AppState;

describe('targetHref', () => {
	/**
	 * The route segment has to come from the id, not from a guess about it: the
	 * loader rebuilds the id by gluing the segment's prefix back onto the number,
	 * so a satellite routed as `/b/` comes back as a NAIF body of the same
	 * number — a different object, and silently so.
	 */
	it('routes every id prefix to its own segment', () => {
		const cases: Array<[string, string]> = [
			['naif-599', '/b/599'],
			['spkid-20000001', '/s/20000001'],
			['norad_satcat-25544', '/e/25544'],
			['probe-41967618', '/p/41967618'],
			['extra-7', '/u/7']
		];
		for (const [id, prefix] of cases) {
			expect(targetHref(appState, { id }, '')).toContain(`${prefix}?`);
		}
	});

	it('sends a group to its collection page and a feature to its host body', () => {
		expect(targetHref(appState, { group: 'class-apollo' }, '')).toContain('/g/class-apollo?');
		expect(targetHref(appState, { id: 'naif-301', feature_id: 42 }, 'Abbe')).toContain(
			'/b/301/f/42/Abbe?'
		);
	});

	it('has nowhere to go without an id', () => {
		expect(targetHref(appState, {}, 'x')).toBeUndefined();
	});
});
