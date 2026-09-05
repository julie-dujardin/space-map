import { describe, it, expect } from 'vitest';
import { MapCover } from './map-cover.svelte';

describe('MapCover', () => {
	it('covers while any claim is held', () => {
		const cover = new MapCover();
		expect(cover.covered).toBe(false);
		const a = cover.claim();
		const b = cover.claim();
		a();
		expect(cover.covered).toBe(true);
		b();
		expect(cover.covered).toBe(false);
	});

	it('releases a claim once', () => {
		const cover = new MapCover();
		const release = cover.claim();
		release();
		release();
		expect(cover.covered).toBe(false);
	});
});
