<script lang="ts">
	/**
	 * The two charts of the Planets overview: mass against radius, and mass
	 * against distance from the star. The plot file loads the first time the
	 * overview is in view.
	 */
	import { untrack } from 'svelte';
	import { Skeleton } from '$lib/components/ui/skeleton/index.js';
	import * as m from '$lib/paraglide/messages.js';
	import { formatNumber } from '$lib/format/quantities';
	import { fetchPlanetPlot, type PlanetPlotFile } from '$lib/fetch/groups/planet-plot';
	import {
		planetPlotPoints,
		PLANET_PLOT_COLORS,
		type PlanetPlotKind
	} from '$lib/charts/planet-plot';
	import type { NotableMemberEntry } from '$lib/fetch/objects/object-data';
	import PlanetScatter from './PlanetScatter.svelte';

	interface Props {
		/** The Solar System planets, for their names. */
		solarMembers: NotableMemberEntry[];
		/** Localized names where they differ from the global ones. */
		localizedNames?: Record<string, string>;
		/** The overview is the tab in view. */
		active: boolean;
	}

	let { solarMembers, localizedNames, active }: Props = $props();

	const HEIGHT = 240;
	const CHARTS: { kind: PlanetPlotKind; title: () => string }[] = [
		{ kind: 'radius', title: m.planet_plot_mass_radius_title },
		{ kind: 'distance', title: m.planet_plot_mass_distance_title }
	];

	let file = $state.raw<PlanetPlotFile | null>(null);
	// Without the file the charts go, rather than pulse as if still loading.
	let failed = $state(false);
	$effect(() => {
		if (!active) return;
		let live = true;
		untrack(fetchPlanetPlot).then(
			(f) => {
				if (live) file = f;
			},
			(e: unknown) => {
				console.warn('[planets] no plot file:', e);
				if (live) failed = true;
			}
		);
		return () => {
			live = false;
		};
	});

	let pointsByKind = $derived(
		file
			? { radius: planetPlotPoints(file, 'radius'), distance: planetPlotPoints(file, 'distance') }
			: null
	);

	let names = $derived(
		Object.fromEntries(
			solarMembers.flatMap((e) => (e.id ? [[e.id, localizedNames?.[e.id] ?? e.name]] : []))
		)
	);
</script>

{#each failed ? [] : CHARTS as chart (chart.kind)}
	{@const points = pointsByKind?.[chart.kind]}
	<div class="flex flex-col gap-1">
		<h3 class="text-sm font-medium">{chart.title()}</h3>
		<div class="border-border/60 border-t"></div>
		<div class="pt-1">
			{#if points}
				<PlanetScatter
					{points}
					kind={chart.kind}
					{names}
					ariaLabel={chart.title()}
					height={HEIGHT}
				/>
			{:else}
				<Skeleton class="w-full rounded-md" style="height: {HEIGHT}px" />
			{/if}
		</div>
		{#if points}
			<div
				class="text-muted-foreground flex flex-wrap items-center gap-x-3 gap-y-1 pt-1 text-[11px]"
			>
				<span class="flex items-center gap-1.5">
					<svg class="size-2" viewBox="0 0 8 8" aria-hidden="true">
						<circle cx="4" cy="4" r="3" fill={PLANET_PLOT_COLORS.measured} />
					</svg>
					{m.planet_plot_legend_measured()}
				</span>
				{#if points.minimum.length > 0}
					<span class="flex items-center gap-1.5">
						<svg class="size-2" viewBox="0 0 8 8" aria-hidden="true">
							<circle cx="4" cy="4" r="2.5" fill="none" stroke={PLANET_PLOT_COLORS.minimum} />
						</svg>
						{m.planet_plot_legend_minimum()}
					</span>
				{/if}
				<span class="flex items-center gap-1.5">
					<svg class="size-2" viewBox="0 0 8 8" aria-hidden="true">
						<circle cx="4" cy="4" r="3.5" class="fill-foreground" />
					</svg>
					{m.tab_solar_system()}
				</span>
				{#if points.estimated > 0}
					<span class="ms-auto">
						{m.planet_plot_estimated({ count: formatNumber(points.estimated) })}
					</span>
				{/if}
			</div>
		{/if}
	</div>
{/each}
