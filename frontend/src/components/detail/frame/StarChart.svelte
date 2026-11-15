<!-- The chart of a figure of a sky culture: the sky behind it, its lines, and
     the names of its stars as links. Drawn from `$lib/star-chart`. -->
<script lang="ts">
	import { getContext, onDestroy, untrack } from 'svelte';
	import type { LoadedChart } from '$lib/fetch/extrasolar/figures';
	import { extrasolarObjectId } from '$lib/fetch/extrasolar/ids';
	import type { StarChartPicture } from '$lib/fetch/objects/galleries';
	import { RetryBackoff } from '$lib/fetch/retry-backoff';
	import * as m from '$lib/paraglide/messages.js';
	import type { ContextManager } from '$lib/scene/state/context-manager.svelte';
	import type { ChartStar } from '$lib/star-chart/figure';
	import { figureAspect, fitFrame, project, type ChartFrame } from '$lib/star-chart/frame';
	import { placeNames, type LabelBox, type Segment } from '$lib/star-chart/labels';
	import { paintedFlux, type Pixels, type SkySource } from '$lib/star-chart/sky';
	import type { AppState } from '$lib/state/app-state.svelte';
	import { focusClick, focusHref } from '$lib/state/focus-link';
	import type { FocusObject } from '$lib/state/focusable';

	interface Props {
		picture: StarChartPicture;
		/** The figure's name, for readers who do not see the chart. */
		name: string;
		/** Width over height. Absent: the figure's own, within the two limits. */
		aspect?: number;
		minAspect?: number;
		maxAspect?: number;
		/** False for a chart too small to hold names. */
		labels?: boolean;
		class?: string;
	}

	let {
		picture,
		name,
		aspect,
		minAspect = 0.8,
		maxAspect = 1.8,
		labels = true,
		class: className = ''
	}: Props = $props();

	const appState = getContext<AppState>('appState');
	const ctx = getContext<ContextManager | undefined>('ctx');
	const focusObject = getContext<FocusObject | undefined>('focusObject');

	/** A frame under this size on its short side holds no names. */
	const LABEL_MIN_PX = 150;
	/** One name per this many square pixels. */
	const LABEL_AREA_PX = 11000;
	const LABEL_MAX = 14;
	const LABEL_HEIGHT_PX = 13;
	const LABEL_GAP_PX = 6;
	/** A line stops short of its star, so the star shows. */
	const STAR_CLEAR_PX = 5;
	/** A chart with no names needs no room for them, and its lines are short. */
	const BARE_MARGIN = 0.12;
	const BARE_CLEAR_PX = 2.5;
	const STAND_IN_RING_PX = 6;
	/** A sharper canvas costs a larger read from the GPU for no gain. */
	const MAX_PIXEL_RATIO = 2;
	/** The stars are measured in a picture of this pixel ratio on every screen,
	 *  so every screen names the same stars. */
	const MEASURE_RATIO = 2;
	/** Radius of the disc that measures a star, in CSS pixels. */
	const FLUX_RADIUS_PX = 1.5;
	/** Under this painted light, a neighbour does not stand out of the sky. */
	const NEIGHBOUR_MIN_FLUX = 400;
	/** A new size waits this long for the next one, so a drag paints once. */
	const SETTLE_MS = 120;

	interface Label extends LabelBox {
		name: string;
		/** Object.id of a star. Absent on a member that has no page. */
		id?: string;
		neighbour: boolean;
	}

	interface Loaded extends LoadedChart {
		/** The names asked for so far, by extrasolar ID. */
		names: Map<number, Promise<string | null>>;
	}

	let loaded = $state.raw<Loaded | null>(null);
	let failed = $state(false);
	let attempt = $state(0);
	let width = $state(0);
	let canvas = $state<HTMLCanvasElement | null>(null);
	let painted = $state(false);
	let placed = $state.raw<{ frame: ChartFrame; labels: Label[] } | null>(null);
	let deviceRatio = $state(globalThis.devicePixelRatio || 1);
	let skyChanges = $state(0);
	/** The loaded chart, or the same with the neighbours of a later read. Not
	 *  state: new neighbours change the names, not the frame. */
	let named: Loaded | null = null;
	/** The run whose picture is on the canvas. */
	let onCanvas: Run | null = null;
	/** The picture that the names are measured in, while more neighbours can come. */
	let kept: Pixels | null = null;

	const retry = new RetryBackoff<'load' | 'names'>((key) =>
		key === 'load' ? attempt++ : void readNames()
	);
	const creditKey = {};
	onDestroy(() => {
		retry.clear('load');
		retry.clear('names');
		ctx?.credits.setChart(creditKey, null);
	});

	$effect(() => {
		const { load, slug, figure } = picture;
		void attempt;
		let current = true;
		load().then(
			(chart) => {
				if (!current) return;
				loaded = named = { ...chart, names: new Map() };
				failed = false;
				retry.clear('load');
				// A chart with no neighbours yet draws now and reads them again later.
				if (chart.more) retry.fail('names');
				else retry.clear('names');
			},
			(e: unknown) => {
				if (!current) return;
				console.warn(`[star-chart] no chart of ${slug}/${figure}:`, e);
				failed = true;
				retry.fail('load');
			}
		);
		return () => {
			current = false;
		};
	});
	// Another figure: the chart of the last one must not show under its name.
	$effect.pre(() => {
		void picture.slug;
		void picture.figure;
		untrack(() => {
			loaded = named = null;
			onCanvas = kept = null;
			placed = null;
			painted = false;
			retry.clear('load');
			retry.clear('names');
		});
	});

	let sky = $derived<SkySource | null>(ctx?.chartSky ?? null);
	$effect(() => sky?.onChange(() => skyChanges++));

	$effect(() => {
		const query = matchMedia(`(resolution: ${deviceRatio}dppx)`);
		const read = () => (deviceRatio = window.devicePixelRatio || 1);
		query.addEventListener('change', read);
		return () => query.removeEventListener('change', read);
	});

	let chart = $derived(loaded?.chart ?? null);
	let ratio = $derived(
		aspect ?? (chart?.points.length ? figureAspect(chart.points, minAspect, maxAspect) : 4 / 3)
	);
	let height = $derived(Math.round(width / ratio));
	let frame = $derived(
		chart?.points.length && width > 0
			? fitFrame(chart.points, { width, height, margin: labels ? undefined : BARE_MARGIN })
			: null
	);

	let segments = $derived.by((): Segment[] => {
		if (!frame || !chart) return [];
		const at = frame;
		return chart.lines.map(([a, b]) => [...project(at, a), ...project(at, b)] as const);
	});

	/** The lines, each cut short at both ends. */
	let path = $derived(
		segments
			.map(([x1, y1, x2, y2]) => {
				const length = Math.hypot(x2 - x1, y2 - y1);
				if (length === 0) return '';
				// A short line keeps half of its length.
				const clear = Math.min(labels ? STAR_CLEAR_PX : BARE_CLEAR_PX, length / 4) / length;
				const ux = (x2 - x1) * clear;
				const uy = (y2 - y1) * clear;
				return `M${(x1 + ux).toFixed(1)} ${(y1 + uy).toFixed(1)}L${(x2 - ux).toFixed(1)} ${(y2 - uy).toFixed(1)}`;
			})
			.join('')
	);

	let starPoints = $derived.by(() => {
		if (!frame || !chart) return [];
		const at = frame;
		return chart.stars.map(({ direction }) => project(at, direction));
	});
	let standInPoints = $derived.by(() => {
		if (!frame || !chart) return [];
		const at = frame;
		return chart.standIns.map(({ direction }) => project(at, direction));
	});

	/** A figure with no lines shows its stars by a ring. So does one with no sky. */
	let ringed = $derived(!!chart && (chart.lines.length === 0 || !painted));

	interface Measured {
		star: ChartStar;
		x: number;
		y: number;
		flux: number;
	}

	/** The stars inside the frame, the brightest in the painted sky first. */
	function measureStars(
		at: ChartFrame,
		stars: readonly ChartStar[],
		pixels: Pixels | null
	): Measured[] {
		const scale = pixels ? pixels.width / at.width : 1;
		return stars
			.map((star) => {
				const [x, y] = project(at, star.direction);
				const flux = pixels ? paintedFlux(pixels, x * scale, y * scale, FLUX_RADIUS_PX * scale) : 0;
				return { star, x, y, flux };
			})
			.filter(({ x, y }) => x >= 0 && y >= 0 && x <= at.width && y <= at.height)
			.sort((a, b) => b.flux - a.flux);
	}

	function median(values: number[]): number {
		const sorted = [...values].sort((a, b) => a - b);
		return sorted[sorted.length >> 1] ?? 0;
	}

	function nameOf(of: Loaded, star: ChartStar): Promise<string | null> {
		let asked = of.names.get(star.id);
		if (!asked) of.names.set(star.id, (asked = of.name(star).catch(() => null)));
		return asked;
	}

	let pen: CanvasRenderingContext2D | null = null;
	function textWidth(text: string, family: string): number {
		pen ??= document.createElement('canvas').getContext('2d');
		if (!pen) return text.length * 6;
		pen.font = `500 11px ${family}`;
		return Math.ceil(pen.measureText(text).width);
	}

	/** What one run draws. A run reads nothing else after it starts. */
	interface Run {
		at: ChartFrame;
		of: Loaded;
		target: HTMLCanvasElement;
		source: SkySource | null;
		pixelRatio: number;
		named: boolean;
		segments: Segment[];
		points: (readonly [number, number])[];
		standIns: (readonly [number, number])[];
	}

	let latest: Run | null = null;

	/** Paint, then name. A newer run ends this one. */
	async function draw(run: Run): Promise<void> {
		latest = run;
		const { at, of, target, source } = run;
		const scaled = (pixelRatio: number): [number, number] => [
			Math.round(at.width * pixelRatio),
			Math.round(at.height * pixelRatio)
		];
		const pixels = (await source?.paint(at, ...scaled(run.pixelRatio))) ?? null;
		if (latest !== run) return;
		const context = target.getContext('2d');
		if (pixels && context) {
			target.width = pixels.width;
			target.height = pixels.height;
			context.putImageData(new ImageData(pixels.data, pixels.width, pixels.height), 0, 0);
		}
		painted = !!pixels && !!context;
		onCanvas = run;
		kept = null;
		ctx?.credits.setChart(creditKey, { sky: painted, credits: (named ?? of).credits });
		if (!run.named) {
			placed = { frame: at, labels: [] };
			return;
		}
		const measured =
			pixels && run.pixelRatio !== MEASURE_RATIO
				? ((await source?.paint(at, ...scaled(MEASURE_RATIO))) ?? null)
				: pixels;
		if (latest !== run) return;
		if ((named ?? of).more) kept = measured;
		await nameStars(run, measured);
	}

	/** The members first, the brightest first, then the neighbours that stand
	 *  out as much. A newer run ends this one. */
	async function nameStars(run: Run, measured: Pixels | null): Promise<void> {
		const { at, target } = run;
		const of = named ?? run.of;
		const members = measureStars(at, of.chart.stars, measured);
		const memberNames = await Promise.all(members.map(({ star }) => nameOf(of, star)));
		if (latest !== run) return;
		const family = getComputedStyle(target).fontFamily;
		const limit = Math.min(Math.round((at.width * at.height) / LABEL_AREA_PX), LABEL_MAX);
		const layout = (
			wanted: { x: number; y: number; name: string; id?: string }[],
			most: number,
			taken: Label[],
			neighbour: boolean
		): Label[] =>
			placeNames(
				wanted.map(({ x, y, name }) => ({
					x,
					y,
					width: textWidth(name, family),
					height: LABEL_HEIGHT_PX
				})),
				{
					width: at.width,
					height: at.height,
					gap: LABEL_GAP_PX,
					limit: most,
					segments: run.segments,
					points: [...run.points, ...run.standIns],
					taken
				}
			).map(({ index, ...box }) => ({
				...box,
				name: wanted[index].name,
				id: wanted[index].id,
				neighbour
			}));
		// A member with no star has no light to rank it by, and its ring needs a name.
		const own = layout(
			[
				...of.chart.standIns.flatMap(({ name }, i) =>
					name ? [{ x: run.standIns[i][0], y: run.standIns[i][1], name }] : []
				),
				...members.flatMap(({ star, x, y }, i) => {
					const name = memberNames[i];
					return name ? [{ x, y, name, id: extrasolarObjectId(star.id) }] : [];
				})
			],
			limit,
			[],
			false
		);
		placed = { frame: at, labels: own };
		// With no sky, no star is known to be bright.
		if (!measured) return;
		const floor = Math.max(median(members.map(({ flux }) => flux)), NEIGHBOUR_MIN_FLUX);
		const around = measureStars(at, of.chart.neighbours, measured)
			.filter(({ flux }) => flux >= floor)
			.slice(0, limit);
		const aroundNames = await Promise.all(around.map(({ star }) => nameOf(of, star)));
		if (latest !== run) return;
		const others = layout(
			around.flatMap(({ star, x, y }, i) => {
				const name = aroundNames[i];
				return name ? [{ x, y, name, id: extrasolarObjectId(star.id) }] : [];
			}),
			Math.ceil(limit / 2),
			own,
			true
		);
		placed = { frame: at, labels: [...own, ...others] };
	}

	/** Read the international names again. New neighbours are named on the
	 *  picture that is shown, with no new paint. */
	async function readNames(): Promise<void> {
		const of = named;
		if (!of?.more) return;
		const fuller = await of.more();
		if (named !== of) return;
		named = { ...fuller, names: of.names };
		if (fuller.more) retry.fail('names');
		else retry.clear('names');
		// A run on its way names the stars with these neighbours itself.
		if (!onCanvas || onCanvas !== latest) return;
		ctx?.credits.setChart(creditKey, { sky: painted, credits: named.credits });
		if (!onCanvas.named) return;
		const run = { ...onCanvas };
		latest = onCanvas = run;
		const measured = kept;
		if (!fuller.more) kept = null;
		await nameStars(run, measured);
	}

	// One paint per frame at most. A chart that is on screen waits for its size to settle.
	let drawnOnce = false;
	$effect(() => {
		const at = frame;
		const of = loaded;
		const target = canvas;
		if (!at || !of || !target) return;
		const run: Run = {
			at,
			of,
			target,
			source: sky,
			pixelRatio: Math.min(deviceRatio, MAX_PIXEL_RATIO),
			named: labels && Math.min(at.width, at.height) >= LABEL_MIN_PX,
			segments,
			points: starPoints,
			standIns: standInPoints
		};
		void skyChanges;
		const resized = untrack(() => drawnOnce && latest?.of === of && latest.at.width !== at.width);
		const start = () => {
			drawnOnce = true;
			draw(run).catch((e: unknown) => console.warn('[star-chart] draw failed:', e));
		};
		let frameId = 0;
		const timer = setTimeout(
			() => (frameId = requestAnimationFrame(start)),
			resized ? SETTLE_MS : 0
		);
		return () => {
			clearTimeout(timer);
			cancelAnimationFrame(frameId);
		};
	});

	/** The names of another size are not at their stars. */
	let shown = $derived(placed && placed.frame === frame ? placed.labels : []);
