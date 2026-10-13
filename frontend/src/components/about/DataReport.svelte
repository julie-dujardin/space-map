<!--
  The data table itself: one row per map of each world, and one per patch of a
  map. The page around it draws before this does, so it takes the payload
  already resolved.
-->
<script lang="ts">
	import * as m from '$lib/paraglide/messages.js';
	import { formatIsoDate } from '$lib/format/date';
	import { formatBytes } from '$lib/format/bytes';
	import { ltrIsolate } from '$lib/format/bidi';
	import { formatNumber, formatQuantity, formatUnit, ucfirst } from '$lib/format/quantities';
	import { getLocale } from '$lib/host';
	import { layerLabel } from '$lib/credits/imagery-layers';
	import { bodyHref } from '$lib/state/page-href';
	import type { LabelMap } from '$lib/fetch/position/labels';
	import {
		listedSources,
		mapFigures,
		totals,
		type AboutData,
		type MapPatch,
		type MapSource,
		type WorldMap
	} from '$lib/about/data-payload';

	interface Props {
		data: AboutData;
		/** Names in the language of the reader, by object id. */
		labels: LabelMap;
	}

	let { data, labels }: Props = $props();

	/** The name of a body in the language of the reader, else its English one. */
	function named(id: string | undefined, fallback: string): string {
		return (id && labels.get(id)?.name) || fallback;
	}

	const sum = $derived(totals(data));

	const EM_DASH = '—';

	// Column widths, shared by the header and every row.
	const WORLD = 'sm:w-28 sm:shrink-0';
	const RESOLUTION = 'w-20 shrink-0 text-end sm:w-24';
	const EXTENT = 'hidden w-48 shrink-0 text-end lg:block';
	const TILES = 'hidden w-20 shrink-0 text-end sm:block';
	const SIZE = 'w-20 shrink-0 text-end';

	function count(n: number): string {
		return n.toLocaleString(getLocale());
	}

	/** "10.2 m", "1.3 km". The rounded figure decides the unit, so 999.6 m
	 *  reads "1 km". */
	function distance(metres: number): string {
		const rounded = Number(metres.toPrecision(3));
		return rounded >= 1000
			? formatQuantity({ value: rounded / 1000, unit: 'kilometre' }, true)
			: formatQuantity({ value: rounded, unit: 'metre' }, true);
	}

	function resolution(metres: number | undefined): string {
		return metres === undefined ? EM_DASH : distance(metres);
	}

	function pixels(width: number | undefined, height: number | undefined): string {
		if (width === undefined || height === undefined) return EM_DASH;
		return ltrIsolate(m.about_data_pixels({ width: count(width), height: count(height) }));
	}

	function ground(patch: MapPatch): string {
		if (patch.width_km === undefined || patch.height_km === undefined) return EM_DASH;
		const unit = formatUnit('kilometre', true);
		return ltrIsolate(`${formatNumber(patch.width_km)} × ${formatNumber(patch.height_km)} ${unit}`);
	}

	/** "-60°", "+84°". */
	function latitude(degrees: number): string {
		const figure = new Intl.NumberFormat(getLocale(), {
			signDisplay: 'exceptZero',
			maximumFractionDigits: 0
		}).format(degrees);
		return ltrIsolate(`${figure}°`);
	}

	function sourceNote(source: MapSource, sharpened: boolean): string {
		const figure = resolution(source.m_per_px);
		let note = figure;
		if (source.role === 'detail') note = m.about_data_source_detail({ resolution: figure });
		else if (sharpened) note = m.about_data_source_colour({ resolution: figure });
		if (!source.lat_range) return note;
		const [south, north] = source.lat_range;
		return m.about_data_latitudes({
			source: note,
			south: latitude(south),
			north: latitude(north)
		});
	}

	/** What the row of a map does not say, one line each: the sources of its
	 *  pyramid, then the facts of the map itself. */
	function notes(map: WorldMap): string[] {
		const sources = map.tiles ? listedSources(map.tiles) : [];
		const sharpened = sources.some((source) => source.role === 'detail');
		const made = sources
			.filter((source) => source.m_per_px !== undefined)
			.map((source) => sourceNote(source, sharpened));
		const facts: string[] = [];
		if (map.frames) facts.push(m.about_data_frames({ count: count(map.frames) }));
		const step = mapFigures(map).height_step_m;
		if (step !== undefined) facts.push(m.about_data_height_step({ step: distance(step) }));
		return [made, facts].filter((line) => line.length > 0).map((line) => line.join(' · '));
	}

	const stats = $derived([
		{ label: m.about_data_worlds(), value: count(sum.worlds) },
		{ label: m.about_data_maps(), value: count(sum.maps) },
		{ label: m.about_data_column_tiles(), value: count(sum.tiles) },
		{ label: m.about_data_column_size(), value: formatBytes(sum.size_bytes) }
	]);
