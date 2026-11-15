import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import type { LoadedChart } from '$lib/fetch/extrasolar/figures';
import { normalize, type Vec3 } from '$lib/math/travel/vec3';
import type { FigureChart } from './figure';
import { fitFrame, project, type ChartFrame } from './frame';
import { chartPoints, type ChartNames } from './overlay';
import { ChartPainter, type PaintInput } from './painter';
import type { ChartSky, Pixels } from './sky';

const MEMBER: Vec3 = [1, 0, 0];
const NEIGHBOUR = normalize([1, 0.01, 0.01]);

const figure: FigureChart = {
	points: [MEMBER],
	lines: [],
	stars: [{ id: 1, direction: MEMBER }],
	standIns: [],
	neighbours: []
};

function loaded(more?: () => Promise<LoadedChart>, neighbours = figure.neighbours): LoadedChart {
	return {
		chart: { ...figure, neighbours },
		name: async ({ id }) => `Star ${id}`,
		credits: [],
		more
	};
}

/** A picture with a bright spot on each star. */
function sky(frame: ChartFrame, width: number, height: number): Pixels {
	const data = new Uint8ClampedArray(width * height * 4);
	const scale = width / frame.width;
	for (const direction of [MEMBER, NEIGHBOUR]) {
		const [x, y] = project(frame, direction).map((v) => Math.round(v * scale));
		for (let dy = -2; dy <= 2; dy++)
			for (let dx = -2; dx <= 2; dx++)
				data.fill(255, ((y + dy) * width + x + dx) * 4, ((y + dy) * width + x + dx) * 4 + 4);
	}
	return { data, width, height };
}

/** A sky whose paints wait for the test. */
function heldSky(): ChartSky & { paints: number; arrive: (() => void)[] } {
	const made = {
		paints: 0,
		arrive: [] as (() => void)[],
		paint: (frame: ChartFrame, width: number, height: number) => {
			made.paints++;
			return new Promise<Pixels>((resolve) =>
				made.arrive.push(() => resolve(sky(frame, width, height)))
			);
		},
		watch: () => () => {}
	};
	return made;
}

function input(width: number, chart: LoadedChart): PaintInput {
	const frame = fitFrame(chart.chart.points, { width, height: width });
	return {
		frame,
		points: chartPoints(frame, chart.chart),
		chart,
		canvas: {
			width: 0,
			height: 0,
			getContext: () => ({ putImageData: () => {} })
		} as unknown as HTMLCanvasElement,
		fill: false,
		search: true,
		most: 14,
		neighbours: true
	};
}

/** Lets the timers, the animation frame and the awaits of a paint run. */
async function settle(): Promise<void> {
	await vi.advanceTimersByTimeAsync(200);
}

describe('ChartPainter', () => {
	let frames: FrameRequestCallback[];
	beforeEach(() => {
		vi.useFakeTimers();
		frames = [];
		vi.stubGlobal('requestAnimationFrame', (cb: FrameRequestCallback) => {
			frames.push(cb);
			setTimeout(() => frames.shift()?.(0), 16);
			return frames.length;
		});
		vi.stubGlobal('cancelAnimationFrame', () => frames.splice(0));
		vi.stubGlobal('matchMedia', () => ({
			addEventListener: () => {},
			removeEventListener: () => {}
		}));
		vi.stubGlobal(
			'ImageData',
			class {
				constructor(
					readonly data: Uint8ClampedArray,
					readonly width: number,
					readonly height: number
				) {}
			}
		);
	});
	afterEach(() => {
		vi.useRealTimers();
		vi.unstubAllGlobals();
	});

	function painter(source: ChartSky) {
		const named: ChartNames[] = [];
		const failed: unknown[] = [];
		const made = new ChartPainter(source, {
			painted: () => {},
			named: (names) => named.push(names),
			failed: (e) => failed.push(e)
		});
		return { made, named, failed };
	}

	it('tells the names of the frame on show, and none of a frame that is gone', async () => {
		const source = heldSky();
		const { made, named } = painter(source);
		let release = (): void => {};
		const gate = new Promise<void>((resolve) => (release = resolve));
		const chart: LoadedChart = {
			...loaded(),
			name: async ({ id }) => gate.then(() => `Star ${id}`)
		};
		const first = input(300, chart);
		made.show(first);
		await settle();
		source.arrive.shift()!();
		await vi.advanceTimersByTimeAsync(0);
		// The box changes size while the names of the first frame are read.
		const second = input(320, chart);
		made.show(second);
		release();
		await vi.advanceTimersByTimeAsync(0);
		expect(named.filter(({ frame }) => frame === first.frame)).toEqual([]);
		await settle();
		source.arrive.shift()!();
		await settle();
		expect(named.at(-1)?.frame).toBe(second.frame);
		expect(named.at(-1)?.members).toHaveLength(1);
	});

	it('names new neighbours on the picture on show, with no new paint', async () => {
		const source = heldSky();
		const { made, named } = painter(source);
		const fuller = loaded(undefined, [{ id: 2, direction: NEIGHBOUR, given: 'Two' }]);
		const partial = loaded(async () => fuller);
		made.show(input(300, partial));
		await settle();
		source.arrive.shift()!();
		await settle();
		expect(named.at(-1)?.neighbours).toEqual([]);
		made.extend(fuller);
		await settle();
		expect(source.paints).toBe(1);
		expect(named.at(-1)?.neighbours.map(({ star }) => star.id)).toEqual([2]);
	});

	it('reports a paint that fails', async () => {
		const { made, failed } = painter({
			paint: async () => {
				throw new Error('lost');
			},
			watch: () => () => {}
		});
		made.show(input(300, loaded()));
		await settle();
		expect(failed).toHaveLength(1);
	});
});
