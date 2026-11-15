<!-- The chart of a figure of a sky culture: the sky behind it, its lines, and
     the names of its stars as links. Drawn from `$lib/star-chart`. -->
<script lang="ts">
	import { getContext, onDestroy, untrack } from 'svelte';
	import type { LoadedChart } from '$lib/fetch/extrasolar/figures';
	import { extrasolarObjectId } from '$lib/fetch/extrasolar/ids';
	import { CHART_PICTURE, type StarChartPicture } from '$lib/fetch/objects/galleries';
	import { RetryBackoff } from '$lib/fetch/retry-backoff';
	import * as m from '$lib/paraglide/messages.js';
	import { constellationCreditName } from '$lib/scene/state/attribution';
	import type { ContextManager } from '$lib/scene/state/context-manager.svelte';
	import type { ChartCredits, SkyboxCredit } from '$lib/scene/state/credits.svelte';
	import type { ChartStar } from '$lib/star-chart/figure';
	import {
		figureAspect,
		fillFrame,
		fitFrame,
		project,
		type ChartFrame
	} from '$lib/star-chart/frame';
	import { placeNames, type LabelBox, type Segment } from '$lib/star-chart/labels';
	import {
		halved,
		PAINT_RATIO,
		paintedFlux,
		paintRatio,
		type ChartSky,
		type Pixels
	} from '$lib/star-chart/sky';
	import type { AppState } from '$lib/state/app-state.svelte';
	import { isModifiedClick } from '$lib/modified-click';
	import { focusClick, focusHref, imageHref } from '$lib/state/focus-link';
	import type { FocusObject } from '$lib/state/focusable';
	import type { DrawnCredit } from '../../image-viewer/ImageViewerCaption.svelte';

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
		/** The chart takes the size of its box, with the sky around the figure.
		 *  `aspect` and its limits do not apply. */
		fill?: boolean;
		/** With `fill`: CSS pixels at the sides, and at the top and bottom, that
		 *  the figure stays out of. */
		clear?: readonly [number, number];
		/** The parts of a chart of this size that something else covers. No name
		 *  goes there. The names move when the state that it reads changes. */
		covered?: (width: number, height: number) => readonly LabelBox[];
		/** Hears the works of each sky that the chart draws, as a caption names them. */
		oncredits?: (credits: DrawnCredit[]) => void;
		/** The shelf whose viewer shows the chart at full size. With it, the chart
		 *  is a link to that view. */
		gallery?: string;
		class?: string;
	}

	let {
		picture,
		name,
		aspect,
		minAspect = 0.8,
		maxAspect = 1.8,
		labels = true,
		fill = false,
		clear,
		covered,
		oncredits,
		gallery,
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
	/** A chart that fills its box has the room of a screen. */
	const FILL_LABEL_MAX = 40;
	const LABEL_HEIGHT_PX = 13;
	const LABEL_GAP_PX = 6;
	/** A line stops short of its star, so the star shows. */
	const STAR_CLEAR_PX = 5;
	/** A chart with no names needs no room for them, and its lines are short. */
	const BARE_MARGIN = 0.12;
	const BARE_CLEAR_PX = 2.5;
	const STAND_IN_RING_PX = 6;
	/** Radius of the disc that measures a star, in CSS pixels. */
	const FLUX_RADIUS_PX = 1.5;
	/** Under this painted light, a neighbour does not stand out of the sky.
	 *  Counted in a picture of {@link PAINT_RATIO}. */
	const NEIGHBOUR_MIN_FLUX = 400;
	/** A new size waits this long for the next one, so a drag paints once. */
	const SETTLE_MS = 120;

	interface Wanted {
		x: number;
		y: number;
		name: string;
		/** Object.id of a star. Absent on a member that has no page. */
		id?: string;
	}

	interface Label extends LabelBox, Omit<Wanted, 'x' | 'y'> {
		neighbour: boolean;
	}

	/** The names that a paint found for its frame, before they are laid out. */
	interface Found {
		frame: ChartFrame;
		family: string;
		/** The most names of members. */
		limit: number;
		/** Members: the stand-ins, then the stars, the brightest first. */
		own: Wanted[];
		/** Neighbours that stand out as much, the brightest first. */
		around: Wanted[];
		segments: Segment[];
		points: (readonly [number, number])[];
	}

	interface Loaded extends LoadedChart {
		/** The names asked for so far, by extrasolar ID. */
		names: Map<number, Promise<string | null>>;
	}

	let loaded = $state.raw<Loaded | null>(null);
	let failed = $state(false);
	let attempt = $state(0);
	let width = $state(0);
	let boxHeight = $state(0);
	let canvas = $state<HTMLCanvasElement | null>(null);
	let painted = $state(false);
	/** A paint ended with no sky. */
	let skyless = $state(false);
	let found = $state.raw<Found | null>(null);
	/** What the last paint drew, for the credits. */
	let drawn = $state.raw<ChartCredits | null>(null);
	let skyChanges = $state(0);
	let deviceRatio = $state(globalThis.devicePixelRatio || 1);
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
			found = null;
			drawn = null;
			painted = false;
			skyless = false;
			retry.clear('load');
			retry.clear('names');
		});
	});

	const sky: ChartSky | null = ctx?.chartSky ?? null;

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
	let height = $derived(fill ? boxHeight : Math.round(width / ratio));
	let frame = $derived.by(() => {
		if (!chart?.points.length || width <= 0 || height <= 0) return null;
		if (fill) return fillFrame(chart.points, { width, height, clear });
		return fitFrame(chart.points, { width, height, margin: labels ? undefined : BARE_MARGIN });
	});

	$effect(() => {
		if (frame) return sky?.watch(frame, () => skyChanges++);
	});

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
	let ringed = $derived(!!chart && (chart.lines.length === 0 || skyless));

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
		source: ChartSky | null;
		/** Aborted when the chart wants another picture, or none. */
		signal: AbortSignal;
		/** Painted pixels per CSS pixel. */
		ratio: number;
		/** The picture is shown at half size. */
		halve: boolean;
		named: boolean;
		/** The most names of members. */
		most: number;
		segments: Segment[];
		points: (readonly [number, number])[];
		standIns: (readonly [number, number])[];
	}

	let latest: Run | null = null;

	/** Paint, then find the names. A newer run ends this one. */
	async function draw(run: Run): Promise<void> {
		latest = run;
		const { at, of, target, source } = run;
		const pixels =
			(await source?.paint(
				at,
				Math.round(at.width * run.ratio),
				Math.round(at.height * run.ratio),
				run.signal
			)) ?? null;
		if (latest !== run || run.signal.aborted) return;
		const context = target.getContext('2d');
		if (pixels && context) {
			const shown = run.halve ? halved(pixels) : pixels;
			target.width = shown.width;
			target.height = shown.height;
			context.putImageData(new ImageData(shown.data, shown.width, shown.height), 0, 0);
		}
		painted = !!pixels && !!context;
		skyless = !painted;
		onCanvas = run;
		kept = null;
		drawn = { sky: painted, credits: (named ?? of).credits };
		ctx?.credits.setChart(creditKey, drawn);
		if (!run.named) {
			found = unnamed(run);
			return;
		}
		if ((named ?? of).more) kept = pixels;
		await nameStars(run, pixels);
	}

	function unnamed(run: Run): Found {
		return {
			frame: run.at,
			family: '',
			limit: 0,
			own: [],
			around: [],
			segments: run.segments,
			points: [...run.points, ...run.standIns]
		};
	}

	/** The members first, the brightest first, then the neighbours that stand
	 *  out as much. A newer run ends this one. */
	async function nameStars(run: Run, pixels: Pixels | null): Promise<void> {
		const { at, target } = run;
		const of = named ?? run.of;
		const empty = unnamed(run);
		const members = measureStars(at, of.chart.stars, pixels);
		const memberNames = await Promise.all(members.map(({ star }) => nameOf(of, star)));
		if (latest !== run) return;
		const limit = Math.min(Math.round((at.width * at.height) / LABEL_AREA_PX), run.most);
		const own: Found = {
			...empty,
			family: getComputedStyle(target).fontFamily,
			limit,
			// A member with no star has no light to rank it by, and its ring needs a name.
			own: [
				...of.chart.standIns.flatMap(({ name }, i) =>
					name ? [{ x: run.standIns[i][0], y: run.standIns[i][1], name }] : []
				),
				...members.flatMap(({ star, x, y }, i) => {
					const name = memberNames[i];
					return name ? [{ x, y, name, id: extrasolarObjectId(star.id) }] : [];
				})
			]
		};
		found = own;
		// With no sky, no star is known to be bright.
		if (!pixels) return;
		const floor = Math.max(
			median(members.map(({ flux }) => flux)),
			NEIGHBOUR_MIN_FLUX * (pixels.width / at.width / PAINT_RATIO) ** 2
		);
		const around = measureStars(at, of.chart.neighbours, pixels)
			.filter(({ flux }) => flux >= floor)
			.slice(0, limit);
		const aroundNames = await Promise.all(around.map(({ star }) => nameOf(of, star)));
		if (latest !== run) return;
		found = {
			...own,
			around: around.flatMap(({ star, x, y }, i) => {
				const name = aroundNames[i];
				return name ? [{ x, y, name, id: extrasolarObjectId(star.id) }] : [];
			})
		};
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
		drawn = { sky: painted, credits: named.credits };
		ctx?.credits.setChart(creditKey, drawn);
		if (!onCanvas.named) return;
		const run = { ...onCanvas };
		latest = onCanvas = run;
		const measured = kept;
		if (!fuller.more) kept = null;
		await nameStars(run, measured);
	}

	function layout(
		of: Found,
		wanted: readonly Wanted[],
		most: number,
		taken: readonly LabelBox[],
		neighbour: boolean
	): Label[] {
		return placeNames(
			wanted.map(({ x, y, name }) => ({
				x,
				y,
				width: textWidth(name, of.family),
				height: LABEL_HEIGHT_PX
			})),
			{
				width: of.frame.width,
				height: of.frame.height,
				gap: LABEL_GAP_PX,
				limit: most,
				segments: of.segments,
				points: of.points,
				taken
			}
		).map(({ index, ...box }) => ({
			...box,
			name: wanted[index].name,
			id: wanted[index].id,
			neighbour
		}));
	}

	// The names are laid out again when what covers the chart changes, with no new paint.
	let placed = $derived.by(() => {
		if (!found) return null;
		const { frame: at } = found;
		const taken = covered?.(at.width, at.height) ?? [];
		const own = layout(found, found.own, found.limit, taken, false);
		const others = layout(
			found,
			found.around,
			Math.ceil(found.limit / 2),
			[...taken, ...own],
			true
		);
		return { frame: at, labels: [...own, ...others] };
	});

	$effect(() => {
		const report = drawn;
		const skybox = ctx?.credits.skybox ?? null;
		if (report) oncredits?.(creditLines(report, skybox));
	});

	/** The works of a drawn chart that have a licence, as the credit bar names them. */
	function creditLines(report: ChartCredits, skybox: SkyboxCredit | null): DrawnCredit[] {
		const givers = new Map<string, DrawnCredit['works'][number]>();
		for (const credit of report.credits) {
			const name = constellationCreditName(credit);
			if (credit.license && !givers.has(name))
				givers.set(name, { name, href: credit.source, license: credit.license });
		}
		const sky = report.sky && skybox;
		return [
			{
				label: m.attribution_section_skybox(),
				works: sky ? [{ name: sky.organisation, href: sky.source, license: sky.license }] : []
			},
			{ label: m.attribution_constellations(), works: [...givers.values()] }
		].filter(({ works }) => works.length > 0);
	}

	// One paint per frame at most. A chart that is on screen waits for its size to settle.
	let drawnOnce = false;
	$effect(() => {
		const at = frame;
		const of = loaded;
		const target = canvas;
		if (!at || !of || !target) return;
		const wanted = new AbortController();
		const run: Run = {
			at,
			of,
			target,
			source: sky,
			signal: wanted.signal,
			// A small chart is painted alike on every screen, so every screen names
			// the same stars. A chart that fills a screen reads no more than it shows.
			ratio: paintRatio(at.width, at.height, fill ? deviceRatio : PAINT_RATIO),
			halve: !fill && deviceRatio <= 1,
			named: labels && Math.min(at.width, at.height) >= LABEL_MIN_PX,
			most: fill ? FILL_LABEL_MAX : LABEL_MAX,
			segments,
			points: starPoints,
			standIns: standInPoints
		};
		void skyChanges;
		const resized = untrack(() => {
			const was = latest?.at;
			const sized = was?.width !== at.width || was.height !== at.height;
			return drawnOnce && latest?.of === of && sized;
		});
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
			wanted.abort();
		};
	});

	function open(e: MouseEvent) {
		if (isModifiedClick(e) || gallery === undefined) return;
		e.preventDefault();
		appState.setImage(CHART_PICTURE, gallery);
	}

	/** The names of another size are not at their stars. */
	let shown = $derived(placed && placed.frame === frame ? placed.labels : []);