</script>

<!-- The figures a narrow screen has no column for go under the name. -->
{#snippet under(extent: string, tiles: number | undefined)}
	<div class="text-xs text-muted-subtle tabular-nums lg:hidden">{extent}</div>
	{#if tiles !== undefined}
		<div class="text-xs text-muted-subtle tabular-nums sm:hidden">
			{m.about_data_tiles_count({ count: count(tiles) })}
		</div>
	{/if}
{/snippet}

<div class="text-sm leading-relaxed">
	<p class="-mt-6 mb-2 text-xs text-muted-subtle">
		{m.status_generated({ date: formatIsoDate(data.generated_at) })}
	</p>
	<p class="mt-1.5 max-w-prose text-muted-foreground">{m.about_data_intro()}</p>

	<dl class="mt-6 grid grid-cols-2 gap-x-6 gap-y-4 sm:grid-cols-4">
		{#each stats as stat (stat.label)}
			<div>
				<dt class="text-xs font-semibold uppercase tracking-wider text-muted-subtle">
					{stat.label}
				</dt>
				<dd class="text-xl tabular-nums">{stat.value}</dd>
			</div>
		{/each}
	</dl>

	<div
		class="mt-8 flex items-baseline gap-4 border-b border-border pb-1.5 text-xs font-semibold uppercase tracking-wider text-muted-subtle"
	>
		<div class="hidden {WORLD} sm:block">{m.about_data_column_world()}</div>
		<div class="min-w-0 flex-1">{m.about_data_column_map()}</div>
		<div class={RESOLUTION}>{m.about_data_column_resolution()}</div>
		<div class={EXTENT}>{m.about_data_column_extent()}</div>
		<div class={TILES}>{m.about_data_column_tiles()}</div>
		<div class={SIZE}>{m.about_data_column_size()}</div>
	</div>

	{#each data.systems as system (system.id)}
		<section>
			<h2 class="mt-7 mb-1 text-xs font-semibold uppercase tracking-wider text-muted-foreground">
				{system.name === null ? m.credits_other_bodies() : named(system.primary_id, system.name)}
			</h2>
			{#each system.worlds as world (world.id)}
				{@const name = named(world.id, world.name)}
				<div class="border-b border-border py-2.5 sm:flex sm:gap-4">
					<h3 class="font-medium {WORLD}">
						<a href={bodyHref(world.id, name)} class="hover:underline underline-offset-2">{name}</a>
					</h3>
					<ul class="flex min-w-0 flex-1 flex-col gap-2.5">
						{#each world.maps as map (map.id)}
							{@const figures = mapFigures(map)}
							{@const details = notes(map)}
							<li>
								<div class="flex items-baseline gap-4">
									<div class="min-w-0 flex-1">
										{ucfirst(layerLabel(map.layer))}
										{#if map.alternate}
											<span class="text-muted-subtle">· {m.about_data_alternate()}</span>
										{/if}
										{@render under(pixels(figures.width, figures.height), figures.tiles)}
										{#each details as line (line)}
											<div class="text-xs text-muted-subtle">{line}</div>
										{/each}
									</div>
									<div class="{RESOLUTION} tabular-nums">{resolution(figures.m_per_px)}</div>
									<div class="{EXTENT} text-muted-foreground tabular-nums">
										{pixels(figures.width, figures.height)}
									</div>
									<div class="{TILES} text-muted-foreground tabular-nums">
										{figures.tiles === undefined ? EM_DASH : count(figures.tiles)}
									</div>
									<div class="{SIZE} text-muted-foreground tabular-nums">
										{formatBytes(figures.size_bytes)}
									</div>
								</div>
								{#if map.tiles?.patches}
									<ul class="mt-1.5 flex flex-col gap-1.5">
										{#each map.tiles.patches as patch (patch.id)}
											<li class="flex items-baseline gap-4">
												<div class="min-w-0 flex-1 ps-4">
													{patch.name}
													{@render under(ground(patch), patch.tiles)}
												</div>
												<div class="{RESOLUTION} tabular-nums">{resolution(patch.m_per_px)}</div>
												<div class="{EXTENT} text-muted-foreground tabular-nums">
													{ground(patch)}
												</div>
												<div class="{TILES} text-muted-foreground tabular-nums">
													{count(patch.tiles)}
												</div>
												<div class="{SIZE} text-muted-foreground tabular-nums">
													{formatBytes(patch.size_bytes)}
												</div>
											</li>
										{/each}
									</ul>
								{/if}
							</li>
						{/each}
					</ul>
				</div>
			{/each}
		</section>
	{/each}
</div>
