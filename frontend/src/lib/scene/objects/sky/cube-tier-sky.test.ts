import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import type { SkyboxMetadata } from '$lib/fetch/metadata';
import { fitFrame } from '$lib/star-chart/frame';

const loads = vi.hoisted(() => ({
	answers: [] as ((ok: boolean) => void)[],
	asked: [] as string[]
}));
const source = vi.hoisted(() => ({ paints: 0, changes: 0 }));

vi.mock('three', () => ({
	WebGLRenderer: class {
		capabilities = { maxTextureSize: 16384 };
		dispose(): void {}
		forceContextLoss(): void {}
	}
}));
vi.mock('$lib/star-chart/webgl', () => ({ webgl2Canvas: () => ({ canvas: {}, gl: {} }) }));
vi.mock('$lib/star-chart/cube-sky', () => ({
	texelsPerPixel: () => 1,
	CubeSkySource: class {
		constructor(
			_renderer: unknown,
			private readonly cube: () => unknown
		) {}
		async paint() {
			if (!this.cube()) return null;
			source.paints++;
			return { data: new Uint8ClampedArray(4), width: 1, height: 1 };
		}
		finest = () => null;
		onChange = () => () => {};
		changed(): void {
			source.changes++;
		}
		dispose(): void {}
	}
}));
vi.mock('./skybox', () => ({
	skyboxTiers: () => ['low'],
	loadSkyboxTier: (_renderer: unknown, _meta: unknown, tier: string) => {
		loads.asked.push(tier);
		return new Promise((resolve, reject) =>
			loads.answers.push((ok) => (ok ? resolve({ dispose() {} }) : reject(new Error('face'))))
		);
	}
}));

const { CubeTierSky } = await import('./cube-tier-sky');

const META = { tier_face_size: { low: 2048 } } as unknown as SkyboxMetadata;
const FRAME = fitFrame([[1, 0, 0]], { width: 100, height: 100 });

describe('CubeTierSky', () => {
	beforeEach(() => {
		vi.useFakeTimers();
		vi.spyOn(console, 'warn').mockImplementation(() => {});
		loads.answers.length = loads.asked.length = 0;
		source.paints = source.changes = 0;
	});
	afterEach(() => {
		vi.useRealTimers();
		vi.restoreAllMocks();
	});

	it('paints the first cube once, for the paint that waits for it', async () => {
		const sky = new CubeTierSky(META);
		const painted = sky.paint(FRAME, 100, 100);
		loads.answers.shift()!(true);
		expect(await painted).not.toBeNull();
		expect(source.paints).toBe(1);
		expect(source.changes).toBe(0);
	});

	it('paints nothing for a paint that is aborted', async () => {
		const sky = new CubeTierSky(META);
		const wanted = new AbortController();
		const painted = sky.paint(FRAME, 100, 100, wanted.signal);
		wanted.abort();
		loads.answers.shift()!(true);
		expect(await painted).toBeNull();
		expect(source.paints).toBe(0);
	});

	it('asks for a failed tier again after a wait, and tells the charts', async () => {
		const sky = new CubeTierSky(META);
		const painted = sky.paint(FRAME, 100, 100);
		loads.answers.shift()!(false);
		expect(await painted).toBeNull();
		// A paint during the wait asks for nothing.
		expect(await sky.paint(FRAME, 100, 100)).toBeNull();
		expect(loads.asked).toEqual(['low']);
		await vi.advanceTimersByTimeAsync(3000);
		expect(loads.asked).toEqual(['low', 'low']);
		loads.answers.shift()!(true);
		await vi.advanceTimersByTimeAsync(0);
		expect(source.changes).toBe(1);
		sky.dispose();
	});
});
