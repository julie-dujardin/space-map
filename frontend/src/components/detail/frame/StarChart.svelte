<!-- The chart of a figure of a sky culture: the sky behind it, its lines, and
     the names of its stars as links. Drawn from `$lib/star-chart`. -->
<script lang="ts">
	import { getContext, onDestroy, untrack } from 'svelte';
	import type { LoadedChart } from '$lib/fetch/extrasolar/figures';
	import { CHART_PICTURE, type StarChartPicture } from '$lib/fetch/objects/galleries';
	import { RetryBackoff } from '$lib/fetch/retry-backoff';
	import * as m from '$lib/paraglide/messages.js';
	import { constellationCreditName } from '$lib/scene/state/attribution';
	import type { ContextManager } from '$lib/scene/state/context-manager.svelte';
	import type { ChartCredits, SkyboxCredit } from '$lib/scene/state/credits.svelte';
	import type { LabelBox } from '$lib/star-chart/labels';
	import {
		chartPoints,
		chooseFrame,
		FILL_LABEL_MAX,
		LABEL_MAX,
		LABEL_MIN_PX,
		layoutNames,
		linePath,
		nameWidth,
		rememberNames,
		STAND_IN_RING_PX,
		type ChartNames,
		type ChartPoints
	} from '$lib/star-chart/overlay';
	import { ChartPainter } from '$lib/star-chart/painter';
	import type { ChartSky } from '$lib/star-chart/sky';
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

	let loaded = $state.raw<LoadedChart | null>(null);
	let failed = $state(false);
	let attempt = $state(0);
	let width = $state(0);
	let boxHeight = $state(0);
	let canvas = $state<HTMLCanvasElement | null>(null);
	let painted = $state(false);
	/** A paint ended with no sky. */
	let skyless = $state(false);
	let found = $state.raw<ChartNames | null>(null);
	/** The font of the names, read at each paint. */
	let family = $state('');
	/** What the last paint drew, for the credits. */
	let drawn = $state.raw<ChartCredits | null>(null);
	/** The loaded chart, or the same with the neighbours of a later read. Not
	 *  state: new neighbours change the names, not the frame. */
	let named: LoadedChart | null = null;

	const retry = new RetryBackoff<'load' | 'names'>((key) =>
		key === 'load' ? attempt++ : void readNames()
	);
	const creditKey = {};
	const sky: ChartSky | null = ctx?.chartSky ?? null;
	const painter = new ChartPainter(sky, {
		painted: (_, shown, of) => {
			painted = shown;
			skyless = !shown;
			drawn = { sky: shown, credits: of.credits };
			ctx?.credits.setChart(creditKey, drawn);
			if (canvas) family = getComputedStyle(canvas).fontFamily;
		},
		named: (names) => (found = names),
		failed: (e) => console.warn('[star-chart] draw failed:', e)
	});
	onDestroy(() => {
		painter.dispose();
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
				loaded = named = { ...chart, name: rememberNames(chart.name) };
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
			found = null;
			drawn = null;
			painted = false;
			skyless = false;
			retry.clear('load');
			retry.clear('names');
		});
	});

	/** Read the international names again. New neighbours are named on the
	 *  picture that is shown, with no new paint. */
	async function readNames(): Promise<void> {
		const of = named;
		if (!of?.more) return;
		const fuller = await of.more();
		if (named !== of) return;
		named = { ...fuller, name: of.name };
		if (fuller.more) retry.fail('names');
		else retry.clear('names');
		if (drawn) {
			drawn = { sky: drawn.sky, credits: named.credits };
			ctx?.credits.setChart(creditKey, drawn);
		}
		painter.extend(named);
	}

	let chart = $derived(loaded?.chart ?? null);
	// The box's height only counts with `fill`: a frame is made again when it changes.
	let boxShare = $derived(fill ? boxHeight : 0);
	let choice = $derived(
		chooseFrame(chart, {
			width,
			height: boxShare,
			fill,
			labels,
			aspect,
			minAspect,
			maxAspect,
			clear
		})
	);
	let frame = $derived(choice.frame);

	let points = $derived<ChartPoints | null>(frame && chart ? chartPoints(frame, chart) : null);
	let path = $derived(points ? linePath(points.segments, labels) : '');

	/** A figure with no lines shows its stars by a ring. So does one with no sky. */
	let ringed = $derived(!!chart && (chart.lines.length === 0 || skyless));

	const textWidth = nameWidth();

	// The names are laid out again when what covers the chart changes, with no new paint.
	let placed = $derived.by(() => {
		if (!found) return null;
		const { frame: at } = found;
		const font = family;
		const taken = covered?.(at.width, at.height) ?? [];
		return { frame: at, labels: layoutNames(found, (text) => textWidth(text, font), taken) };
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

	$effect(() => {
		const at = frame;
		const of = loaded && (named ?? loaded);
		painter.show(
			at && of && canvas && points
				? {
						frame: at,
						points,
						chart: of,
						canvas,
						fill,
						search: labels && Math.min(at.width, at.height) >= LABEL_MIN_PX,
						most: fill ? FILL_LABEL_MAX : LABEL_MAX,
						neighbours: true
					}
				: null
		);
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
		style:aspect-ratio={fill ? undefined : choice.ratio}
	>
		<canvas bind:this={canvas} class:painted aria-hidden="true"></canvas>
		{#if frame}
			<svg viewBox="0 0 {frame.width} {frame.height}" aria-hidden="true">
				<path d={path} class="lines" />
				{#if ringed}
					{#each points?.stars ?? [] as [x, y], i (i)}
						<circle cx={x} cy={y} r="3.5" class="ring" />
					{/each}
				{/if}
				{#each points?.standIns ?? [] as [x, y], i (i)}
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
