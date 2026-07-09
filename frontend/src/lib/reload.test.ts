import { describe, it, expect, vi, afterEach } from 'vitest';
import { startPageReload } from './reload';

describe('startPageReload', () => {
	afterEach(() => vi.unstubAllGlobals());

	it('runs onStart immediately and defers the reload to a later frame', () => {
		// Stub rAF to capture the callback without running it, so location.reload
		// never fires (jsdom has no navigation) — we only assert the ordering.
		const raf = vi.fn().mockReturnValue(0);
		vi.stubGlobal('requestAnimationFrame', raf);
		const onStart = vi.fn();

		startPageReload(onStart);

		expect(onStart).toHaveBeenCalledOnce(); // feedback paints first
		expect(raf).toHaveBeenCalledTimes(1); // reload is scheduled, not synchronous
	});
});
