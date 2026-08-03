import { describe, it, expect, vi, beforeEach } from 'vitest';

// vi.mock factories are hoisted above top-level statements, so the spies must
// be created via vi.hoisted to be in scope when the mock factory runs.
const { pushStateSpy, replaceStateSpy } = vi.hoisted(() => ({
	pushStateSpy: vi.fn(),
	replaceStateSpy: vi.fn()
}));

vi.mock('$app/navigation', () => ({
	pushState: pushStateSpy,
	replaceState: replaceStateSpy
}));

vi.mock('$app/paths', () => ({
	resolve: (route: string, params: Record<string, string | undefined>) =>
		route
			.replace('[type]', params.type ?? '')
			.replace('[id]', params.id ?? '')
			.replace('/[[name]]', params.name ? `/${params.name}` : '')
}));

// AppState's `createAppState()` calls parseUrl(), which reads $app/state.page.
// We construct AppState directly, so this only needs to satisfy the import.
vi.mock('$app/state', () => ({ page: { params: {}, url: new URL('http://x/') } }));

import { AppState } from './app-state.svelte';
import type { MapViewState } from './view';

const initialView: MapViewState = {
	type: 'b',
	id: 'naif-10',
	name: 'Sun',
	date: new Date('2026-01-15T12:00:00Z'),
	isNow: false,
	latitude: 45,
	longitude: 0,
	zoom: 42.43,
	imageIndex: null,
	featureId: null,
	groupSlug: null,
	tab: null,
	memberPage: null,
	quad: null,
	featureType: null,
	ring: null
};

beforeEach(() => {
	pushStateSpy.mockClear();
	replaceStateSpy.mockClear();
	vi.useFakeTimers();
});

describe('AppState.setCamera', () => {
	it('updates view fields synchronously', () => {
		const s = new AppState({ ...initialView });
		s.setCamera({ latitude: 30, longitude: -60, zoom: 5 });
		expect(s.view.latitude).toBe(30);
		expect(s.view.longitude).toBe(-60);
		expect(s.view.zoom).toBe(5);
	});

	it('writes URL via replaceState immediately (camera settles are discrete)', () => {
		const s = new AppState({ ...initialView });
		s.setCamera({ latitude: 30, longitude: -60, zoom: 5 });
		expect(replaceStateSpy).toHaveBeenCalledOnce();
	});

	it('writes the latest value on each call (no coalescing)', () => {
		const s = new AppState({ ...initialView });
		s.setCamera({ latitude: 1, longitude: 1, zoom: 1 });
		s.setCamera({ latitude: 2, longitude: 2, zoom: 2 });
		s.setCamera({ latitude: 3, longitude: 3, zoom: 3 });
		expect(replaceStateSpy).toHaveBeenCalledTimes(3);
		const [, state] = replaceStateSpy.mock.calls[2];
		expect(state.view.latitude).toBe(3);
	});

	it('does not touch imageIndex', () => {
		const s = new AppState({ ...initialView, imageIndex: 2 });
		s.setCamera({ latitude: 30, longitude: -60, zoom: 5 });
		expect(s.view.imageIndex).toBe(2);
	});
});

describe('AppState.setDate', () => {
	it('updates date and isNow only', () => {
		const s = new AppState({ ...initialView, isNow: false });
		const next = new Date('2030-06-01T00:00:00Z');
		s.setDate(next, true);
		expect(s.view.date).toBe(next);
		expect(s.view.isNow).toBe(true);
		expect(s.view.id).toBe(initialView.id);
		expect(s.view.latitude).toBe(initialView.latitude);
	});

	it('throttles the URL write to one trailing call per window', () => {
		const s = new AppState({ ...initialView });
		s.setDate(new Date('2030-06-01T00:00:00Z'), true);
		expect(replaceStateSpy).not.toHaveBeenCalled();
		// Subsequent ticks within the window don't reschedule or pile up.
		s.setDate(new Date('2030-06-01T00:00:30Z'), true);
		vi.advanceTimersByTime(60_000);
		expect(replaceStateSpy).toHaveBeenCalledOnce();
		const [, state] = replaceStateSpy.mock.calls[0];
		expect(state.view.date).toEqual(new Date('2030-06-01T00:00:30Z'));
	});
});

describe('AppState.setFocus', () => {
	it('updates focus fields and clears imageIndex', () => {
		const s = new AppState({ ...initialView, imageIndex: 3 });
		s.setFocus({ type: 'b', id: 'naif-399', name: 'Earth' });
		expect(s.view.id).toBe('naif-399');
		expect(s.view.name).toBe('Earth');
		expect(s.view.imageIndex).toBeNull();
	});

	it('preserves camera and date', () => {
		const s = new AppState({ ...initialView, latitude: 12, longitude: 34, zoom: 5 });
		s.setFocus({ type: 'b', id: 'naif-399', name: 'Earth' });
		expect(s.view.latitude).toBe(12);
		expect(s.view.longitude).toBe(34);
		expect(s.view.zoom).toBe(5);
	});

	it('pushes a new history entry immediately (no debounce)', () => {
		const s = new AppState({ ...initialView });
		s.setFocus({ type: 'b', id: 'naif-399', name: 'Earth' });
		expect(pushStateSpy).toHaveBeenCalledOnce();
		expect(replaceStateSpy).not.toHaveBeenCalled();
	});

	// Regression: a throttled setDate firing AFTER setFocus would replaceState the
	// new pushState entry's URL back to the old view. setFocus must cancel the
	// pending throttle.
	it('cancels a pending date-throttle write', () => {
		const s = new AppState({ ...initialView });
		s.setDate(new Date('2030-06-01T00:00:00Z'), true);
		s.setFocus({ type: 'b', id: 'naif-399', name: 'Earth' });
		vi.advanceTimersByTime(60_000);
		expect(replaceStateSpy).not.toHaveBeenCalled();
		expect(pushStateSpy).toHaveBeenCalledOnce();
	});
});