</script>

{#if !failed}
	<!-- The sky has its own left and right: east is on the left in every language. -->
	<figure
		class="chart {className}"
		class:fill
		dir="ltr"
		aria-label={m.star_chart_label({ name })}
		bind:clientWidth={width}
		bind:clientHeight={boxHeight}
		style:aspect-ratio={fill ? undefined : ratio}
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
		{#if gallery !== undefined}
			<!-- Under the names: a name is a link of its own. -->
			<a
				href={imageHref(appState, CHART_PICTURE, gallery)}
				onclick={open}
				aria-label={m.image_open_viewer()}
				class="open"
			></a>
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
	.chart.fill {
		width: 100%;
		height: 100%;
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
		/* The picture of another size keeps its shape until the next paint. */
		object-fit: cover;
		opacity: 0;
		transition: opacity 0.3s;
	}
	canvas.painted {
		opacity: 1;
	}

	.open {
		position: absolute;
		inset: 0;
		border-radius: inherit;
		cursor: zoom-in;
	}
	.open:focus-visible {
		outline: 2px solid var(--color-ring);
		outline-offset: -2px;
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
	/* A name with no page lets a click through to the chart's own link. */
	span.name {
		pointer-events: none;
	}
	a.name:hover,
	a.name:focus-visible {
		color: #fff;
		text-decoration: underline;
	}
</style>