</script>

{#if !failed}
	<!-- The sky has its own left and right: east is on the left in every language. -->
	<figure
		class="chart {className}"
		dir="ltr"
		aria-label={m.star_chart_label({ name })}
		bind:clientWidth={width}
		style:aspect-ratio={ratio}
	>
		<canvas bind:this={canvas} class:painted aria-hidden="true"></canvas>
		{#if frame}
			<svg viewBox="0 0 {frame.width} {frame.height}" aria-hidden="true">
				<path d={path} class="lines" />
				{#if ringed}
					{#each starPoints as [x, y], i (i)}
						<circle cx={x} cy={y} r="3.5" class="ring" />
					{/each}
				{/if}
				{#each standInPoints as [x, y], i (i)}
					<circle cx={x} cy={y} r={labels ? STAND_IN_RING_PX : STAND_IN_RING_PX / 2} class="ring" />
				{/each}
			</svg>
		{/if}
		{#each shown as label, i (i)}
			{#if label.id}
				<a
					href={focusHref(appState, label.id, label.name)}
					onclick={focusClick(focusObject, label.id, label.name)}
					class="name"
					class:neighbour={label.neighbour}
					style:left="{label.left}px"
					style:top="{label.top}px"
					style:height="{label.height}px"><bdi>{label.name}</bdi></a
				>
			{:else}
				<span
					class="name"
					style:left="{label.left}px"
					style:top="{label.top}px"
					style:height="{label.height}px"><bdi>{label.name}</bdi></span
				>
			{/if}
		{/each}
	</figure>
{/if}

<style>
	.chart {
		position: relative;
		margin: 0;
		overflow: hidden;
		background: #05070c;
	}

	canvas,
	svg {
		position: absolute;
		inset: 0;
		width: 100%;
		height: 100%;
		pointer-events: none;
	}
	canvas {
		opacity: 0;
		transition: opacity 0.3s;
	}
	canvas.painted {
		opacity: 1;
	}

	.lines {
		fill: none;
		stroke: rgb(150 180 235 / 0.6);
		stroke-width: 1;
		stroke-linecap: round;
	}
	.ring {
		fill: none;
		stroke: rgb(150 180 235 / 0.7);
		stroke-width: 1;
	}

	.name {
		position: absolute;
		font-size: 11px;
		font-weight: 500;
		line-height: 13px;
		white-space: nowrap;
		color: rgb(255 255 255 / 0.92);
		text-shadow:
			0 0 3px rgb(0 0 0 / 0.95),
			0 0 6px rgb(0 0 0 / 0.8);
	}
	.name.neighbour {
		color: rgb(255 255 255 / 0.55);
	}
	a.name:hover,
	a.name:focus-visible {
		color: #fff;
		text-decoration: underline;
	}
</style>