describe('AppState.setImage', () => {
	it('null → 0 pushes (open is a history boundary)', () => {
		const s = new AppState({ ...initialView, imageIndex: null });
		s.setImage(0);
		expect(pushStateSpy).toHaveBeenCalledOnce();
		expect(replaceStateSpy).not.toHaveBeenCalled();
		expect(s.view.imageIndex).toBe(0);
	});

	it('0 → 1 replaces (in-viewer nav, no history pollution)', () => {
		const s = new AppState({ ...initialView, imageIndex: 0 });
		s.setImage(1);
		expect(replaceStateSpy).toHaveBeenCalledOnce();
		expect(pushStateSpy).not.toHaveBeenCalled();
		expect(s.view.imageIndex).toBe(1);
	});

	it('0 → null pushes (close is a history boundary)', () => {
		const s = new AppState({ ...initialView, imageIndex: 0 });
		s.setImage(null);
		expect(pushStateSpy).toHaveBeenCalledOnce();
		expect(replaceStateSpy).not.toHaveBeenCalled();
		expect(s.view.imageIndex).toBeNull();
	});
});

describe('AppState.setTab', () => {
	it('stores a non-overview tab and writes via replaceState', () => {
		const s = new AppState({ ...initialView });
		s.setTab('members');
		expect(s.view.tab).toBe('members');
		expect(replaceStateSpy).toHaveBeenCalledOnce();
		expect(pushStateSpy).not.toHaveBeenCalled();
	});

	it("maps 'overview' to a null tab (the default needs no URL block)", () => {
		const s = new AppState({ ...initialView, tab: 'members' });
		s.setTab('overview');
		expect(s.view.tab).toBeNull();
	});

	it('resets member-page depth — a manual switch lands at the top of the list', () => {
		const s = new AppState({ ...initialView, tab: 'members', memberPage: 4 });
		s.setTab('images');
		expect(s.view.memberPage).toBeNull();
	});

	it('is a no-op when already on the tab with no depth to clear', () => {
		const s = new AppState({ ...initialView, tab: 'members', memberPage: null });
		s.setTab('members');
		expect(replaceStateSpy).not.toHaveBeenCalled();
	});

	it('preserves camera and focus', () => {
		const s = new AppState({ ...initialView, id: 'naif-399', latitude: 12 });
		s.setTab('members');
		expect(s.view.id).toBe('naif-399');
		expect(s.view.latitude).toBe(12);
	});
});

describe('AppState.setMemberPage', () => {
	it('records depth > 1 via replaceState (no history pollution)', () => {
		const s = new AppState({ ...initialView, tab: 'members' });
		s.setMemberPage(3);
		expect(s.view.memberPage).toBe(3);
		expect(replaceStateSpy).toHaveBeenCalledOnce();
		expect(pushStateSpy).not.toHaveBeenCalled();
	});

	it('normalizes page 1 back to null (the implicit default)', () => {
		const s = new AppState({ ...initialView, tab: 'members', memberPage: 2 });
		s.setMemberPage(1);
		expect(s.view.memberPage).toBeNull();
	});

	it('is a no-op when the depth is unchanged', () => {
		const s = new AppState({ ...initialView, tab: 'members', memberPage: 3 });
		s.setMemberPage(3);
		expect(replaceStateSpy).not.toHaveBeenCalled();
	});
});

describe('AppState.syncFromPopState', () => {
	it('replaces the view without writing to URL', () => {
		const s = new AppState({ ...initialView });
		const incoming: MapViewState = {
			...initialView,
			id: 'naif-399',
			name: 'Earth',
			imageIndex: 2
		};
		s.syncFromPopState(incoming);
		expect(s.view.id).toBe('naif-399');
		expect(s.view.imageIndex).toBe(2);
		expect(pushStateSpy).not.toHaveBeenCalled();
		expect(replaceStateSpy).not.toHaveBeenCalled();
	});
});

// History.state must be structured-cloneable. In the real browser, Svelte 5's
// $state proxy is NOT cloneable (DataCloneError), which is why we snapshot
// before pushing. Vitest's environment doesn't fully reproduce that proxy
// behavior — `s.view` here ends up plain even without snapshot — so these
// assertions document the contract rather than reproducing the exact failure.
// The browser-side repro lives in manual QA.
describe('history.state payload is structured-cloneable', () => {
	it('pushState receives plain data (setFocus)', () => {
		const s = new AppState({ ...initialView });
		s.setFocus({ type: 'b', id: 'naif-399', name: 'Earth' });
		const [, state] = pushStateSpy.mock.calls[0];
		expect(() => structuredClone(state)).not.toThrow();
	});

	it('replaceState receives plain data (setCamera)', () => {
		const s = new AppState({ ...initialView });
		s.setCamera({ latitude: 30, longitude: -60, zoom: 5 });
		const [, state] = replaceStateSpy.mock.calls[0];
		expect(() => structuredClone(state)).not.toThrow();
	});

	// Snapshots must be detached from the live reactive view; otherwise a later
	// setter mutation could retroactively rewrite past history entries.
	it('snapshot is detached from the live reactive view', () => {
		const s = new AppState({ ...initialView });
		s.setFocus({ type: 'b', id: 'naif-399', name: 'Earth' });
		const [, snapshot] = pushStateSpy.mock.calls[0];
		const idAtPushTime = snapshot.view.id;
		s.setFocus({ type: 'b', id: 'naif-499', name: 'Mars' });
		expect(snapshot.view.id).toBe(idAtPushTime);
	});
});
