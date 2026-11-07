<script lang="ts">
	/** A Hertzsprung–Russell diagram: a random sample of the stars, by stage,
	 *  with the page's listed stars on top. */

	import { getContext, untrack } from 'svelte';
	import { scaleLinear } from 'd3-scale';
	import { Skeleton } from '$lib/components/ui/skeleton/index.js';
	import type { NotableMemberEntry } from '$lib/fetch/objects/object-data';
	import { STAR_FAMILY_SLUG_PREFIX } from '$lib/fetch/groups/registry';
	import { fetchStarPlot, type StarPlotFile } from '$lib/fetch/groups/star-plot';
	import { familyLabel } from '$lib/format/group';
	import { formatNumber } from '$lib/format/quantities';
	import * as m from '$lib/paraglide/messages.js';
	import type { AppState } from '$lib/state/app-state.svelte';
	import { focusClick, focusHref } from '$lib/state/focus-link';
	import type { FocusObject } from '$lib/state/focusable';
	import ScatterAxes from './ScatterAxes.svelte';

	interface Props {
		members: NotableMemberEntry[];
		localizedNames?: Record<string, string>;
		/** The overview is the tab in view. */
		active: boolean;
	}
	let { members, localizedNames, active }: Props = $props();

	const appState = getContext<AppState | undefined>('appState');
	const focusObject = getContext<FocusObject | undefined>('focusObject');

	// Taller than wide, as HR diagrams usually are.
	const HEIGHT_PER_WIDTH = 8 / 7;
	const M = { top: 8, right: 10, bottom: 32, left: 34 };
	// Bright stars sit at the top, by the diagram's convention.
	const X_DOMAIN = [-0.8, 6];
	const Y_DOMAIN = [-7, 17];
	const X_TICKS = [0, 2, 4, 6];
	const Y_TICKS = [-5, 0, 5, 10, 15];
	const DOT = 1.6;
	// Low, so overlapping dots build up and the dense parts read darker.
	const DOT_ALPHA = 0.16;
	const NAMED = 3;
	const PICK_R2 = 12 * 12;
	const UNCLASSIFIED = '#8a8a8a';
	const STAGE_COLORS: Record<string, string> = {
		'main-sequence': '#3b7be0',
		subgiant: '#1f9e8f',
		giant: '#c7900f',
		supergiant: '#d2452a',
		'white-dwarf': '#a8388f'
	};

	let file = $state.raw<StarPlotFile | null>(null);
	// Without the file the chart goes, rather than pulse as if still loading.
	let failed = $state(false);
	$effect(() => {
		if (!active) return;
		let live = true;
		untrack(fetchStarPlot).then(
			(f) => {
				if (live) file = f;
			},
			(e: unknown) => {
				console.warn('[stars] no plot file:', e);
				if (live) failed = true;
			}
		);
		return () => {
			live = false;
		};
	});

	let width = $state(0);
	let innerW = $derived(Math.max(0, width - M.left - M.right));
	let height = $derived(width * HEIGHT_PER_WIDTH);
	let innerH = $derived(Math.max(0, height - M.top - M.bottom));
	let xScale = $derived(scaleLinear().domain(X_DOMAIN).range([0, innerW]));
	let yScale = $derived(scaleLinear().domain(Y_DOMAIN).range([0, innerH]));

	let canvas = $state<HTMLCanvasElement | null>(null);
	$effect(() => {
		if (!canvas || !file || innerW === 0) return;
		const ratio = window.devicePixelRatio || 1;
		canvas.width = innerW * ratio;
		canvas.height = innerH * ratio;
		const ctx = canvas.getContext('2d');
		if (!ctx) return;
		ctx.scale(ratio, ratio);
		const colors = file.stages.map((stage) => STAGE_COLORS[stage] ?? UNCLASSIFIED);
		ctx.globalAlpha = DOT_ALPHA;
		// Grey first, so the classified stars read over it.
		for (const classified of [false, true]) {
			for (let i = 0; i < file.stage.length; i++) {
				const stage = file.stage[i];
				if ((stage !== null) !== classified) continue;
				ctx.fillStyle = stage === null ? UNCLASSIFIED : colors[stage];
				ctx.fillRect(xScale(file.bp_rp[i]), yScale(file.abs_g[i]), DOT, DOT);
			}
		}
	});

	let names = $derived(
		new Map(members.map((e) => [e.id ?? '', localizedNames?.[e.id ?? ''] ?? e.name]))
	);
	let named = $derived(
		(file?.named ?? [])
			.filter((p) => names.has(p.id))
			.map((p) => ({
				...p,
				name: names.get(p.id) as string,
				px: xScale(p.bp_rp),
				py: yScale(p.abs_g)
			}))
	);
	let sun = $derived(named.find((p) => p.id === 'naif-10'));

	let hit = $state<(typeof named)[number] | null>(null);
	let mouse = $state({ x: 0, y: 0 });
	let containerEl = $state<HTMLDivElement | null>(null);

	function hitAt(clientX: number, clientY: number) {
		if (!containerEl) return;
		const rect = containerEl.getBoundingClientRect();
		mouse = { x: clientX - rect.left, y: clientY - rect.top };
		let best = null;
		let bestD = PICK_R2;
		for (const p of named) {
			const d = (mouse.x - M.left - p.px) ** 2 + (mouse.y - M.top - p.py) ** 2;
			if (d < bestD) {
				bestD = d;
				best = p;
			}
		}
		hit = best;
	}

	let legend = $derived([
		...(file?.stages ?? []).toReversed().map((stage) => ({
			color: STAGE_COLORS[stage],
			label: familyLabel(`${STAR_FAMILY_SLUG_PREFIX}${stage}`)
		})),
		{ color: UNCLASSIFIED, label: m.star_plot_legend_unclassified() }
	]);
