import { afterEach, describe, expect, it, vi } from 'vitest';
import { configureHost } from '$lib/host';
import type { ChartSky } from '$lib/star-chart/sky';

const made = vi.hoisted(() => ({ cubes: [] as { disposed: boolean }[], released: 0 }));

vi.mock('$lib/fetch/metadata', () => ({
	fetchMetadata: async () => ({ skybox: { tier_face_size: {} } })
}));
vi.mock('./cube-tier-sky', () => ({
	CubeTierSky: class {
		disposed = false;
		constructor() {
			made.cubes.push(this);
		}
		paint = async () => null;
		onChange = () => () => {};
		dispose(): void {
			this.disposed = true;
		}
	}
}));
vi.mock('$lib/star-chart/tile-sky', () => ({
	TileSkySource: class {},
	releaseTilePainter: () => made.released++
}));

const { holdChartSky } = await import('./chart-sky');

const FRAME = { width: 1, height: 1 } as never;
const map = { chartSky: { paint: async () => null, watch: () => () => {} } as ChartSky };

/** Paints once, so the page sky makes its cube. */
async function opened(sky: ChartSky): Promise<void> {
	await sky.paint(FRAME, 1, 1);
}

describe('holdChartSky', () => {
	afterEach(() => {
		made.cubes.length = 0;
		made.released = 0;
		configureHost({});
	});

	it("frees the page's sky when its last chart lets go, while a map's chart holds on", async () => {
		const onMap = holdChartSky(map);
		const alone = holdChartSky();
		await opened(alone.sky);
		expect(made.cubes).toHaveLength(1);
		alone.release();
		expect(made.cubes[0].disposed).toBe(true);
		expect(made.released).toBe(0);
		onMap.release();
		expect(made.released).toBe(1);
	});

	it('keeps the sky of a chart for another tile host while that chart paints', async () => {
		configureHost({ tilesUrl: 'https://a' });
		const first = holdChartSky();
		await opened(first.sky);
		configureHost({ tilesUrl: 'https://b' });
		const second = holdChartSky();
		expect(second.sky).not.toBe(first.sky);
		expect(made.cubes[0].disposed).toBe(false);
		second.release();
		expect(made.cubes[0].disposed).toBe(false);
		first.release();
		expect(made.cubes[0].disposed).toBe(true);
	});
});
