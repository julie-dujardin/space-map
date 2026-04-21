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
	type: 'body',
	id: 'naif-10',
	name: 'Sun',
	date: new Date('2026-01-15T12:00:00Z'),
	isNow: false,
	latitude: 45,
	longitude: 0,
	zoom: 42.43,
	imageIndex: null
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

	it('writes URL via replaceState after the debounce window', () => {
		const s = new AppState({ ...initialView });
		s.setCamera({ latitude: 30, longitude: -60, zoom: 5 });
		expect(replaceStateSpy).not.toHaveBeenCalled();
		vi.advanceTimersByTime(250);
		expect(replaceStateSpy).toHaveBeenCalledOnce();
	});

	it('coalesces rapid changes into a single replaceState', () => {
		const s = new AppState({ ...initialView });
		s.setCamera({ latitude: 1, longitude: 1, zoom: 1 });
		s.setCamera({ latitude: 2, longitude: 2, zoom: 2 });
		s.setCamera({ latitude: 3, longitude: 3, zoom: 3 });
		vi.advanceTimersByTime(250);
		expect(replaceStateSpy).toHaveBeenCalledOnce();
		const [, state] = replaceStateSpy.mock.calls[0];
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

	it('writes URL via replaceState after the debounce window', () => {
		const s = new AppState({ ...initialView });
		s.setDate(new Date('2030-06-01T00:00:00Z'), true);
		vi.advanceTimersByTime(250);
		expect(replaceStateSpy).toHaveBeenCalledOnce();
	});
});

describe('AppState.setFocus', () => {
	it('updates focus fields and clears imageIndex', () => {
		const s = new AppState({ ...initialView, imageIndex: 3 });
		s.setFocus({ type: 'body', id: 'naif-399', name: 'Earth' });
		expect(s.view.id).toBe('naif-399');
		expect(s.view.name).toBe('Earth');
		expect(s.view.imageIndex).toBeNull();
	});

	it('preserves camera and date', () => {
		const s = new AppState({ ...initialView, latitude: 12, longitude: 34, zoom: 5 });
		s.setFocus({ type: 'body', id: 'naif-399', name: 'Earth' });
		expect(s.view.latitude).toBe(12);
		expect(s.view.longitude).toBe(34);
		expect(s.view.zoom).toBe(5);
	});

	it('pushes a new history entry immediately (no debounce)', () => {
		const s = new AppState({ ...initialView });
		s.setFocus({ type: 'body', id: 'naif-399', name: 'Earth' });
		expect(pushStateSpy).toHaveBeenCalledOnce();
		expect(replaceStateSpy).not.toHaveBeenCalled();
	});

	// Regression: a debounced setCamera firing AFTER setFocus would wipe the new
	// pushState entry off the URL. setFocus must cancel any pending debounce.
	it('cancels a pending replaceState debounce', () => {
		const s = new AppState({ ...initialView });
		s.setCamera({ latitude: 30, longitude: -60, zoom: 5 });
		s.setFocus({ type: 'body', id: 'naif-399', name: 'Earth' });
		vi.advanceTimersByTime(250);
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
		s.setFocus({ type: 'body', id: 'naif-399', name: 'Earth' });
		const [, state] = pushStateSpy.mock.calls[0];
		expect(() => structuredClone(state)).not.toThrow();
	});

	it('replaceState receives plain data (setCamera)', () => {
		const s = new AppState({ ...initialView });
		s.setCamera({ latitude: 30, longitude: -60, zoom: 5 });
		vi.advanceTimersByTime(250);
		const [, state] = replaceStateSpy.mock.calls[0];
		expect(() => structuredClone(state)).not.toThrow();
	});

	// Snapshots must be detached from the live reactive view; otherwise a later
	// setter mutation could retroactively rewrite past history entries.
	it('snapshot is detached from the live reactive view', () => {
		const s = new AppState({ ...initialView });
		s.setFocus({ type: 'body', id: 'naif-399', name: 'Earth' });
		const [, snapshot] = pushStateSpy.mock.calls[0];
		const idAtPushTime = snapshot.view.id;
		s.setFocus({ type: 'body', id: 'naif-499', name: 'Mars' });
		expect(snapshot.view.id).toBe(idAtPushTime);
	});
});