</script>

{#if !failed}
	<div class="flex flex-col gap-1">
		<h3 class="text-sm font-medium">{m.star_plot_title()}</h3>
		<div class="border-border/60 border-t"></div>
		<div class="pt-1">
			{#if file}
				<!-- The axes read left to right in every language: colour is a scale, not text. -->
				<div
					dir="ltr"
					class="relative w-full"
					bind:this={containerEl}
					bind:clientWidth={width}
					style:aspect-ratio="7 / 8"
					onmousemove={(e) => hitAt(e.clientX, e.clientY)}
					onmouseleave={() => (hit = null)}
					role="group"
					aria-label={m.star_plot_title()}
				>
					{#if width > 0}
						<canvas
							bind:this={canvas}
							class="pointer-events-none absolute"
							style:left="{M.left}px"
							style:top="{M.top}px"
							style:width="{innerW}px"
							style:height="{innerH}px"
						></canvas>
						<svg {width} {height} viewBox="0 0 {width} {height}" class="absolute inset-0">
							<g transform="translate({M.left},{M.top})">
								<rect
									width={innerW}
									height={innerH}
									fill="none"
									class="stroke-border"
									stroke-width="1"
								/>
								{#each named as p (p.id)}
									<a
										href={focusHref(appState, p.id, p.name)}
										onclick={focusClick(focusObject, p.id, p.name)}
										aria-label={p.name}
									>
										<circle
											cx={p.px}
											cy={p.py}
											r={p === hit ? NAMED + 1.5 : NAMED}
											class="fill-foreground stroke-background"
											stroke-width="1.5"
										/>
									</a>
								{/each}
								{#if sun}
									<text
										x={sun.px + NAMED + 4}
										y={sun.py}
										dominant-baseline="central"
										class="fill-foreground pointer-events-none text-2xs font-medium"
									>
										{sun.name}
									</text>
								{/if}
								<ScatterAxes
									{innerW}
									{innerH}
									marginLeft={M.left}
									marginBottom={M.bottom}
									{xScale}
									{yScale}
									xTicks={X_TICKS}
									yTicks={Y_TICKS}
									formatTick={formatNumber}
									xLabel={m.star_plot_axis_colour()}
									yLabel={m.star_plot_axis_magnitude()}
								/>
							</g>
						</svg>
					{/if}
					{#if hit}
						<div
							class="bg-foreground text-background pointer-events-none absolute z-50 -translate-y-full rounded-md px-2 py-1 text-xs shadow-md"
							style:left="{mouse.x + 10}px"
							style:top="{mouse.y - 8}px"
						>
							{hit.name}
						</div>
					{/if}
				</div>
			{:else}
				<Skeleton class="w-full rounded-md" style="aspect-ratio: 7 / 8" />
			{/if}
		</div>
		{#if file}
			<div class="text-muted-foreground flex flex-wrap items-center gap-x-3 gap-y-1 pt-1 text-xs">
				{#each legend as item (item.label)}
					<span class="flex items-center gap-1.5">
						<svg class="size-2" viewBox="0 0 8 8" aria-hidden="true">
							<circle cx="4" cy="4" r="3.5" fill={item.color} />
						</svg>
						{item.label}
					</span>
				{/each}
			</div>
			<p class="text-muted-foreground text-xs">
				{m.star_plot_sample({ count: formatNumber(file.stage.length) })}
			</p>
		{/if}
	</div>
{/if}
