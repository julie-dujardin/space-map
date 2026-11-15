/**
 * The paint of a chart, for the drawer's chart and for the SDK's. A run paints
 * the sky of one frame into a canvas, then finds the names that the picture
 * ranks. There is one run per animation frame at most, and a new size waits
 * for the next one. A run stops when a newer run starts or the frame changes.
 * The shell gives the inputs and draws the lines and names itself.
 */

import type { LoadedChart } from '$lib/fetch/extrasolar/figures';
import type { ChartFrame } from './frame';
import { findNames, noNames, SETTLE_MS, type ChartNames, type ChartPoints } from './overlay';
import { halved, PAINT_RATIO, paintRatio, type ChartSky, type Pixels } from './sky';

/** What the chart shows. */
export interface PaintInput {
	frame: ChartFrame;
	points: ChartPoints;
	chart: LoadedChart;
	canvas: HTMLCanvasElement;
	/** The chart fills its box. It paints at the screen's own ratio. */
	fill: boolean;
	/** Find the names of the stars. */
	search: boolean;
	/** The most names of members. */
	most: number;
	neighbours: boolean;
}

export interface PainterEvents {
	/** A picture is on the canvas. `sky` is false for a paint with no sky. */
	painted: (frame: ChartFrame, sky: boolean, chart: LoadedChart) => void;
	/** The names of the frame on show, members first, then with the neighbours. */
	named: (names: ChartNames) => void;
	failed: (error: unknown) => void;
}

/** What one run draws. A run reads nothing else after it starts. */
interface Run {
	input: PaintInput;
	/** Aborted when the chart wants another picture, or none. */
	signal: AbortSignal;
	/** Painted pixels per CSS pixel. */
	ratio: number;
	/** The picture is shown at half size. */
	halve: boolean;
}

export class ChartPainter {
	private input: PaintInput | null = null;
	private latest: Run | null = null;
	/** The run whose picture is on the canvas. */
	private onCanvas: Run | null = null;
	/** The picture that the names are measured in, while more neighbours can come. */
	private kept: Pixels | null = null;
	private wanted: AbortController | null = null;
	private timer: ReturnType<typeof setTimeout> | undefined;
	private frameId = 0;
	private drawnOnce = false;
	private unwatch = (): void => {};
	private deviceRatio = globalThis.devicePixelRatio || 1;
	private stopRatio = (): void => {};
	private disposed = false;

	constructor(
		private readonly sky: ChartSky | null,
		private readonly events: PainterEvents
	) {
		this.watchRatio();
	}

	/** Paint `input` soon, or nothing. */
	show(input: PaintInput | null): void {
		if (this.disposed) return;
		const was = this.input?.frame;
		this.input = input;
		if (input?.frame !== was) {
			this.unwatch();
			this.unwatch = (input && this.sky?.watch(input.frame, () => this.schedule())) || (() => {});
		}
		this.schedule();
	}

	/** The same figure with more neighbours. The names of the picture on show
	 *  are found again, with no new paint. */
	extend(chart: LoadedChart): void {
		if (!this.input || this.disposed) return;
		this.input = { ...this.input, chart };
		const shown = this.onCanvas;
		// A run on its way names the stars with this chart itself.
		if (!shown || shown !== this.latest || !shown.input.search) return;
		const run: Run = { ...shown, input: this.input };
		this.latest = this.onCanvas = run;
		const pixels = this.kept;
		if (!chart.more) this.kept = null;
		this.name(run, chart, pixels).catch((e: unknown) => this.events.failed(e));
	}

	dispose(): void {
		this.disposed = true;
		this.wanted?.abort();
		clearTimeout(this.timer);
		cancelAnimationFrame(this.frameId);
		this.unwatch();
		this.stopRatio();
		this.input = this.latest = this.onCanvas = null;
		this.kept = null;
	}

	private watchRatio(): void {
		const query = matchMedia(`(resolution: ${this.deviceRatio}dppx)`);
		const read = (): void => {
			this.stopRatio();
			this.deviceRatio = globalThis.devicePixelRatio || 1;
			this.watchRatio();
			this.schedule();
		};
		query.addEventListener('change', read);
		this.stopRatio = () => query.removeEventListener('change', read);
	}

	private current(run: Run): boolean {
		return !this.disposed && this.latest === run && this.input?.frame === run.input.frame;
	}

	private schedule(): void {
		clearTimeout(this.timer);
		cancelAnimationFrame(this.frameId);
		this.wanted?.abort();
		this.wanted = null;
		const input = this.input;
		if (!input || this.disposed) return;
		const was = this.latest?.input;
		const resized =
			this.drawnOnce &&
			was?.chart.chart.points === input.chart.chart.points &&
			(was.frame.width !== input.frame.width || was.frame.height !== input.frame.height);
		const wanted = new AbortController();
		this.wanted = wanted;
		const start = (): void => {
			this.drawnOnce = true;
			const { frame, fill } = input;
			this.draw({
				input,
				signal: wanted.signal,
				// A small chart is painted alike on every screen, so every screen names
				// the same stars. A chart that fills a screen reads no more than it shows.
				ratio: paintRatio(frame.width, frame.height, fill ? this.deviceRatio : PAINT_RATIO),
				halve: !fill && this.deviceRatio <= 1
			}).catch((e: unknown) => this.events.failed(e));
		};
		this.timer = setTimeout(
			() => (this.frameId = requestAnimationFrame(start)),
			resized ? SETTLE_MS : 0
		);
	}

	/** Paint, then find the names. */
	private async draw(run: Run): Promise<void> {
		this.latest = run;
		const { frame, canvas } = run.input;
		const pixels =
			(await this.sky?.paint(
				frame,
				Math.round(frame.width * run.ratio),
				Math.round(frame.height * run.ratio),
				run.signal
			)) ?? null;
		if (!this.current(run) || run.signal.aborted) return;
		const context = canvas.getContext('2d');
		if (pixels && context) {
			const shown = run.halve ? halved(pixels) : pixels;
			canvas.width = shown.width;
			canvas.height = shown.height;
			context.putImageData(new ImageData(shown.data, shown.width, shown.height), 0, 0);
		}
		const chart = this.input!.chart;
		this.onCanvas = run;
		this.kept = null;
		this.events.painted(frame, !!pixels && !!context, chart);
		if (!run.input.search) {
			this.events.named(noNames(frame, run.input.points));
			return;
		}
		if (chart.more) this.kept = pixels;
		await this.name(run, chart, pixels);
	}

	private name(run: Run, chart: LoadedChart, pixels: Pixels | null): Promise<void> {
		const { frame, points, most, neighbours } = run.input;
		return findNames(
			{
				frame,
				chart: chart.chart,
				pixels,
				points,
				most,
				neighbours,
				name: chart.name,
				current: () => this.current(run)
			},
			(names) => this.events.named(names)
		);
	}
}
